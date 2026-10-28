from django.contrib.auth.password_validation import validate_password
from rest_framework import serializers
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer

from cases.phones import normalize_ke_phone

from .models import User


class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = [
            "id", "username", "full_name", "phone", "area",
            "role", "is_active", "last_login", "date_joined",
        ]
        read_only_fields = fields


class SalamaTokenObtainPairSerializer(TokenObtainPairSerializer):
    """Login with CHW ID + password. The ID is case-insensitive."""

    @classmethod
    def get_token(cls, user):
        token = super().get_token(user)
        token["role"] = user.role
        return token

    def validate(self, attrs):
        typed = (attrs.get(self.username_field) or "").strip()
        match = User.objects.filter(username__iexact=typed).first()
        attrs[self.username_field] = match.username if match else typed
        data = super().validate(attrs)  # raises for wrong password / inactive
        data["user"] = UserSerializer(self.user).data
        return data


class ChwSerializer(serializers.ModelSerializer):
    """Admin creates / edits CHW accounts."""

    password = serializers.CharField(write_only=True, required=False, min_length=8)
    open_cases = serializers.IntegerField(read_only=True, required=False)

    class Meta:
        model = User
        fields = [
            "id", "username", "password", "full_name", "phone", "area",
            "is_active", "last_login", "open_cases",
        ]
        read_only_fields = ["last_login", "open_cases"]
        extra_kwargs = {"username": {"validators": []}}  # we check case-insensitively below

    def validate_username(self, value):
        value = value.strip().upper()
        clash = User.objects.filter(username__iexact=value)
        if self.instance:
            clash = clash.exclude(pk=self.instance.pk)
        if clash.exists():
            raise serializers.ValidationError("A user with this ID already exists.")
        return value

    def validate_phone(self, value):
        try:
            return normalize_ke_phone(value)
        except ValueError:
            raise serializers.ValidationError("Enter a valid Kenyan mobile number.")

    def validate_password(self, value):
        validate_password(value)
        return value

    def create(self, validated_data):
        password = validated_data.pop("password", None)
        if not password:
            raise serializers.ValidationError({"password": "This field is required."})
        user = User(role=User.Role.CHW, **validated_data)
        user.set_password(password)
        user.save()
        return user

    def update(self, instance, validated_data):
        password = validated_data.pop("password", None)
        for k, v in validated_data.items():
            setattr(instance, k, v)
        if password:
            instance.set_password(password)
        instance.save()
        return instance
