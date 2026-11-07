from django.urls import path

from . import web_views as v


app_name = "dash6"

urlpatterns = [
    path("live.json", v.live, name="live"),
    path("performance/", v.performance, name="performance"),
    path("trends/", v.trends, name="trends"),
    path("impact/", v.impact, name="impact"),
    path("outreach/", v.outreach, name="outreach"),
    path("audit/", v.audit, name="audit"),
    path("export/cases.csv", v.export_cases, name="export"),
    path("report/monthly/",v.monthly_report, name="monthly"),
]