import io
import re

from django.http import HttpResponse
from rest_framework import status as http
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from accounts.permissions import IsSalamaAdmin, IsStaffMember
from cases.models import CASE_REF_REGEX, Case, CaseStatus

from . import reports
from .models import DeviceToken, HelpContact


# ---------------------------------------------------------------------------
# Public: help directory (the app caches it for offline use)
# ---------------------------------------------------------------------------
class HelpDirectoryView(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "public_read"

    def get(self, request):
        qs = HelpContact.objects.filter(is_active=True)
        area = request.query_params.get("area")
        if area:
            qs = qs.filter(area__iexact=area)
        contacts = list(qs)
        version = max((c.updated_at for c in contacts), default=None)
        return Response(
            {
                "version": version.isoformat() if version else None,
                "contacts": [
                    {
                        "id": c.id, "name": c.name, "category": c.category,
                        "phone": c.phone, "phone_alt": c.phone_alt, "area": c.area,
                        "address": c.address, "hours": c.hours,
                        "notes_en": c.notes_en, "notes_sw": c.notes_sw,
                        "lat": c.lat, "lon": c.lon,
                    }
                    for c in contacts
                ],
            }
        )


# ---------------------------------------------------------------------------
# Public: "what is happening with my case?" - status only, nothing personal
# ---------------------------------------------------------------------------
# What the survivor sees (never the CHW's name, notes or description).
SURVIVOR_STATUS = {
    CaseStatus.NEW: "received",
    CaseStatus.SOS: "received",
    CaseStatus.RESPONDED: "in_progress",
    CaseStatus.REFERRED: "referred",
    CaseStatus.FOLLOWUP: "in_progress",
    CaseStatus.CLOSED: "closed",
}


class CaseStatusView(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "status_check"  # tight: stops anyone guessing case IDs

    def get(self, request, case_ref):
        ref = case_ref.strip().upper()
        case = Case.objects.filter(case_ref=ref).first() if re.match(CASE_REF_REGEX, ref) else None
        if not case:
            # Same answer for "bad format" and "does not exist".
            return Response({"found": False}, status=http.HTTP_404_NOT_FOUND)
        return Response(
            {
                "found": True,
                "case_ref": case.case_ref,
                "status": SURVIVOR_STATUS.get(case.status, "received"),
                "updated_at": case.updated_at.isoformat(),
            }
        )


# ---------------------------------------------------------------------------
# CHW push tokens
# ---------------------------------------------------------------------------
class DeviceTokenView(APIView):
    permission_classes = [IsStaffMember]

    def post(self, request):
        token = (request.data.get("token") or "").strip()
        if not (20 <= len(token) <= 400):
            return Response({"detail": "Invalid token."}, status=http.HTTP_400_BAD_REQUEST)
        platform = (request.data.get("platform") or "android")[:10]
        DeviceToken.objects.update_or_create(
            token=token, defaults={"user": request.user, "platform": platform}
        )
        return Response({"ok": True})

    def delete(self, request):
        """Call on logout so a lost/shared phone stops receiving alerts."""
        token = (request.data.get("token") or "").strip()
        DeviceToken.objects.filter(user=request.user, token=token).delete()
        return Response(status=http.HTTP_204_NO_CONTENT)


# ---------------------------------------------------------------------------
# Admin reports
# ---------------------------------------------------------------------------
class AnonymousStatsView(APIView):
    """?from=YYYY-MM-DD&to=YYYY-MM-DD  -> counts by month, area and type. Small cells hidden."""

    permission_classes = [IsSalamaAdmin]

    def get(self, request):
        return Response(reports.anonymous_stats(reports.report_queryset(request.query_params)))


class ExportCsvView(APIView):
    permission_classes = [IsSalamaAdmin]

    def get(self, request):
        buf = io.StringIO()
        reports.write_csv(reports.report_queryset(request.query_params), buf)
        resp = HttpResponse(buf.getvalue(), content_type="text/csv; charset=utf-8")
        resp["Content-Disposition"] = 'attachment; filename="salama_anonymous_stats.csv"'
        return resp


class ResponseTimesView(APIView):
    permission_classes = [IsSalamaAdmin]

    def get(self, request):
        return Response(reports.response_times(reports.report_queryset(request.query_params)))
