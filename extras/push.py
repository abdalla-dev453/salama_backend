"""
Push notifications to CHW phones through Firebase Cloud Messaging.

The message holds NO personal data and no location: "new urgent case" only.
The CHW opens the app and logs in to see it.

Setup (see EXTRAS_SETUP.md): pip install firebase-admin, then set
FCM_CREDENTIALS_FILE=/path/to/service-account.json in .env.
Without it, everything here quietly does nothing.
"""
import logging

from django.conf import settings

logger = logging.getLogger(__name__)
_app = None


def _firebase():
    global _app
    path = getattr(settings, "FCM_CREDENTIALS_FILE", "")
    if not path:
        return None
    if _app is None:
        import firebase_admin
        from firebase_admin import credentials

        _app = firebase_admin.initialize_app(credentials.Certificate(path))
    return _app


def push_sos_to_chws(case_ref: str) -> int:
    """Returns how many phones were told. Never raises."""
    try:
        app = _firebase()
        if app is None:
            return 0
        from accounts.models import User
        from firebase_admin import messaging

        from .models import DeviceToken

        tokens = list(
            DeviceToken.objects.filter(
                user__is_active=True, user__role__in=[User.Role.CHW, User.Role.ADMIN]
            ).values_list("token", flat=True)
        )
        sent = 0
        for token in tokens:
            msg = messaging.Message(
                token=token,
                data={"kind": "sos", "ref": case_ref},
                notification=messaging.Notification(
                    title="SALAMA", body="New urgent case / Kesi ya dharura"
                ),
                android=messaging.AndroidConfig(priority="high"),
            )
            try:
                messaging.send(msg, app=app)
                sent += 1
            except (messaging.UnregisteredError, messaging.SenderIdMismatchError):
                DeviceToken.objects.filter(token=token).delete()  # phone uninstalled
            except Exception:  # noqa: BLE001
                logger.exception("push failed for one device")
        return sent
    except Exception:  # noqa: BLE001 - an alert must never break case intake
        logger.exception("push_sos_to_chws failed")
        return 0
