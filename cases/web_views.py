"""
Staff web dashboard (the "SALAMA Admin" portal): KPIs, recent cases, CHW workload,
case list with assignment. Admin-role users only. Survivors' free-text
descriptions and phone numbers are deliberately NOT shown here; open the case in
/admin/ for that.
"""
from functools import wraps

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from accounts.models import User

from .models import OPEN_STATUSES, Case, CaseStatus, CaseType
from .services import workflow
from .stats import stats_for


def admin_required(view):
    @wraps(view)
    @login_required
    def wrapper(request, *args, **kwargs):
        if not request.user.is_salama_admin:
            raise PermissionDenied
        return view(request, *args, **kwargs)

    return wrapper


def _delta(now, before):
    if not before:
        return None
    return round((now - before) * 100 / before)


@admin_required
def index(request):
    stats = stats_for(Case.objects.all())
    peak = max([d["count"] for d in stats["trend"]] + [1])
    for d in stats["trend"]:
        d["pct"] = max(3, round(d["count"] * 100 / peak)) if d["count"] else 0
    recent = Case.objects.select_related("assigned_to")[:8]
    chws = (
        User.objects.filter(role=User.Role.CHW, is_active=True)
        .annotate(open_cases=Count("cases", filter=Q(cases__status__in=OPEN_STATUSES)))
        .order_by("username")
    )
    type_rows = [
        {"label": label, "count": stats["by_type"].get(value, 0)}
        for value, label in CaseType.choices
    ]
    return render(request, "dashboard/index.html", {
        "stats": stats,
        "week_delta": _delta(stats["last_7_days"], stats["previous_7_days"]),
        "recent": recent,
        "chws": chws,
        "type_rows": type_rows,
        "active_nav": "dashboard",
    })


@admin_required
def case_list(request):
    qs = Case.objects.select_related("assigned_to")
    status = request.GET.get("status", "")
    ctype = request.GET.get("type", "")
    who = request.GET.get("assigned", "")
    if status in CaseStatus.values:
        qs = qs.filter(status=status)
    if ctype in CaseType.values:
        qs = qs.filter(type=ctype)
    if who == "none":
        qs = qs.filter(assigned_to__isnull=True)
    page = Paginator(qs, 25).get_page(request.GET.get("page"))
    return render(request, "dashboard/cases.html", {
        "page": page,
        "chws": User.objects.filter(role=User.Role.CHW, is_active=True).order_by("username"),
        "statuses": CaseStatus.choices,
        "types": CaseType.choices,
        "f_status": status, "f_type": ctype, "f_assigned": who,
        "active_nav": "cases",
    })


@admin_required
@require_POST
def assign(request, pk):
    case = get_object_or_404(Case, pk=pk)
    chw_id = request.POST.get("chw", "")
    chw = None
    if chw_id:
        chw = get_object_or_404(User, pk=chw_id, role=User.Role.CHW, is_active=True)
    workflow.assign_case(case, chw, request.user)
    messages.success(request, f"{case.case_ref}: assigned to {chw.display_name if chw else 'nobody'}.")
    return redirect(request.POST.get("next") or "dashboard:cases")


@admin_required
def chw_list(request):
    chws = (
        User.objects.filter(role=User.Role.CHW)
        .annotate(
            open_cases=Count("cases", filter=Q(cases__status__in=OPEN_STATUSES)),
            total_cases=Count("cases"),
        )
        .order_by("username")
    )
    return render(request, "dashboard/chws.html", {"chws": chws, "active_nav": "chws"})
