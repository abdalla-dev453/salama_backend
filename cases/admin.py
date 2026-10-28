from django.contrib import admin

from .models import Case, CaseStatus, CaseUpdate, SmsInbound


class CaseUpdateInline(admin.TabularInline):
    model = CaseUpdate
    extra = 0
    can_delete = False
    readonly_fields = ("created_at", "author", "kind", "from_status", "to_status", "note")

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(Case)
class CaseAdmin(admin.ModelAdmin):
    list_display = ("case_ref", "type", "status", "location_text", "assigned_to",
                    "source", "received_at")
    list_filter = ("status", "type", "source", "assigned_to")
    search_fields = ("case_ref", "location_text")
    date_hierarchy = "received_at"
    readonly_fields = ("id", "case_ref", "received_at", "updated_at", "source")
    inlines = [CaseUpdateInline]
    actions = ["mark_closed"]

    @admin.action(description="Mark selected cases as Closed")
    def mark_closed(self, request, queryset):
        for case in queryset:
            old = case.status
            case.status = CaseStatus.CLOSED
            case.save()
            CaseUpdate.objects.create(case=case, author=request.user, kind=CaseUpdate.Kind.STATUS,
                                      from_status=old, to_status=CaseStatus.CLOSED)


@admin.register(SmsInbound)
class SmsInboundAdmin(admin.ModelAdmin):
    """Read-only inbox. Look at 'unparsed' messages here and handle them by hand."""

    list_display = ("__str__", "received_at", "parsed", "error", "case")
    list_filter = ("parsed",)
    readonly_fields = ("provider_id", "sender", "text", "received_at", "parsed", "error", "case")

    def has_add_permission(self, request):
        return False
