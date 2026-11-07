import hashlib
import uuid

from django.conf import settings
from django.db import models

from cases.fields import EncryptedTextField


class ChatMessage(models.Model):
    """Secure two-way chat between a survivor (by case ref) and the assigned CHW."""

    class Sender(models.TextChoices):
        SURVIVOR = "survivor", "Survivor"
        CHW = "chw", "CHW"

    case = models.ForeignKey("cases.Case", on_delete=models.CASCADE, related_name="chat")
    sender = models.CharField(max_length=8, choices=Sender.choices)
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    text = EncryptedTextField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["id"]
        indexes = [models.Index(fields=["case", "id"])]


class SurvivorDevice(models.Model):
    """FCM token of the survivor's phone. Used only for neutral 'Update available' pushes."""

    case_ref = models.CharField(max_length=32, db_index=True)
    token = models.CharField(max_length=400, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)


class Evidence(models.Model):
    """A photo. Stored encrypted (Fernet) in the database, EXIF/GPS removed."""

    case = models.ForeignKey("cases.Case", on_delete=models.CASCADE, related_name="evidence")
    data = models.BinaryField()
    content_type = models.CharField(max_length=40)
    size = models.PositiveIntegerField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["id"]


class CheckIn(models.Model):
    """'Alert my contacts if I do not check in within X minutes.'"""

    device_id = models.UUIDField(unique=True)
    case_ref = models.CharField(max_length=32, blank=True)
    due_at = models.DateTimeField()
    contacts = EncryptedTextField(blank=True, default="")  # comma separated +254...
    note = EncryptedTextField(blank=True, default="")
    active = models.BooleanField(default=True)
    alerted = models.BooleanField(default=False)
    updated_at = models.DateTimeField(auto_now=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def contact_list(self):
        return [c for c in (self.contacts or "").split(",") if c]


class Escalation(models.Model):
    """Record that an unanswered SOS was escalated (so it is only escalated once per level)."""

    case = models.ForeignKey("cases.Case", on_delete=models.CASCADE, related_name="escalations")
    level = models.PositiveSmallIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = [("case", "level")]


class VisitNote(models.Model):
    class Risk(models.TextChoices):
        LOW = "low", "Low"
        MEDIUM = "medium", "Medium"
        HIGH = "high", "High"

    case = models.ForeignKey("cases.Case", on_delete=models.CASCADE, related_name="visits")
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+"
    )
    visit_date = models.DateField()
    risk_level = models.CharField(max_length=6, choices=Risk.choices)
    safe_at_home = models.BooleanField(default=True)
    injuries = models.BooleanField(default=False)
    needs = models.JSONField(default=list, blank=True)
    referral_made = models.BooleanField(default=False)
    summary = EncryptedTextField(blank=True, default="")
    next_step = EncryptedTextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-visit_date", "-id"]


class Feedback(models.Model):
    """Anonymous satisfaction survey. No phone, no description."""

    case_ref = models.CharField(max_length=32, blank=True)
    rating = models.PositiveSmallIntegerField()
    helped = models.BooleanField(default=False)
    comment = models.CharField(max_length=300, blank=True)
    lang = models.CharField(max_length=2, default="en")
    created_at = models.DateTimeField(auto_now_add=True)


class Article(models.Model):
    title_en = models.CharField(max_length=160)
    title_sw = models.CharField(max_length=160, blank=True)
    body_en = models.TextField()
    body_sw = models.TextField(blank=True)
    # [{"q_en","q_sw","options_en":[..],"options_sw":[..],"answer":0}]
    quiz = models.JSONField(default=list, blank=True)
    is_active = models.BooleanField(default=True)
    sort_order = models.PositiveIntegerField(default=100)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["sort_order", "id"]

    def __str__(self):
        return self.title_en


class Subscriber(models.Model):
    """Opted-in phone for SMS awareness messages. Phone stored encrypted + hashed for uniqueness."""

    phone = EncryptedTextField()
    phone_hash = models.CharField(max_length=64, unique=True)
    area = models.CharField(max_length=80, blank=True)
    lang = models.CharField(max_length=2, default="sw")
    created_at = models.DateTimeField(auto_now_add=True)

    @staticmethod
    def hash_phone(p):
        return hashlib.sha256(p.encode()).hexdigest()


class Broadcast(models.Model):
    sent_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+"
    )
    message = models.CharField(max_length=300)
    area = models.CharField(max_length=80, blank=True)
    recipients = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]