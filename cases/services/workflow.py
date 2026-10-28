"""Everything a CHW or admin can do to a case. Used by the API and the web dashboard."""
from django.db import transaction
from rest_framework import status as http
from rest_framework.exceptions import APIException, PermissionDenied

from ..models import Case, CaseUpdate


class Conflict(APIException):
    status_code = http.HTTP_409_CONFLICT
    default_detail = "This case is already assigned to someone else."
    default_code = "conflict"


def _locked(case) -> Case:
    # Lock only the case row ("self"): PostgreSQL cannot lock the nullable side of a join.
    return (
        Case.objects.select_for_update(of=("self",))
        .select_related("assigned_to")
        .get(pk=case.pk)
    )


def _who(user) -> str:
    return user.display_name if user else "nobody"


@transaction.atomic
def assign_case(case, chw, by):
    """Admin assigns (or unassigns with chw=None)."""
    case = _locked(case)
    if case.assigned_to_id == (chw.pk if chw else None):
        return case
    old = case.assigned_to
    case.assigned_to = chw
    case.save(update_fields=["assigned_to", "updated_at"])
    CaseUpdate.objects.create(
        case=case, author=by, kind=CaseUpdate.Kind.ASSIGN,
        note=f"{_who(old)} -> {_who(chw)}",
    )
    return case


@transaction.atomic
def claim_case(case, user):
    """A CHW takes an unassigned case. 409 if somebody already has it."""
    case = _locked(case)
    if case.assigned_to_id == user.pk:
        return case
    if case.assigned_to_id is not None:
        raise Conflict()
    case.assigned_to = user
    case.save(update_fields=["assigned_to", "updated_at"])
    CaseUpdate.objects.create(case=case, author=user, kind=CaseUpdate.Kind.ASSIGN,
                              note=f"nobody -> {_who(user)}")
    return case


@transaction.atomic
def change_status(case, user, new_status, note=""):
    """
    Admin: any case. CHW: own cases, or an unassigned one (which they then own).
    A case assigned to another CHW is off limits.
    """
    case = _locked(case)
    if not user.is_salama_admin:
        if case.assigned_to_id not in (None, user.pk):
            raise PermissionDenied("This case is assigned to another CHW.")
        if case.assigned_to_id is None:
            case.assigned_to = user
            CaseUpdate.objects.create(case=case, author=user, kind=CaseUpdate.Kind.ASSIGN,
                                      note=f"nobody -> {_who(user)}")
    old = case.status
    case.status = new_status
    case.save()
    CaseUpdate.objects.create(
        case=case, author=user, kind=CaseUpdate.Kind.STATUS,
        from_status=old, to_status=new_status, note=note or "",
    )
    return case


@transaction.atomic
def add_note(case, user, note):
    case = _locked(case)
    if not user.is_salama_admin and case.assigned_to_id not in (None, user.pk):
        raise PermissionDenied("This case is assigned to another CHW.")
    CaseUpdate.objects.create(case=case, author=user, kind=CaseUpdate.Kind.NOTE, note=note)
    case.save(update_fields=["updated_at"])
    return case
