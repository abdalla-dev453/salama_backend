import uuid

from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator, RegexValidator
from django.db import models

from .fields import EncryptedTextField

# Same IDs the phone generates: KWALE-<ddMM>-XXXXXX for reports, SOS-XXXXXX for SOS.
CASE_REF_REGEX = r"^(?:KWALE-\d{4}|SOS)-[A-Z0-9]{6}$"


class CaseType(models.TextChoices):
    VIOLENCE = "violence", "Violence / GBV"
    CARE = "care", "Abortion care / post-care"
    COUNSELING = "counseling", "Counseling & referral"
    SOS = "sos", "SOS emergency"


class CaseStatus(models.TextChoices):
    NEW = "new", "New - Pending"
    SOS = "sos", "SOS - Urgent"
    RESPONDED = "responded", "Responded - Visiting"
    REFERRED = "referred", "Referred to facility"
    FOLLOWUP = "followup", "Follow-up done"
    CLOSED = "closed", "Closed"


# Statuses where somebody still has to act.
OPEN_STATUSES = [CaseStatus.NEW, CaseStatus.SOS, CaseStatus.RESPONDED, CaseStatus.REFERRED]
# Statuses where nobody has responded yet.
WAITING_STATUSES = [CaseStatus.NEW, CaseStatus.SOS]


class CaseSource(models.TextChoices):
    APP = "app", "Mobile app"
    SMS = "sms", "SMS"


class Case(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    # The ID generated on the phone. Same in the app, the SMS and here, which is
    # what makes every upload idempotent.
    case_ref = models.CharField(
        max_length=32,
        unique=True,
        validators=[RegexValidator(CASE_REF_REGEX, "Invalid case reference")],
    )
    type = models.CharField(max_length=12, choices=CaseType.choices)
    status = models.CharField(max_length=12, choices=CaseStatus.choices, default=CaseStatus.NEW)
    source = models.CharField(max_length=4, choices=CaseSource.choices, default=CaseSource.APP)

    # Sensitive text is encrypted at rest (see fields.EncryptedTextField).
    description = EncryptedTextField(blank=True, default="")
    contact_phone = EncryptedTextField(blank=True, default="")

    location_text = models.CharField(max_length=200, blank=True)
    lat = models.FloatField(
        null=True, blank=True, validators=[MinValueValidator(-90), MaxValueValidator(90)]
    )
    lon = models.FloatField(
        null=True, blank=True, validators=[MinValueValidator(-180), MaxValueValidator(180)]
    )
    safe_to_call = models.BooleanField(default=False)

    reported_at = models.DateTimeField()  # when she saved it on her phone
    received_at = models.DateTimeField(auto_now_add=True)  # when we got it
    updated_at = models.DateTimeField(auto_now=True)

    assigned_to = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="cases",
    )

    class Meta:
        ordering = ["-received_at"]
        indexes = [
            models.Index(fields=["status"]),
            models.Index(fields=["type", "status"]),
            models.Index(fields=["assigned_to", "status"]),
            models.Index(fields=["-received_at"]),
        ]

    def __str__(self):
        return self.case_ref

    @property
    def is_open(self):
        return self.status in OPEN_STATUSES

    @property
    def is_urgent(self):
        """An SOS nobody has responded to yet."""
        return self.type == CaseType.SOS and self.status in WAITING_STATUSES

    @property
    def priority(self):
        if self.type == CaseType.SOS:
            return "urgent"
        if self.type == CaseType.VIOLENCE:
            return "high"
        return "medium"


class CaseUpdate(models.Model):
    """Audit trail: who did what to a case, and when."""

    class Kind(models.TextChoices):
        CREATED = "created", "Created"
        STATUS = "status", "Status change"
        ASSIGN = "assign", "Assignment"
        NOTE = "note", "Note"

    case = models.ForeignKey(Case, on_delete=models.CASCADE, related_name="updates")
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="case_updates",
    )
    kind = models.CharField(max_length=8, choices=Kind.choices)
    from_status = models.CharField(max_length=12, blank=True)
    to_status = models.CharField(max_length=12, blank=True)
    note = EncryptedTextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at", "id"]

    def __str__(self):
        return f"{self.case_id} {self.kind}"


class SmsInbound(models.Model):
    """Every SMS Africa's Talking forwards to us, parsed or not (for audit / manual handling)."""

    provider_id = models.CharField(max_length=64, unique=True, null=True, blank=True)
    sender = EncryptedTextField(blank=True, default="")
    text = EncryptedTextField(blank=True, default="")
    received_at = models.DateTimeField(auto_now_add=True)
    parsed = models.BooleanField(default=False)
    error = models.CharField(max_length=200, blank=True)
    case = models.ForeignKey(
        Case, null=True, blank=True, on_delete=models.SET_NULL, related_name="sms_messages"
    )

    class Meta:
        ordering = ["-received_at"]
        verbose_name = "inbound SMS"
        verbose_name_plural = "inbound SMS"

    def __str__(self):
        return f"SMS {self.provider_id or self.pk} ({'ok' if self.parsed else 'unparsed'})"
