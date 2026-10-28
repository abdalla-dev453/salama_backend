from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import CaseViewSet, HealthView, IntakeView, SmsCallbackView, StatsView

router = DefaultRouter()
router.register("cases", CaseViewSet, basename="case")

urlpatterns = [
    path("health/", HealthView.as_view(), name="health"),
    path("intake/", IntakeView.as_view(), name="intake"),
    path("sms/africastalking/", SmsCallbackView.as_view(), name="sms-callback"),
    path("stats/", StatsView.as_view(), name="stats"),
    path("", include(router.urls)),
]
