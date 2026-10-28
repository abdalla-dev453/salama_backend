from django.db.models import Count, Q
from rest_framework import status, viewsets
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView

from cases.models import CaseStatus

from .models import User
from .permissions import IsSalamaAdmin, IsStaffMember
from .serializers import ChwSerializer, SalamaTokenObtainPairSerializer, UserSerializer


class LoginView(TokenObtainPairView):
    serializer_class = SalamaTokenObtainPairSerializer
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "login"


class RefreshView(TokenRefreshView):
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "login"


class MeView(APIView):
    permission_classes = [IsStaffMember]

    def get(self, request):
        return Response(UserSerializer(request.user).data)


class ChwViewSet(viewsets.ModelViewSet):
    """Admin only: manage CHW accounts. DELETE deactivates (keeps the audit trail)."""

    permission_classes = [IsSalamaAdmin]
    serializer_class = ChwSerializer
    search_fields = ["username", "full_name", "area", "phone"]
    filterset_fields = ["is_active", "area"]

    def get_queryset(self):
        open_statuses = [CaseStatus.NEW, CaseStatus.SOS, CaseStatus.RESPONDED, CaseStatus.REFERRED]
        return (
            User.objects.filter(role=User.Role.CHW)
            .annotate(open_cases=Count("cases", filter=Q(cases__status__in=open_statuses)))
            .order_by("username")
        )

    def destroy(self, request, *args, **kwargs):
        user = self.get_object()
        user.is_active = False
        user.save(update_fields=["is_active"])
        return Response(status=status.HTTP_204_NO_CONTENT)
