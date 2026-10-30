"""Follow-up reminders and referral tracking for CHWs."""
from django.utils import timezone
from rest_framework import serializers
from rest_framework import status as http
from rest_framework.generics import get_object_or_404
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.permissions import IsStaffMember
from cases.views import visible_cases

from .models import FollowUp, Referral


class FollowUpSerializer(serializers.ModelSerializer):
    case_ref = serializers.CharField(source="case.case_ref", read_only=True)
    case_id = serializers.UUIDField(source="case.id", read_only=True)

    class Meta:
        model = FollowUp
        fields = ["id", "case_id", "case_ref", "due_date", "note", "done", "done_at", "created_at"]
        read_only_fields = ["id", "case_id", "case_ref", "done_at", "created_at"]

    def validate_due_date(self, v):
        if v < timezone.localdate():
            raise serializers.ValidationError("Date cannot be in the past.")
        return v


class ReferralSerializer(serializers.ModelSerializer):
    contact_name = serializers.CharField(source="contact.name", read_only=True, default=None)

    class Meta:
        model = Referral
        fields = ["id", "contact", "contact_name", "facility_name", "outcome", "note",
                  "created_at", "updated_at"]
        read_only_fields = ["id", "contact_name", "created_at", "updated_at"]

    def validate(self, data):
        if self.instance is None and not (data.get("contact") or data.get("facility_name")):
            raise serializers.ValidationError("Choose a facility or type its name.")
        return data


def _case_for(request, case_id, write=False):
    """A CHW may read cases they can see, but only change their own. Others get 404/403."""
    case = get_object_or_404(visible_cases(request.user), pk=case_id)
    if write and not request.user.is_salama_admin and case.assigned_to_id != request.user.id:
        return None
    return case


class CaseFollowUps(APIView):
    permission_classes = [IsStaffMember]

    def get(self, request, case_id):
        case = _case_for(request, case_id)
        return Response(FollowUpSerializer(case.followups.all(), many=True).data)

    def post(self, request, case_id):
        case = _case_for(request, case_id, write=True)
        if case is None:
            return Response({"detail": "Take the case first."}, status=http.HTTP_403_FORBIDDEN)
        s = FollowUpSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        s.save(case=case, created_by=request.user)
        return Response(s.data, status=http.HTTP_201_CREATED)


class FollowUpDetail(APIView):
    permission_classes = [IsStaffMember]

    def patch(self, request, pk):
        f = get_object_or_404(FollowUp.objects.select_related("case"), pk=pk)
        case = _case_for(request, f.case_id, write=True)
        if case is None:
            return Response({"detail": "Not your case."}, status=http.HTTP_403_FORBIDDEN)
        done = request.data.get("done")
        if done is not None:
            f.done = bool(done)
            f.done_at = timezone.now() if f.done else None
            f.save(update_fields=["done", "done_at"])
        return Response(FollowUpSerializer(f).data)


class MyFollowUps(APIView):
    """Open follow-ups on my cases, soonest first (overdue ones come first)."""

    permission_classes = [IsStaffMember]

    def get(self, request):
        qs = FollowUp.objects.filter(done=False, case__assigned_to=request.user).select_related("case")
        return Response(FollowUpSerializer(qs, many=True).data)


class CaseReferrals(APIView):
    permission_classes = [IsStaffMember]

    def get(self, request, case_id):
        case = _case_for(request, case_id)
        return Response(ReferralSerializer(case.referrals.select_related("contact"), many=True).data)

    def post(self, request, case_id):
        case = _case_for(request, case_id, write=True)
        if case is None:
            return Response({"detail": "Take the case first."}, status=http.HTTP_403_FORBIDDEN)
        s = ReferralSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        s.save(case=case, created_by=request.user)
        return Response(s.data, status=http.HTTP_201_CREATED)


class ReferralDetail(APIView):
    permission_classes = [IsStaffMember]

    def patch(self, request, pk):
        r = get_object_or_404(Referral.objects.select_related("case"), pk=pk)
        case = _case_for(request, r.case_id, write=True)
        if case is None:
            return Response({"detail": "Not your case."}, status=http.HTTP_403_FORBIDDEN)
        s = ReferralSerializer(r, data=request.data, partial=True)
        s.is_valid(raise_exception=True)
        s.save()
        return Response(s.data)
