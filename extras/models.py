from django.conf import settings
from django.db import models

from cases.fields import EncryptedTextField


class HelpContact(models.Model):
    """
    A place a survivor can go to: clinic, police gender desk, safe house...
    Managed by admins in Django admin; the app downloads the list and keeps a
    copy on the phone so it works with no signal.

    Only real, verified contacts belong here. Never invent numbers.
    """

    class Category(models.TextChoices):
        HELPLINE = "helpline", "Helpline"
        CLINIC = "clinic", "Clinic / hospital"
        POLICE = "police", "Police gender desk"
        SAFEHOUSE = "safehouse", "Safe house / shelter"
        LEGAL = "legal", "Legal aid"
        COUNSELING = "counseling", "Counseling"

    name = models.CharField(max_length=160)
    category = models.CharField(max_length=12, choices=Category.choices)
    phone = models.CharField(max_length=20, blank=True)
    phone_alt = models.CharField(max_length=20, blank=True)
    area = models.CharField(
        max_length=80, blank=True, help_text="Ukunda, Msambweni, Lunga Lunga, Kinango, ..."
    )
    address = models.CharField(max_length=200, blank=True)
    hours = models.CharField(max_length=80, blank=True, help_text="e.g. 24 hours, Mon-Fri 8-5")
    notes_en = models.CharField(max_length=240, blank=True)
    notes_sw = models.CharField(max_length=240, blank=True)
    lat = models.FloatField(null=True, blank=True)
    lon = models.FloatField(null=True, blank=True)
    is_active = models.BooleanField(default=True)
    sort_order = models.PositiveIntegerField(default=100)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["sort_order", "category", "name"]

    def __str__(self):
        return f"{self.name} ({self.category})"


class DeviceToken(models.Model):
    """FCM token of a CHW/admin phone, used to push 'new urgent case' alerts."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="device_tokens"
    )
    token = models.CharField(max_length=400, unique=True)
    platform = models.CharField(max_length=10, default="android")
    created_at = models.DateTimeField(auto_now_add=True)
    last_seen = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.user_id}:{self.token[:12]}..."


class FollowUp(models.Model):
    """A planned follow-up visit/call on a case, with a reminder date."""

    case = models.ForeignKey("cases.Case", on_delete=models.CASCADE, related_name="followups")
    due_date = models.DateField()
    note = EncryptedTextField(blank=True, default="")
    done = models.BooleanField(default=False)
    done_at = models.DateTimeField(null=True, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["done", "due_date", "id"]


class Referral(models.Model):
    """Where a survivor was sent (clinic, police desk...) and what happened."""

    class Outcome(models.TextChoices):
        PENDING = "pending", "Pending"
        ATTENDED = "attended", "Attended"
        NOT_ATTENDED = "not_attended", "Did not attend"
        UNKNOWN = "unknown", "Unknown"

    case = models.ForeignKey("cases.Case", on_delete=models.CASCADE, related_name="referrals")
    contact = models.ForeignKey(HelpContact, null=True, blank=True, on_delete=models.SET_NULL)
    facility_name = models.CharField(max_length=160, blank=True)  # if not in the directory
    outcome = models.CharField(max_length=12, choices=Outcome.choices, default=Outcome.PENDING)
    note = EncryptedTextField(blank=True, default="")
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at", "id"]
