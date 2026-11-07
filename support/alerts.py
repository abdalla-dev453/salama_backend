"""Timed jobs: check-in alerts and SOS escalation. Run them every minute (see V6_SETUP.md)."""
import logging
from datetime import timedelta

from django.conf import settings
from django.utils import timezone

from accounts.models import User
from cases.models import WAITING_STATUSES, Case, CaseType
from cases.services.notify import send_sms

from .models import CheckIn, Escalation

logger = logging.getLogger(__name__)


def process_checkins(now=None):
    """Text the contacts of every overdue check-in once. Returns how many were alerted."""
    now = now or timezone.now()
    n = 0
    for c in CheckIn.objects.filter(active=True, alerted=False, due_at__lte=now):
        phones = c.contact_list()
        text = "SALAMA safety alert: a person who named you as a trusted contact has not checked in as planned."
        if c.note:
            text += f" Note: {c.note}"
        text += " Please try to reach her now."
        sent = send_sms(phones, text) if phones else False
        c.alerted = True  # never repeat (a repeat SMS could itself put her at risk)
        c.active = False
        c.save(update_fields=["alerted", "active", "updated_at"])
        n += 1
        if not sent:
            logger.warning("check-in %s overdue but SMS not sent (is Africa's Talking set up?)", c.device_id)
    return n


def _admin_phones():
    extra = [p for p in getattr(settings, "ADMIN_ALERT_PHONES", []) if p]
    db = list(User.objects.filter(role=User.Role.ADMIN, is_active=True).exclude(phone="").values_list("phone", flat=True))
    return list(dict.fromkeys(extra + db))


def escalate_sos(now=None):
    """
    Level 1: an SOS still unanswered after SOS_ESCALATE_MINUTES -> SMS all CHWs + admins.
    Level 2: still unanswered after twice that -> SMS admins again, louder.
    No personal data in the texts. Returns number of escalations sent.
    """
    now = now or timezone.now()
    base = getattr(settings, "SOS_ESCALATE_MINUTES", 10)
    sent = 0
    for level, mins in ((1, base), (2, base * 2)):
        due = Case.objects.filter(
            type=CaseType.SOS, status__in=WAITING_STATUSES, received_at__lte=now - timedelta(minutes=mins)
        ).exclude(escalations__level__gte=level)
        for case in due:
            phones = list(User.objects.filter(is_active=True).exclude(phone="").filter(
                role__in=[User.Role.CHW, User.Role.ADMIN]).values_list("phone", flat=True)) \
                if level == 1 else _admin_phones()
            send_sms(list(dict.fromkeys(phones + _admin_phones())),
                     f"SALAMA URGENT: SOS {case.case_ref} still has no response after {mins} min. Open the app now.")
            Escalation.objects.get_or_create(case=case, level=level)
            sent += 1
    return sent


def alert_unassigned(now=None):
    """Tell admins once per case when a non-SOS case has been unassigned for UNASSIGNED_ALERT_HOURS."""
    now = now or timezone.now()
    hours = getattr(settings, "UNASSIGNED_ALERT_HOURS", 24)
    qs = Case.objects.filter(assigned_to__isnull=True, status="new", received_at__lte=now - timedelta(hours=hours)) \
        .exclude(type=CaseType.SOS).exclude(escalations__level=9)
    refs = list(qs.values_list("case_ref", flat=True)[:20])
    if refs:
        send_sms(_admin_phones(), f"SALAMA: {len(refs)} case(s) unassigned for over {hours}h, e.g. {refs[0]}. Open the dashboard.")
        for c in qs[:20]:
            Escalation.objects.get_or_create(case=c, level=9)
    return len(refs)