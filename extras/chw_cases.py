"""A CHW logs a case for a survivor she is with (the "+ New Case" button)."""
import uuid

from django.utils import timezone
from rest_framework import status as http
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.permissions import IsStaffMember
from cases.models import Case, CaseSource, CaseType
from cases.serializers import IntakeSerializer
from cases.services import workflow
from cases.services.intake import intake_case


def new_case_ref(sos=False) -> str:
    prefix = "SOS" if sos else f"KWALE-{timezone.localdate():%d%m}"
    while True:
        ref = f"{prefix}-{uuid.uuid4().hex[:6].upper()}"
        if not Case.objects.filter(case_ref=ref).exists():
            return ref


class CreateCaseView(APIView):
    """POST /api/new-case/  (CHW or admin). The new case is assigned to the creator."""

    permission_classes = [IsStaffMember]

    def post(self, request):
        data = {k: v for k, v in request.data.items()}
        data["case_ref"] = new_case_ref(sos=data.get("type") == CaseType.SOS)
        s = IntakeSerializer(data=data)
        s.is_valid(raise_exception=True)
        case, _ = intake_case(**s.validated_data, source=CaseSource.APP)
        workflow.assign_case(case, request.user, request.user)  # writes the audit entry too
        return Response({"id": str(case.id), "case_ref": case.case_ref}, status=http.HTTP_201_CREATED)
