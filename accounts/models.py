from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):
    """
    One table for admins and CHWs. For a CHW the `username` IS the CHW ID,
    e.g. CHW-KWALE-001 (that is what they type in the app).
    """

    class Role(models.TextChoices):
        ADMIN = "admin", "Admin"
        CHW = "chw", "Community Health Worker"

    role = models.CharField(max_length=10, choices=Role.choices, default=Role.CHW)
    full_name = models.CharField(max_length=120, blank=True)
    phone = models.CharField(max_length=20, blank=True)
    area = models.CharField(max_length=80, blank=True, help_text="e.g. Ukunda, Msambweni")

    def save(self, *args, **kwargs):
        if self.is_superuser:
            self.role = self.Role.ADMIN
        if self.role == self.Role.ADMIN:
            self.is_staff = True  # needed for the Django admin login page
        super().save(*args, **kwargs)

    @property
    def is_salama_admin(self) -> bool:
        return self.is_active and (self.is_superuser or self.role == self.Role.ADMIN)

    @property
    def is_chw(self) -> bool:
        return self.is_active and self.role == self.Role.CHW

    @property
    def display_name(self) -> str:
        return self.full_name or self.username

    def __str__(self):
        return f"{self.username} ({self.display_name})" if self.full_name else self.username
