"""
USSD (Africa's Talking) for people with basic phones and no data, e.g. *483*87#.

Africa's Talking POSTs: sessionId, serviceCode, phoneNumber, text
where `text` is everything the user typed so far joined with '*'
(for example "2*1*Ukunda*1"). We answer in plain text starting with
"CON " (session continues) or "END " (session over).

Callback URL to set in Africa's Talking -> USSD -> your code:
  https://api.yourdomain.org/api/ussd/africastalking/?token=<AT_WEBHOOK_TOKEN>

Cases made here use the SMS source (the only non-app source in the database).
"""
import hashlib
import hmac

from django.conf import settings
from django.db import transaction
from django.http import HttpResponse
from django.utils import timezone
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.permissions import AllowAny
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from cases.models import Case, CaseSource, CaseType
from cases.phones import normalize_ke_phone
from cases.services.intake import intake_case

from .models import HelpContact
from .views import SURVIVOR_STATUS

STRINGS = {
    "sw": {
        "menu": "CON SALAMA\n1. Dharura (SOS)\n2. Ripoti tukio\n3. Hali ya kesi\n4. Namba za msaada",
        "sos_safe": "CON Je, ni salama kukupigia simu kwenye namba hii?\n1. Ndiyo\n2. Hapana",
        "sos_done": "END Tumepokea ombi lako la dharura. Msaada unakuja. Kumbukumbu: {ref}",
        "type": "CON Aina ya tukio:\n1. Ukatili\n2. Huduma baada ya utoaji mimba\n3. Ushauri",
        "loc": "CON Uko wapi? (mf. Ukunda, Msambweni, Kinango)",
        "safe": "CON Salama kukupigia simu?\n1. Ndiyo\n2. Hapana",
        "done": "END Tumepokea ripoti yako. Kumbukumbu: {ref}. Mfanyakazi wa afya atakuhudumia.",
        "ref": "CON Weka namba ya kumbukumbu (mf. KWALE-2710-A1B2C3)",
        "status_found": "END Kumbukumbu {ref}: {status}",
        "status_none": "END Kumbukumbu haijapatikana.",
        "st": {"received": "Imepokelewa", "in_progress": "Inashughulikiwa",
               "referred": "Umeelekezwa", "closed": "Imefungwa"},
        "help": "END Msaada: Piga 1195 (bure). Dharura: 999 au 112.",
        "bad": "END Chaguo si sahihi. Jaribu tena.",
    },
    "en": {
        "menu": "CON SALAMA\n1. Emergency (SOS)\n2. Report an incident\n3. Case status\n4. Help numbers",
        "sos_safe": "CON Is it safe to call you on this number?\n1. Yes\n2. No",
        "sos_done": "END We got your emergency. Help is coming. Reference: {ref}",
        "type": "CON Incident type:\n1. Violence\n2. Abortion post-care\n3. Counseling",
        "loc": "CON Where are you? (e.g. Ukunda, Msambweni, Kinango)",
        "safe": "CON Is it safe to call you?\n1. Yes\n2. No",
        "done": "END We got your report. Reference: {ref}. A health worker will help you.",
        "ref": "CON Enter your reference (e.g. KWALE-2710-A1B2C3)",
        "status_found": "END Reference {ref}: {status}",
        "status_none": "END Reference not found.",
        "st": {"received": "Received", "in_progress": "In progress",
               "referred": "Referred", "closed": "Closed"},
        "help": "END Help: call 1195 (free). Emergency: 999 or 112.",
        "bad": "END Invalid choice. Try again.",
    },
}
TYPES = {"1": CaseType.VIOLENCE, "2": CaseType.CARE, "3": CaseType.COUNSELING}


def _ref(session_id: str, sos: bool) -> str:
    """Same session -> same reference, so an Africa's Talking retry never makes a duplicate."""
    code = hashlib.sha1(session_id.encode()).hexdigest()[:6].upper()
    return f"SOS-{code}" if sos else f"KWALE-{timezone.localdate():%d%m}-{code}"


def handle(session_id: str, phone: str, text: str) -> str:
    parts = text.split("*") if text else []
    if not parts:
        return "CON Chagua lugha / Choose language\n1. Kiswahili\n2. English"
    if parts[0] not in ("1", "2"):
        return STRINGS["sw"]["bad"]
    s = STRINGS["sw" if parts[0] == "1" else "en"]
    step = parts[1:]
    try:
        contact = normalize_ke_phone(phone)
    except ValueError:
        contact = ""

    if not step:
        return s["menu"]
    choice = step[0]

    if choice == "1":  # SOS
        if len(step) == 1:
            return s["sos_safe"]
        ref = _ref(session_id, sos=True)
        intake_case(case_ref=ref, type=CaseType.SOS, location_text="USSD",
                    contact_phone=contact, safe_to_call=step[1] == "1",
                    reported_at=timezone.now(), source=CaseSource.SMS)
        return s["sos_done"].format(ref=ref)

    if choice == "2":  # report: type -> location -> safe
        if len(step) == 1:
            return s["type"]
        if step[1] not in TYPES:
            return s["bad"]
        if len(step) == 2:
            return s["loc"]
        if len(step) == 3:
            return s["safe"]
        ref = _ref(session_id, sos=False)
        intake_case(case_ref=ref, type=TYPES[step[1]], location_text=step[2][:200],
                    contact_phone=contact, safe_to_call=step[3] == "1",
                    reported_at=timezone.now(), source=CaseSource.SMS)
        return s["done"].format(ref=ref)

    if choice == "3":  # status
        if len(step) == 1:
            return s["ref"]
        case = Case.objects.filter(case_ref=step[1].strip().upper()).first()
        if not case:
            return s["status_none"]
        label = s["st"][SURVIVOR_STATUS.get(case.status, "received")]
        return s["status_found"].format(ref=case.case_ref, status=label)

    if choice == "4":
        return s["help"]
    return s["bad"]


class UssdView(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]
    parser_classes = [FormParser, MultiPartParser, JSONParser]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "ussd"

    def post(self, request):
        expected = settings.AT_WEBHOOK_TOKEN
        given = request.query_params.get("token") or request.headers.get("X-Webhook-Token", "")
        if not expected or not hmac.compare_digest(given.encode(), expected.encode()):
            return HttpResponse("END Forbidden", status=403, content_type="text/plain")
        d = request.data
        with transaction.atomic():
            reply = handle(
                (d.get("sessionId") or "").strip() or "none",
                (d.get("phoneNumber") or "").strip(),
                (d.get("text") or "").strip(),
            )
        return HttpResponse(reply, content_type="text/plain; charset=utf-8")
