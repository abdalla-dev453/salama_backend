import csv
import statistics
from collections import Counter, defaultdict

from cases.models import Case, CaseUpdate

from .areas import area_for

# Counts below this are shown as "<5" so one person cannot be identified in a small area.
MIN_CELL = 5


def _cell(n: int):
    return n if n >= MIN_CELL else f"<{MIN_CELL}"


def anonymous_rows(qs):
    """[(month 'YYYY-MM', area, type, count)] without any personal data."""
    counts = Counter()
    for received_at, location_text, type_ in qs.values_list("received_at", "location_text", "type"):
        counts[(received_at.strftime("%Y-%m"), area_for(location_text), type_)] += 1
    return sorted((m, a, t, n) for (m, a, t), n in counts.items())


def anonymous_stats(qs):
    rows = anonymous_rows(qs)
    return {
        "min_cell": MIN_CELL,
        "rows": [{"month": m, "area": a, "type": t, "count": _cell(n)} for m, a, t, n in rows],
        "total": qs.count(),
    }


def write_csv(qs, out):
    w = csv.writer(out)
    w.writerow(["month", "area", "type", "count"])
    for m, a, t, n in anonymous_rows(qs):
        w.writerow([m, a, t, _cell(n)])


def _minutes(delta):
    return round(delta.total_seconds() / 60, 1)


def response_times(qs):
    """
    Minutes from 'received' to the first action by a staff member (assignment,
    status change or note). Overall, for SOS only, and per CHW.
    """
    first = {}
    updates = (
        CaseUpdate.objects.filter(case__in=qs, author__isnull=False)
        .exclude(kind=CaseUpdate.Kind.CREATED)
        .select_related("author", "case")
        .order_by("created_at")
    )
    for u in updates:
        first.setdefault(u.case_id, u)

    all_m, sos_m, per_chw = [], [], defaultdict(list)
    for u in first.values():
        m = _minutes(u.created_at - u.case.received_at)
        all_m.append(m)
        if u.case.type == "sos":
            sos_m.append(m)
        per_chw[u.author.username].append(m)

    def summary(values):
        if not values:
            return {"cases": 0, "median_min": None, "average_min": None}
        return {
            "cases": len(values),
            "median_min": round(statistics.median(values), 1),
            "average_min": round(sum(values) / len(values), 1),
        }

    return {
        "overall": summary(all_m),
        "sos": summary(sos_m),
        "per_chw": {k: summary(v) for k, v in sorted(per_chw.items())},
        "never_answered": qs.exclude(pk__in=list(first.keys())).count(),
    }


def report_queryset(params):
    qs = Case.objects.all()
    if params.get("from"):
        qs = qs.filter(received_at__date__gte=params["from"])
    if params.get("to"):
        qs = qs.filter(received_at__date__lte=params["to"])
    return qs
