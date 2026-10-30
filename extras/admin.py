from django.contrib import admin

from .models import DeviceToken, FollowUp, HelpContact, Referral


@admin.register(HelpContact)
class HelpContactAdmin(admin.ModelAdmin):
    list_display = ("name", "category", "area", "phone", "is_active", "sort_order", "updated_at")
    list_filter = ("category", "area", "is_active")
    search_fields = ("name", "phone", "address")
    list_editable = ("is_active", "sort_order")


@admin.register(DeviceToken)
class DeviceTokenAdmin(admin.ModelAdmin):
    list_display = ("user", "platform", "last_seen")
    readonly_fields = ("token",)


@admin.register(Referral)
class ReferralAdmin(admin.ModelAdmin):
    list_display = ("case", "facility_name", "contact", "outcome", "created_at")
    list_filter = ("outcome",)


@admin.register(FollowUp)
class FollowUpAdmin(admin.ModelAdmin):
    list_display = ("case", "due_date", "done")
    list_filter = ("done",)
