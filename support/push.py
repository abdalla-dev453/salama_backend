"""Neutral push notifications (no personal data). Silent no-op unless Firebase is configured."""
import logging

logger = logging.getLogger(__name__)


def _send(tokens, title, body, data):
    try:
        from extras.push import _firebase

        app = _firebase()
        if app is None or not tokens:
            return 0
        from firebase_admin import messaging

        sent = 0
        for t in tokens:
            try:
                messaging.send(
                    messaging.Message(token=t, data=data, notification=messaging.Notification(title=title, body=body)),
                    app=app,
                )
                sent += 1
            except Exception:  # noqa: BLE001
                logger.warning("push to one device failed")
        return sent
    except Exception:  # noqa: BLE001
        logger.exception("push failed")
        return 0


def push_survivor(case_ref):
    from .models import SurvivorDevice

    tokens = list(SurvivorDevice.objects.filter(case_ref=case_ref).values_list("token", flat=True))
    return _send(tokens, "SALAMA", "Update available / Taarifa mpya", {"kind": "update"})


def push_user(user, body="New message / Ujumbe mpya"):
    from extras.models import DeviceToken

    tokens = list(DeviceToken.objects.filter(user=user).values_list("token", flat=True))
    return _send(tokens, "SALAMA", body, {"kind": "message"})