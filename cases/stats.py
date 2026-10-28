from datetime import timedelta

from django.db.models import Count, Q
from django.db.models.functions import TruncDate
from django.utils import timezone

from .models import CaseStatus, CaseType


def stats_for(qs, days: int = 30) -> dict:
    """KPI numbers for a Case queryset (all cases for admins, visible ones for a CHW)."""
    agg = qs.aggregate(
        total=Count("id"),
        pending=Count("id", filter=Q(status__in=[CaseStatus.NEW, CaseStatus.SOS])),
        active=Count("id", filter=Q(status__in=[CaseStatus.RESPONDED, CaseStatus.REFERRED])),
        urgent=Count("id", filter=Q(type=CaseType.SOS,
                                    status__in=[CaseStatus.NEW, CaseStatus.SOS])),
        referred=Count("id", filter=Q(status=CaseStatus.REFERRED)),
        closed=Count("id", filter=Q(status=CaseStatus.CLOSED)),
    )
    by_status = {r["status"]: r["n"] for r in qs.values("status").annotate(n=Count("id")).order_by()}
    by_type = {r["type"]: r["n"] for r in qs.values("type").annotate(n=Count("id")).order_by()}

    today = timezone.localdate()
    start = today - timedelta(days=days - 1)
    per_day = {
        r["d"]: r["n"]
        for r in qs.filter(received_at__date__gte=start)
        .annotate(d=TruncDate("received_at"))
        .values("d").annotate(n=Count("id")).order_by()
    }
    trend = [
        {"date": (start + timedelta(days=i)).isoformat(),
         "count": per_day.get(start + timedelta(days=i), 0)}
        for i in range(days)
    ]

    now = timezone.now()
    last7 = qs.filter(received_at__gte=now - timedelta(days=7)).count()
    prev7 = qs.filter(received_at__gte=now - timedelta(days=14),
                      received_at__lt=now - timedelta(days=7)).count()

    return {**agg, "by_status": by_status, "by_type": by_type, "trend": trend,
            "last_7_days": last7, "previous_7_days": prev7}
