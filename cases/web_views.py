"""
Staff web dashboard (the "SALAMA Admin" portal), v5: sidebar, search, bell, KPI notes,
case map, trend chart with range, recent cases with Assign, CHW management,
Analytics and Settings pages. Admin-role users only.

Privacy: survivors' descriptions and phone numbers are never shown here. The map
shows locations rounded to about 1 km, grouped, with counts.
"""
from datetime import timedelta
from functools import wraps

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.paginator import Paginator
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from accounts.models import User
from cases.phones import normalize_ke_phone

from cases.models import OPEN_STATUSES, WAITING_STATUSES, Case, CaseStatus, CaseType
from cases.services import workflow
from cases.stats import stats_for

try:  # the v4 "extras" app
    from extras import reports as extras_reports
except Exception:  # noqa: BLE001
    extras_reports = None


def admin_required(view):
    @wraps(view)
    @login_required
    def wrapper(request, *args, **kwargs):
        if not request.user.is_salama_admin:
            raise PermissionDenied
        return view(request, *args, **kwargs)

    return wrapper


def _ctx(request, nav, **extra):
    """Things every page needs: bell count, active nav item."""
    urgent = Case.objects.filter(type=CaseType.SOS, status__in=WAITING_STATUSES).count()
    return {"active_nav": nav, "urgent_count": urgent, "q": request.GET.get("q", ""), **extra}


def _pct(now, before):
    if not before:
        return None
    return round((now - before) * 100 / before)


# --------------------------------------------------------------------------- dashboard
@admin_required
def index(request):
    days = int(request.GET.get("days", 30)) if request.GET.get("days") in ("7", "30", "90") else 30
    qs = Case.objects.all()
    now = timezone.now()
    today = timezone.localdate()

    stats = stats_for(qs, days=days)

    # ---- KPI notes (plain counts, labelled exactly)
    last30 = qs.filter(received_at__gte=now - timedelta(days=30)).count()
    prev30 = qs.filter(received_at__gte=now - timedelta(days=60), received_at__lt=now - timedelta(days=30)).count()
    sos_today = qs.filter(type=CaseType.SOS, received_at__date=today).count()
    sos_yesterday = qs.filter(type=CaseType.SOS, received_at__date=today - timedelta(days=1)).count()
    referred_week = qs.filter(status=CaseStatus.REFERRED, updated_at__gte=now - timedelta(days=7)).count()
    closed_month = qs.filter(status=CaseStatus.CLOSED, updated_at__gte=now - timedelta(days=30)).count()

    # ---- trend chart as an SVG polyline (no JS needed)
    W, H, PAD = 640, 170, 12
    counts = [d["count"] for d in stats["trend"]]
    peak = max(counts + [1])
    n = max(len(counts) - 1, 1)
    pts = [(PAD + i * (W - 2 * PAD) / n, H - PAD - c * (H - 2 * PAD) / peak) for i, c in enumerate(counts)]
    line = " ".join(f"{x:.1f},{y:.1f}" for x, y in pts)
    area = f"{PAD},{H - PAD} {line} {W - PAD},{H - PAD}"
    dots = [{"x": round(x, 1), "y": round(y, 1), "t": f'{d["date"]}: {d["count"]}'}
            for (x, y), d in zip(pts, stats["trend"])] if days <= 30 else []

    # ---- cases by type (real SALAMA types)
    total = max(sum(stats["by_type"].values()), 1)
    type_rows = [
        {"label": label, "count": stats["by_type"].get(value, 0),
         "pct": round(stats["by_type"].get(value, 0) * 100 / total)}
        for value, label in CaseType.choices
    ]

    # ---- map: rounded (~1 km) + grouped, never exact points
    clusters = {}
    for lat, lon, status, type_ in qs.filter(lat__isnull=False).values_list("lat", "lon", "status", "type")[:3000]:
        key = (round(lat, 2), round(lon, 2))
        c = clusters.setdefault(key, {"lat": key[0], "lon": key[1], "n": 0, "urgent": False})
        c["n"] += 1
        if type_ == CaseType.SOS and status in WAITING_STATUSES:
            c["urgent"] = True
    no_gps = qs.filter(lat__isnull=True).count()
    open_with_gps = qs.filter(lat__isnull=False, status__in=OPEN_STATUSES).count()

    return render(request, "dashboard/index.html", _ctx(
        request, "dashboard",
        stats=stats, days=days,
        total_delta=_pct(last30, prev30), last30=last30,
        sos_today=sos_today, sos_yesterday=sos_yesterday,
        referred_week=referred_week, closed_month=closed_month,
        line=line, area=area, dots=dots, W=W, H=H,
        type_rows=type_rows,
        clusters=list(clusters.values()), no_gps=no_gps, open_with_gps=open_with_gps,
        recent=Case.objects.select_related("assigned_to")[:5],
        chws=User.objects.filter(role=User.Role.CHW, is_active=True).order_by("username"),
    ))


# --------------------------------------------------------------------------- cases
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
    return render(request, "dashboard/cases.html", _ctx(
        request, "cases", page=page,
        chws=User.objects.filter(role=User.Role.CHW, is_active=True).order_by("username"),
        statuses=CaseStatus.choices, types=CaseType.choices,
        f_status=status, f_type=ctype, f_assigned=who,
    ))


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


# --------------------------------------------------------------------------- CHWs
@admin_required
def chw_list(request):
    if request.method == "POST":
        action = request.POST.get("action")
        if action == "create":
            _create_chw(request)
        elif action in ("toggle", "password"):
            u = get_object_or_404(User, pk=request.POST.get("id"), role=User.Role.CHW)
            if action == "toggle":
                u.is_active = not u.is_active
                u.save(update_fields=["is_active"])
                messages.success(request, f"{u.username}: {'activated' if u.is_active else 'deactivated'}.")
            else:
                pw = request.POST.get("password", "")
                try:
                    validate_password(pw, u)
                except ValidationError as e:
                    messages.error(request, " ".join(e.messages))
                else:
                    u.set_password(pw)
                    u.save(update_fields=["password"])
                    messages.success(request, f"{u.username}: password changed.")
        return redirect("dashboard:chws")

    chws = (
        User.objects.filter(role=User.Role.CHW)
        .annotate(open_cases=Count("cases", filter=Q(cases__status__in=OPEN_STATUSES)),
                  total_cases=Count("cases"))
        .order_by("username")
    )
    return render(request, "dashboard/chws.html", _ctx(request, "chws", chws=chws))


def _create_chw(request):
    p = request.POST
    username = p.get("username", "").strip().upper()
    if not username or User.objects.filter(username__iexact=username).exists():
        messages.error(request, "Choose a CHW ID that is not already used (e.g. CHW-KWALE-005).")
        return
    phone = p.get("phone", "").strip()
    if phone:
        try:
            phone = normalize_ke_phone(phone)
        except ValueError:
            messages.error(request, "Enter a valid Kenyan phone number or leave it empty.")
            return
    user = User(username=username, full_name=p.get("full_name", "").strip(),
                phone=phone, area=p.get("area", "").strip(), role=User.Role.CHW)
    try:
        validate_password(p.get("password", ""), user)
    except ValidationError as e:
        messages.error(request, " ".join(e.messages))
        return
    user.set_password(p["password"])
    user.save()
    messages.success(request, f"CHW {user.username} created. Give them the password in person.")


# --------------------------------------------------------------------------- analytics
@admin_required
def analytics(request):
    ctx = {"enabled": extras_reports is not None}
    if extras_reports is not None:
        qs = extras_reports.report_queryset(request.GET)
        rows = extras_reports.anonymous_rows(qs)
        types = [v for v, _ in CaseType.choices]
        pivot = {}
        for _m, area, type_, n in rows:
            pivot.setdefault(area, {t: 0 for t in types})[type_] += n
        pivot_rows = []
        for area, by in sorted(pivot.items()):
            total = sum(by.values())
            pivot_rows.append({
                "area": area, "total": extras_reports._cell(total),
                "cells": [extras_reports._cell(by[t]) for t in types],
            })
        ctx.update(pivot_rows=pivot_rows, type_labels=[l for _, l in CaseType.choices],
                   times=extras_reports.response_times(qs), min_cell=extras_reports.MIN_CELL,
                   date_from=request.GET.get("from", ""), date_to=request.GET.get("to", ""),
                   qs_string=request.GET.urlencode())
    return render(request, "dashboard/analytics.html", _ctx(request, "analytics", **ctx))


# --------------------------------------------------------------------------- settings (read-only status)
@admin_required
def settings_page(request):
    def yes(v):
        return bool(v)

    checks = [
        ("Data encryption keys", yes(settings.FIELD_ENCRYPTION_KEYS), "Required. Back them up separately from the database."),
        ("Debug mode off", not settings.DEBUG, "Must be off on the live server."),
        ("Africa's Talking SMS webhook token", yes(settings.AT_WEBHOOK_TOKEN), "Needed for incoming SMS and USSD."),
        ("Africa's Talking sending (SMS alerts)", yes(settings.AT_USERNAME and settings.AT_API_KEY), "Optional: texts CHWs on SOS."),
        ("SMS alert to CHWs on SOS", yes(settings.NOTIFY_CHWS_ON_SOS), "Optional."),
        ("Push alerts (Firebase)", yes(getattr(settings, "FCM_CREDENTIALS_FILE", "")), "Optional: needs the Firebase key file."),
        ("Survivor app key", yes(settings.SURVIVOR_API_KEY), "Optional; not a secret."),
    ]
    links = [
        ("Users (admins and CHWs)", "/admin/accounts/user/"),
        ("Help contacts (clinics, police desks, safe houses)", "/admin/extras/helpcontact/"),
        ("Inbound SMS inbox", "/admin/cases/smsinbound/"),
        ("All cases (full details)", "/admin/cases/case/"),
    ]
    return render(request, "dashboard/settings.html", _ctx(request, "settings", checks=checks, links=links))


# --------------------------------------------------------------------------- search
@admin_required
def search(request):
    q = request.GET.get("q", "").strip()
    cases, chws = [], []
    if q:
        cases = Case.objects.select_related("assigned_to").filter(
            Q(case_ref__icontains=q) | Q(location_text__icontains=q))[:25]
        chws = User.objects.filter(role=User.Role.CHW).filter(
            Q(username__icontains=q) | Q(full_name__icontains=q) | Q(area__icontains=q))[:25]
    return render(request, "dashboard/search.html", _ctx(request, "", cases=cases, chws=chws, query=q))
