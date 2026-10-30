import logging

import requests
from django.conf import settings

logger = logging.getLogger(__name__)

AT_URL = "https://api.africastalking.com/version1/messaging"
AT_SANDBOX_URL = "https://api.sandbox.africastalking.com/version1/messaging"


def send_sms(phones, message: str) -> bool:
    """Sends an SMS through Africa's Talking. Never raises. Returns True on HTTP success."""
    if not (settings.AT_USERNAME and settings.AT_API_KEY and phones):
        return False
    data = {"username": settings.AT_USERNAME, "to": ",".join(phones), "message": message}
    if settings.AT_SENDER_ID:
        data["from"] = settings.AT_SENDER_ID
    try:
        r = requests.post(
            AT_SANDBOX_URL if settings.AT_SANDBOX else AT_URL,
            data=data,
            headers={"apiKey": settings.AT_API_KEY, "Accept": "application/json"},
            timeout=8,
        )
        r.raise_for_status()
        return True
    except Exception:  # noqa: BLE001 - a failed alert must never break case intake
        logger.exception("Could not send SMS alert")
        return False


def notify_chws_of_sos(case_ref: str) -> None:
    """
    Alerts CHWs of a new SOS: a push notification (if Firebase is set up) and,
    optionally, an SMS. Both contain NO personal data and no location: only the
    reference, so they open the app.
    """
    # 1) push (does nothing unless FCM_CREDENTIALS_FILE is set)
    try:
        from extras.push import push_sos_to_chws

        push_sos_to_chws(case_ref)
    except Exception:  # noqa: BLE001
        logger.exception("push alert failed")

    # 2) SMS (as before)
    if not settings.NOTIFY_CHWS_ON_SOS:
        return
    from accounts.models import User

    phones = list(
        User.objects.filter(role=User.Role.CHW, is_active=True)
        .exclude(phone="")
        .values_list("phone", flat=True)
    )
    send_sms(phones, f"SALAMA SOS {case_ref}. Open the SALAMA app now.")
