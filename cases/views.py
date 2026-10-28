import hmac
import logging

import django_filters
from django.conf import settings
from django.db import connection, transaction
from django.db.models import Case as DbCase
from django.db.models import IntegerField, Q, Value, When
from rest_framework import status as http
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from accounts.permissions import IsSalamaAdmin, IsStaffMember

from .models import (
    OPEN_STATUSES, WAITING_STATUSES, Case, CaseSource, CaseStatus, CaseType, SmsInbound,
)
from .parsing import parse_sms
from .phones import normalize_ke_phone
from .serializers import (
    AssignSerializer, CaseDetailSerializer, CaseSerializer, IntakeSerializer,
    NoteSerializer, StatusChangeSerializer,
)
from .services import workflow
from .services.intake import intake_case
from .stats import stats_for

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Survivor intake (no login)
# ---------------------------------------------------------------------------
class IntakeView(APIView):
    """
    POST /api/intake/  - called by the survivor app (and its background sync).
    Anonymous on purpose: a survivor must never need an account. Protected by
    strict validation, throttling and the optional X-Salama-Key header.
    The response never contains case data (anyone can call this endpoint).
    """

    authentication_classes = []
    permission_classes = [AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "intake"

    def post(self, request):
        expected = settings.SURVIVOR_API_KEY
        if expected and not hmac.compare_digest(
            request.headers.get("X-Salama-Key", "").encode(), expected.encode()
        ):
            return Response({"detail": "Invalid or missing key."}, status=http.HTTP_401_UNAUTHORIZED)

        ser = IntakeSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        case, created = intake_case(**ser.validated_data, source=CaseSource.APP)
        return Response(
            {"case_ref": case.case_ref, "status": "received", "created": created},
            status=http.HTTP_201_CREATED if created else http.HTTP_200_OK,
        )


# ---------------------------------------------------------------------------
# Africa's Talking incoming SMS webhook
# ---------------------------------------------------------------------------
class SmsCallbackView(APIView):
    """
    POST /api/sms/africastalking/?token=<AT_WEBHOOK_TOKEN>
    Africa's Talking posts form fields: from, to, text, date, id, linkId.
    Always answers 200 for authenticated calls so AT does not retry forever;
    unparseable messages are kept in the inbox for a human to read.
    """

    authentication_classes = []
    permission_classes = [AllowAny]
    parser_classes = [FormParser, MultiPartParser, JSONParser]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "sms_webhook"

    def post(self, request):
        expected = settings.AT_WEBHOOK_TOKEN
        given = request.query_params.get("token") or request.headers.get("X-Webhook-Token", "")
        # Fail closed: no configured token = webhook disabled.
        if not expected or not hmac.compare_digest(given.encode(), expected.encode()):
            return Response({"detail": "Forbidden."}, status=http.HTTP_403_FORBIDDEN)

        sender = (request.data.get("from") or "").strip()
        text = (request.data.get("text") or "").strip()
        provider_id = (request.data.get("id") or "").strip()[:64] or None

        with transaction.atomic():
            if provider_id and SmsInbound.objects.filter(provider_id=provider_id).exists():
                return Response({"ok": True, "duplicate": True})
            sms = SmsInbound.objects.create(provider_id=provider_id, sender=sender, text=text)

            data = parse_sms(text)
            if not data:
                sms.error = "unrecognised format"
                sms.save(update_fields=["error"])
                return Response({"ok": True, "parsed": False})

            if not data["contact_phone"]:
                try:
                    data["contact_phone"] = normalize_ke_phone(sender)
                except ValueError:
                    pass  # keep empty; sender is still stored in the inbox

            case, _ = intake_case(**data, source=CaseSource.SMS)
            sms.parsed = True
            sms.case = case
            sms.save(update_fields=["parsed", "case"])
        return Response({"ok": True, "parsed": True, "case_ref": case.case_ref})


# ---------------------------------------------------------------------------
# CHW / admin API
# ---------------------------------------------------------------------------
class CaseFilter(django_filters.FilterSet):
    scope = django_filters.CharFilter(method="filter_scope")  # mine | unassigned | open | urgent

    class Meta:
        model = Case
        fields = {"status": ["exact"], "type": ["exact"]}

    def filter_scope(self, qs, name, value):
        user = self.request.user
        if value == "mine":
            return qs.filter(assigned_to=user)
        if value == "unassigned":
            return qs.filter(assigned_to__isnull=True)
        if value == "open":
            return qs.filter(status__in=OPEN_STATUSES)
        if value == "urgent":
            return qs.filter(type=CaseType.SOS, status__in=WAITING_STATUSES)
        return qs


def visible_cases(user):
    """Admins see everything. A CHW sees their own cases + unassigned ones (so no SOS is missed)."""
    qs = Case.objects.select_related("assigned_to")
    if user.is_salama_admin:
        return qs
    return qs.filter(Q(assigned_to=user) | Q(assigned_to__isnull=True))


class CaseViewSet(viewsets.ReadOnlyModelViewSet):
    permission_classes = [IsStaffMember]
    filterset_class = CaseFilter
    search_fields = ["case_ref", "location_text"]

    def get_serializer_class(self):
        return CaseDetailSerializer if self.action == "retrieve" else CaseSerializer

    def get_queryset(self):
        qs = visible_cases(self.request.user)
        if self.action == "retrieve":
            qs = qs.prefetch_related("updates__author")
        # Unanswered SOS first, then newest first.
        return qs.annotate(
            urgency=DbCase(
                When(type=CaseType.SOS, status__in=WAITING_STATUSES, then=Value(0)),
                default=Value(1), output_field=IntegerField(),
            )
        ).order_by("urgency", "-received_at")

    def _respond(self, case, code=http.HTTP_200_OK):
        case = self.get_queryset().prefetch_related("updates__author").get(pk=case.pk)
        return Response(CaseDetailSerializer(case).data, status=code)

    @action(detail=True, methods=["post"])
    def claim(self, request, pk=None):
        case = workflow.claim_case(self.get_object(), request.user)
        return self._respond(case)

    @action(detail=True, methods=["post"], url_path="status")
    def change_status(self, request, pk=None):
        ser = StatusChangeSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        case = workflow.change_status(
            self.get_object(), request.user, ser.validated_data["status"], ser.validated_data["note"]
        )
        return self._respond(case)

    @action(detail=True, methods=["post"])
    def note(self, request, pk=None):
        ser = NoteSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        case = workflow.add_note(self.get_object(), request.user, ser.validated_data["note"])
        return self._respond(case)

    @action(detail=True, methods=["post"], permission_classes=[IsSalamaAdmin])
    def assign(self, request, pk=None):
        ser = AssignSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        case = workflow.assign_case(self.get_object(), ser.validated_data["chw"], request.user)
        return self._respond(case)


class StatsView(APIView):
    permission_classes = [IsStaffMember]

    def get(self, request):
        return Response(stats_for(visible_cases(request.user)))


class HealthView(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]

    def get(self, request):
        with connection.cursor() as cur:
            cur.execute("SELECT 1")
        return Response({"status": "ok"})
