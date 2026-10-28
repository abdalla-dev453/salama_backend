from rest_framework import serializers

from accounts.models import User

from .models import CASE_REF_REGEX, Case, CaseStatus, CaseType, CaseUpdate
from .phones import normalize_ke_phone


class IntakeSerializer(serializers.Serializer):
    """What the survivor's phone sends. No account, so validate strictly."""

    case_ref = serializers.RegexField(CASE_REF_REGEX, max_length=32)
    type = serializers.ChoiceField(choices=CaseType.choices)
    description = serializers.CharField(max_length=4000, required=False, allow_blank=True, default="")
    location_text = serializers.CharField(max_length=200, required=False, allow_blank=True, default="")
    lat = serializers.FloatField(min_value=-90, max_value=90, required=False, allow_null=True, default=None)
    lon = serializers.FloatField(min_value=-180, max_value=180, required=False, allow_null=True, default=None)
    contact_phone = serializers.CharField(max_length=20, required=False, allow_blank=True, default="")
    safe_to_call = serializers.BooleanField(required=False, default=False)
    reported_at = serializers.DateTimeField(required=False, allow_null=True, default=None)

    def validate_contact_phone(self, value):
        try:
            return normalize_ke_phone(value)
        except ValueError:
            raise serializers.ValidationError("Enter a valid Kenyan mobile number.")

    def validate(self, attrs):
        if (attrs.get("lat") is None) != (attrs.get("lon") is None):
            raise serializers.ValidationError("lat and lon must be sent together.")
        if attrs["type"] != CaseType.SOS and not attrs.get("description", "").strip():
            raise serializers.ValidationError({"description": "This field is required."})
        return attrs


class CaseUpdateSerializer(serializers.ModelSerializer):
    author_name = serializers.SerializerMethodField()

    class Meta:
        model = CaseUpdate
        fields = ["id", "kind", "from_status", "to_status", "note", "author_name", "created_at"]

    def get_author_name(self, obj):
        return obj.author.display_name if obj.author else ""


class CaseSerializer(serializers.ModelSerializer):
    priority = serializers.CharField(read_only=True)
    is_urgent = serializers.BooleanField(read_only=True)
    assigned_to_name = serializers.SerializerMethodField()

    class Meta:
        model = Case
        fields = [
            "id", "case_ref", "type", "status", "priority", "is_urgent", "source",
            "description", "location_text", "lat", "lon",
            "contact_phone", "safe_to_call",
            "reported_at", "received_at", "updated_at",
            "assigned_to", "assigned_to_name",
        ]
        read_only_fields = fields

    def get_assigned_to_name(self, obj):
        return obj.assigned_to.display_name if obj.assigned_to else ""


class CaseDetailSerializer(CaseSerializer):
    updates = CaseUpdateSerializer(many=True, read_only=True)

    class Meta(CaseSerializer.Meta):
        fields = CaseSerializer.Meta.fields + ["updates"]
        read_only_fields = fields


class StatusChangeSerializer(serializers.Serializer):
    status = serializers.ChoiceField(choices=CaseStatus.choices)
    note = serializers.CharField(max_length=1000, required=False, allow_blank=True, default="")


class NoteSerializer(serializers.Serializer):
    note = serializers.CharField(max_length=1000)


class AssignSerializer(serializers.Serializer):
    chw = serializers.PrimaryKeyRelatedField(
        queryset=User.objects.filter(role=User.Role.CHW, is_active=True),
        allow_null=True,
    )
