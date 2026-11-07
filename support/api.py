import io
import re
import uuid as uuidlib
from datetime import timedelta

from cryptography.fernet import InvalidToken
from django.conf import settings
from django.db.models import Max
from django.http import HttpResponse
from django.utils import timezone
from rest_framework import serializers
from rest_framework import status as http
from rest_framework.generics import get_object_or_404
from rest_framework.parsers import JSONParser, MultiPartParser
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from accounts.permissions import IsStaffMember
from cases.fields import _fernet
from cases.models import CASE_REF_REGEX, Case, CaseType, WAITING_STATUSES
from cases.phones import normalize_ke_phone
from cases.views import visible_cases
from extras.models import FollowUp, Referral

from . import push
from .models import (
    Article, ChatMessage, CheckIn, Evidence, Feedback, SurvivorDevice, Subscriber, VisitNote,
)


def _case_by_ref(ref):
    ref = (ref or "").strip().upper()
    if not re.match(CASE_REF_REGEX, ref):
        return None
    return Case.objects.filter(case_ref=ref).first()


class Anon(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "chat"


def _msg(m):
    return {"id": m.id, "from": m.sender, "text": m.text, "at": m.created_at.isoformat()}


def _after(request):
    try:
        return int(request.query_params.get("after", 0))
    except ValueError:
        return 0


class TextSer(serializers.Serializer):
    text = serializers.CharField(max_length=1000, trim_whitespace=True)


# ------------------------------------------------------------------ chat
class SurvivorChat(Anon):
    def get(self, request, case_ref):
        case = _case_by_ref(case_ref)
        if not case:
            return Response({"found": False}, status=404)
        qs = case.chat.filter(id__gt=_after(request))[:200]
        return Response({"messages": [_msg(m) for m in qs]})

    def post(self, request, case_ref):
        case = _case_by_ref(case_ref)
        if not case:
            return Response({"found": False}, status=404)
        ser = TextSer(data=request.data)
        ser.is_valid(raise_exception=True)
        m = ChatMessage.objects.create(case=case, sender="survivor", text=ser.validated_data["text"])
        if case.assigned_to_id:
            push.push_user(case.assigned_to)
        return Response(_msg(m), status=201)


class StaffChat(APIView):
    permission_classes = [IsStaffMember]

    def _case(self, request, case_id):
        return get_object_or_404(visible_cases(request.user), pk=case_id)

    def get(self, request, case_id):
        case = self._case(request, case_id)
        qs = case.chat.filter(id__gt=_after(request))[:200]
        return Response({"messages": [_msg(m) for m in qs]})

    def post(self, request, case_id):
        case = self._case(request, case_id)
        ser = TextSer(data=request.data)
        ser.is_valid(raise_exception=True)
        m = ChatMessage.objects.create(
            case=case, sender="chw", author=request.user, text=ser.validated_data["text"]
        )
        push.push_survivor(case.case_ref)
        return Response(_msg(m), status=201)


class SurvivorDeviceView(Anon):
    def post(self, request):
        ref = str(request.data.get("case_ref", ""))
        token = str(request.data.get("token", ""))[:400]
        if not token or not _case_by_ref(ref):
            return Response({"detail": "invalid"}, status=400)
        SurvivorDevice.objects.update_or_create(token=token, defaults={"case_ref": ref.strip().upper()})
        return Response(status=204)


# ------------------------------------------------------------------ evidence
MAX_EVIDENCE = 5 * 1024 * 1024
MAX_PER_CASE = 10


def clean_image(raw: bytes):
    """Re-encode the image: drops EXIF (GPS, device) and anything hidden in metadata."""
    from PIL import Image, ImageOps

    img = Image.open(io.BytesIO(raw))
    fmt = (img.format or "").upper()
    if fmt not in ("JPEG", "PNG", "WEBP"):
        raise ValueError("format")
    img = ImageOps.exif_transpose(img)
    img.load()
    out = io.BytesIO()
    if fmt == "JPEG":
        img.convert("RGB").save(out, "JPEG", quality=85)
        return out.getvalue(), "image/jpeg"
    if fmt == "PNG":
        img.save(out, "PNG")
        return out.getvalue(), "image/png"
    img.save(out, "WEBP", quality=85)
    return out.getvalue(), "image/webp"


class EvidenceUpload(Anon):
    parser_classes = [MultiPartParser]
    throttle_scope = "evidence"

    def post(self, request, case_ref):
        case = _case_by_ref(case_ref)
        if not case:
            return Response({"found": False}, status=404)
        f = request.FILES.get("file")
        if not f or f.size > MAX_EVIDENCE:
            return Response({"detail": "Photo missing or larger than 5 MB."}, status=400)
        if case.evidence.count() >= MAX_PER_CASE:
            return Response({"detail": "Photo limit reached."}, status=400)
        try:
            data, ctype = clean_image(f.read())
        except Exception:  # noqa: BLE001
            return Response({"detail": "Not a valid photo (jpeg, png or webp)."}, status=400)
        ev = Evidence.objects.create(
            case=case, data=_fernet().encrypt(data), content_type=ctype, size=len(data)
        )
        return Response({"id": ev.id}, status=201)


class CaseEvidenceList(APIView):
    permission_classes = [IsStaffMember]

    def get(self, request, case_id):
        case = get_object_or_404(visible_cases(request.user), pk=case_id)
        return Response({"items": [
            {"id": e.id, "size": e.size, "at": e.created_at.isoformat(), "content_type": e.content_type}
            for e in case.evidence.all()
        ]})


class EvidenceItem(APIView):
    permission_classes = [IsStaffMember]

    def get(self, request, pk):
        ev = get_object_or_404(Evidence.objects.select_related("case"), pk=pk)
        if not visible_cases(request.user).filter(pk=ev.case_id).exists():
            return Response(status=404)
        try:
            raw = _fernet().decrypt(bytes(ev.data))
        except InvalidToken:
            return Response(status=500)
        return HttpResponse(raw, content_type=ev.content_type)


# ------------------------------------------------------------------ check-in
class CheckInView(Anon):
    throttle_scope = "checkin"

    def _obj(self, device_id):
        return CheckIn.objects.filter(device_id=device_id).first()

    def get(self, request, device_id):
        c = self._obj(device_id)
        if not c:
            return Response({"active": False, "due_at": None, "alerted": False})
        return Response({"active": c.active, "due_at": c.due_at.isoformat(), "alerted": c.alerted})

    def put(self, request, device_id):
        try:
            minutes = int(request.data.get("minutes"))
        except (TypeError, ValueError):
            return Response({"detail": "minutes required"}, status=400)
        if not 5 <= minutes <= 1440:
            return Response({"detail": "minutes must be 5..1440"}, status=400)
        raw = request.data.get("contacts") or []
        if not isinstance(raw, list) or not 1 <= len(raw) <= 3:
            return Response({"detail": "1 to 3 contacts"}, status=400)
        try:
            contacts = [normalize_ke_phone(str(p)) for p in raw]
        except ValueError:
            return Response({"detail": "Enter Kenyan mobile numbers."}, status=400)
        if not all(contacts):
            return Response({"detail": "Enter Kenyan mobile numbers."}, status=400)
        c, _ = CheckIn.objects.update_or_create(
            device_id=device_id,
            defaults=dict(
                due_at=timezone.now() + timedelta(minutes=minutes),
                contacts=",".join(dict.fromkeys(contacts)),
                note=str(request.data.get("note", ""))[:140],
                case_ref=str(request.data.get("case_ref", ""))[:32],
                active=True, alerted=False,
            ),
        )
        return Response({"due_at": c.due_at.isoformat(), "active": True})


class CheckInOk(Anon):
    throttle_scope = "checkin"

    def post(self, request, device_id):
        CheckIn.objects.filter(device_id=device_id).update(active=False)
        return Response({"active": False})


# ------------------------------------------------------------------ feedback / content
class FeedbackSer(serializers.Serializer):
    case_ref = serializers.CharField(required=False, allow_blank=True, max_length=32)
    rating = serializers.IntegerField(min_value=1, max_value=5)
    helped = serializers.BooleanField(required=False, default=False)
    comment = serializers.CharField(required=False, allow_blank=True, max_length=300)
    lang = serializers.ChoiceField(choices=["en", "sw"], required=False, default="en")


class FeedbackView(Anon):
    throttle_scope = "feedback"

    def post(self, request):
        s = FeedbackSer(data=request.data)
        s.is_valid(raise_exception=True)
        Feedback.objects.create(**s.validated_data)
        return Response(status=201)


class AwarenessView(Anon):
    throttle_scope = "public_read"

    def get(self, request):
        items = list(Article.objects.filter(is_active=True))
        version = max((a.updated_at for a in items), default=None)
        return Response({
            "version": version.isoformat() if version else None,
            "items": [
                {"id": a.id, "title_en": a.title_en, "title_sw": a.title_sw or a.title_en,
                 "body_en": a.body_en, "body_sw": a.body_sw or a.body_en, "quiz": a.quiz}
                for a in items
            ],
        })


class SubscribeView(Anon):
    throttle_scope = "subscribe"

    def _phone(self, request):
        try:
            return normalize_ke_phone(str(request.data.get("phone", "")))
        except ValueError:
            return ""

    def post(self, request):
        p = self._phone(request)
        if not p:
            return Response({"detail": "Enter a Kenyan mobile number."}, status=400)
        Subscriber.objects.update_or_create(
            phone_hash=Subscriber.hash_phone(p),
            defaults=dict(
                phone=p, area=str(request.data.get("area", ""))[:80],
                lang="en" if request.data.get("lang") == "en" else "sw",
            ),
        )
        return Response(status=201)

    def delete(self, request):
        p = self._phone(request)
        if p:
            Subscriber.objects.filter(phone_hash=Subscriber.hash_phone(p)).delete()
        return Response(status=204)


# ------------------------------------------------------------------ staff task inbox
class MyTasks(APIView):
    permission_classes = [IsStaffMember]

    def get(self, request):
        user = request.user
        cases = visible_cases(user)
        mine = cases if user.is_salama_admin else cases.filter(assigned_to=user)
        today = timezone.localdate()
        tasks = []

        def add(kind, urgency, case, en, sw, due=None):
            tasks.append({
                "kind": kind, "urgency": urgency, "case_id": str(case.id), "case_ref": case.case_ref,
                "title_en": en, "title_sw": sw, "due": due.isoformat() if due else None,
            })

        for c in cases.filter(type=CaseType.SOS, status__in=WAITING_STATUSES):
            add("sos", 3, c, "Urgent SOS - respond now", "SOS ya dharura - jibu sasa")
        # a survivor wrote last
        last = dict(mine.filter(chat__isnull=False).annotate(m=Max("chat__id")).values_list("id", "m"))
        if last:
            latest = {m.case_id: m for m in ChatMessage.objects.filter(id__in=last.values())}
            for c in mine.filter(id__in=last.keys()):
                m = latest.get(c.id)
                if m and m.sender == "survivor":
                    add("message", 2, c, "New message from survivor", "Ujumbe mpya kutoka kwa mhusika")
        for f in FollowUp.objects.filter(
            case__in=mine, done=False, due_date__lte=today + timedelta(days=1)
        ).select_related("case"):
            late = f.due_date < today
            add("followup", 2 if late else 1, f.case,
                "Follow-up overdue" if late else "Follow-up due",
                "Ufuatiliaji umechelewa" if late else "Ufuatiliaji unakaribia", f.due_date)
        for r in Referral.objects.filter(case__in=mine, outcome="pending").select_related("case"):
            if r.created_at < timezone.now() - timedelta(days=3):
                add("referral", 1, r.case, "Referral outcome not recorded", "Matokeo ya rufaa hayajaandikwa")
        for c in cases.filter(assigned_to__isnull=True, status="new").exclude(type=CaseType.SOS)[:50]:
            add("unassigned", 1, c, "Unassigned case - claim it", "Kesi haina mhusika - ichukue")

        tasks.sort(key=lambda t: (-t["urgency"], t["due"] or "9999"))
        counts = {k: 0 for k in ("sos", "message", "followup", "referral", "unassigned")}
        for t in tasks:
            counts[t["kind"]] += 1
        return Response({"tasks": tasks[:200], "counts": counts})


# ------------------------------------------------------------------ visit notes
class VisitSer(serializers.ModelSerializer):
    author_name = serializers.SerializerMethodField()

    class Meta:
        model = VisitNote
        fields = ["id", "visit_date", "risk_level", "safe_at_home", "injuries", "needs",
                  "referral_made", "summary", "next_step", "author_name", "created_at"]
        read_only_fields = ["id", "author_name", "created_at"]

    def get_author_name(self, o):
        return o.author.display_name if o.author else ""

    def validate_needs(self, v):
        ok = {"medical", "legal", "shelter", "counseling", "police", "other"}
        if not isinstance(v, list) or any(x not in ok for x in v):
            raise serializers.ValidationError("Unknown need.")
        return v

    def validate_visit_date(self, v):
        if v > timezone.localdate():
            raise serializers.ValidationError("Visit date cannot be in the future.")
        return v


class CaseVisits(APIView):
    permission_classes = [IsStaffMember]

    def get(self, request, case_id):
        case = get_object_or_404(visible_cases(request.user), pk=case_id)
        return Response({"visits": VisitSer(case.visits.select_related("author"), many=True).data})

    def post(self, request, case_id):
        case = get_object_or_404(visible_cases(request.user), pk=case_id)
        s = VisitSer(data=request.data)
        s.is_valid(raise_exception=True)
        s.save(case=case, author=request.user)
        return Response(s.data, status=201)