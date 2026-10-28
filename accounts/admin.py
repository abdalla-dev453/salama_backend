from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin

from .models import User

_salama_fields = ("SALAMA", {"fields": ("role", "full_name", "phone", "area")})


@admin.register(User)
class UserAdmin(DjangoUserAdmin):
    fieldsets = DjangoUserAdmin.fieldsets + (_salama_fields,)
    add_fieldsets = DjangoUserAdmin.add_fieldsets + (_salama_fields,)
    list_display = ("username", "full_name", "role", "area", "phone", "is_active", "last_login")
    list_filter = ("role", "is_active", "area")
    search_fields = ("username", "full_name", "phone")
