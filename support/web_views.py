"""v6 admin pages: live feed, CHW performance, hotspot trends, impact, outreach, audit, exports."""
import csv
import statistics
from collections import Counter, defaultdict
from datetime import timedelta

from django.contrib import messages
from django.http import HttpResponse, JsonResponse
from django.shortcuts import redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from accounts.models import User
from cases.models import WAITING_STATUSES, Case, CaseType, CaseUpdate
from cases.services.notify import send_sms
from cases.web_views import _ctx, admin_required
from extras.areas import area_for

from .models import Broadcast, Feedback, Subscriber

MIN_CELL = 5


def _cell(n):
    return "<5" if 0 < n < MIN_CELL else n


@admin_required
def live(request):
    """Polled by every dashboard page every 10 s: counts + newest urgent SOS id."""
    urgent = Case.objects.filter(type=CaseType.SOS, status__in=WAITING_STATUSES)
    newest = urgent.order_by("-received_at").values_list("case_ref", flat=True).first()
    return JsonResponse({
        "urgent": urgent.count(),
        "newest_sos": newest,
        "open": Case.objects.exclude(status="closed").count(),
        "unassigned": Case.objects.filter(assigned_to__isnull=True, status="new").count(),
    })


def _minutes(a, b):
    return max((b - a).total_seconds() / 60, 0)


@admin_required
def performance(request):
    since = timezone.now() - timedelta(days=int(request.GET.get("days", 30)) if request.GET.get("days") in ("7", "30", "90") else 30)
    rows = []
    for u in User.objects.filter(role=User.Role.CHW, is_active=True).order_by("username"):
        cases = Case.objects.filter(assigned_to=u, received_at__gte=since)
        n = cases.count()
        closed = cases.filter(status="closed").count()
        # first response = first status/assign update by this CHW
        times = []
        for c in cases.prefetch_related("updates")[:300]:
            first = next((x for x in c.updates.all() if x.author_id == u.id), None)
            if first:
                times.append(_minutes(c.received_at, first.created_at))
        rows.append({
            "name": u.display_name, "area": u.area, "cases": n, "closed": closed,
            "rate": round(closed * 100 / n) if n else None,
            "median": round(statistics.median(times)) if times else None,
            "open": cases.exclude(status="closed").count(),
        })
    return render(request, "dashboard/performance.html", _ctx(request, "performance", rows=rows, days=since))


@admin_required
def trends(request):
    now = timezone.now()
    this_w = Case.objects.filter(received_at__gte=now - timedelta(days=7))
    last_w = Case.objects.filter(received_at__gte=now - timedelta(days=14), received_at__lt=now - timedelta(days=7))
    a, b = Counter(), Counter()
    for t in this_w.values_list("location_text", flat=True):
        a[area_for(t)] += 1
    for t in last_w.values_list("location_text", flat=True):
        b[area_for(t)] += 1
    rows = []
    for area in sorted(set(a) | set(b), key=lambda k: -a[k]):
        small = a[area] < MIN_CELL or b[area] < MIN_CELL
        rows.append({"area": area, "this": _cell(a[area]), "last": _cell(b[area]),
                     "change": None if small else a[area] - b[area]})
    return render(request, "dashboard/trends.html", _ctx(request, "trends", rows=rows))


@admin_required
def impact(request):
    qs = Feedback.objects.all()
    n = qs.count()
    dist = Counter(qs.values_list("rating", flat=True))
    helped = qs.filter(helped=True).count()
    ctx = {"n": n, "enough": n >= MIN_CELL}
    if n >= MIN_CELL:
        ctx.update(avg=round(sum(k * v for k, v in dist.items()) / n, 1),
                   helped_pct=round(helped * 100 / n),
                   dist=[{"star": s, "count": _cell(dist.get(s, 0)), "pct": round(dist.get(s, 0) * 100 / n)} for s in (5, 4, 3, 2, 1)],
                   comments=list(qs.exclude(comment="").values_list("comment", flat=True)[:15]))
    return render(request, "dashboard/impact.html", _ctx(request, "impact", **ctx))


@admin_required
def outreach(request):
    if request.method == "POST":
        msg = request.POST.get("message", "").strip()[:300]
        area = request.POST.get("area", "").strip()
        if not msg:
            messages.error(request, "Write a message first.")
        else:
            subs = Subscriber.objects.all()
            if area:
                subs = subs.filter(area__iexact=area)
            phones = [s.phone for s in subs]
            ok = True
            for i in range(0, len(phones), 100):
                ok = send_sms(phones[i:i + 100], msg + " Reply STOP to opt out.") and ok
            Broadcast.objects.create(sent_by=request.user, message=msg, area=area, recipients=len(phones))
            (messages.success if ok and phones else messages.error)(
                request, f"Sent to {len(phones)} subscriber(s)." if ok and phones else
                "Nothing sent: no subscribers, or Africa's Talking is not set up.")
        return redirect("dash6:outreach")
    return render(request, "dashboard/outreach.html", _ctx(
        request, "outreach", subs=Subscriber.objects.count(),
        history=Broadcast.objects.select_related("sent_by")[:10]))


@admin_required
def audit(request):
    ups = CaseUpdate.objects.select_related("case", "author").order_by("-created_at")[:200]
    return render(request, "dashboard/audit.html", _ctx(request, "audit", ups=ups))


@admin_required
def export_cases(request):
    """CSV for donors/county. NO descriptions, phones or coordinates; small areas are suppressed."""
    month = request.GET.get("month", "")
    qs = Case.objects.all()
    if len(month) == 7:
        try:
            y, m = int(month[:4]), int(month[5:])
            qs = qs.filter(received_at__year=y, received_at__month=m)
        except ValueError:
            pass
    by = Counter()
    for t, s, loc in qs.values_list("type", "status", "location_text"):
        by[(area_for(loc), t, s)] += 1
    resp = HttpResponse(content_type="text/csv")
    resp["Content-Disposition"] = f'attachment; filename="salama-cases-{month or "all"}.csv"'
    w = csv.writer(resp)
    w.writerow(["area", "type", "status", "count"])
    for (area, t, s), n in sorted(by.items()):
        w.writerow([area, t, s, _cell(n)])
    return resp


@admin_required
def monthly_report(request):
    """Printable page (Ctrl+P -> Save as PDF)."""
    now = timezone.localdate()
    month = request.GET.get("month") or now.strftime("%Y-%m")
    try:
        y, m = int(month[:4]), int(month[5:7])
    except ValueError:
        y, m = now.year, now.month
    qs = Case.objects.filter(received_at__year=y, received_at__month=m)
    by_type = Counter(qs.values_list("type", flat=True))
    by_status = Counter(qs.values_list("status", flat=True))
    by_area = Counter(area_for(t) for t in qs.values_list("location_text", flat=True))
    fb = Feedback.objects.filter(created_at__year=y, created_at__month=m)
    return render(request, "dashboard/monthly.html", _ctx(
        request, "analytics", month=f"{y}-{m:02d}", total=qs.count(),
        types=[(label, _cell(by_type.get(v, 0))) for v, label in CaseType.choices],
        statuses=[(k, _cell(v)) for k, v in sorted(by_status.items())],
        areas=[(k, _cell(v)) for k, v in sorted(by_area.items(), key=lambda kv: -kv[1])],
        fb_n=fb.count()))
