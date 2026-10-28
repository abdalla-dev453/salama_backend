from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import ChwViewSet, LoginView, MeView, RefreshView

router = DefaultRouter()
router.register("chws", ChwViewSet, basename="chw")

urlpatterns = [
    path("auth/login/", LoginView.as_view(), name="login"),
    path("auth/refresh/", RefreshView.as_view(), name="token-refresh"),
    path("auth/me/", MeView.as_view(), name="me"),
    path("", include(router.urls)),
]
