from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from ..models import Case, CaseSource, CaseStatus, CaseType, CaseUpdate
from .notify import notify_chws_of_sos


def _clamp_reported_at(value):
    """Phone clocks can be wrong: never in the future, never older than a year."""
    now = timezone.now()
    if value is None or value > now or value < now - timedelta(days=365):
        return now
    return value


@transaction.atomic
def intake_case(
    *,
    case_ref,
    type,
    description="",
    location_text="",
    lat=None,
    lon=None,
    contact_phone="",
    safe_to_call=False,
    reported_at=None,
    source=CaseSource.APP,
):
    """
    Idempotent. Returns (case, created).

    Creating: stores the case, writes the first audit entry, alerts CHWs if SOS.
    Already exists (e.g. the SMS arrived first, now the app syncs the same case,
    or the app re-sends after a timeout): nothing is duplicated and nothing that
    a CHW may already have worked on is overwritten; only EMPTY fields are filled
    in (description from the app, GPS found a few seconds after the SOS...).
    """
    defaults = {
        "type": type,
        "status": CaseStatus.SOS if type == CaseType.SOS else CaseStatus.NEW,
        "source": source,
        "description": description or "",
        "location_text": location_text or "",
        "lat": lat,
        "lon": lon,
        "contact_phone": contact_phone or "",
        "safe_to_call": bool(safe_to_call),
        "reported_at": _clamp_reported_at(reported_at),
    }
    case, created = Case.objects.get_or_create(case_ref=case_ref, defaults=defaults)

    if created:
        CaseUpdate.objects.create(case=case, kind=CaseUpdate.Kind.CREATED, to_status=case.status)
        if case.type == CaseType.SOS:
            transaction.on_commit(lambda: notify_chws_of_sos(case.case_ref))
        return case, True

    case = Case.objects.select_for_update().get(pk=case.pk)
    changed = []
    if description and not case.description:
        case.description = description
        changed.append("description")
    if location_text and not case.location_text:
        case.location_text = location_text
        changed.append("location_text")
    if lat is not None and lon is not None and case.lat is None:
        case.lat, case.lon = lat, lon
        changed += ["lat", "lon"]
    if contact_phone and not case.contact_phone:
        case.contact_phone = contact_phone
        case.safe_to_call = bool(safe_to_call)
        changed += ["contact_phone", "safe_to_call"]
    if changed:
        case.save(update_fields=changed + ["updated_at"])
    return case, False
