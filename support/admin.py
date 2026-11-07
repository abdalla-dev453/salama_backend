from django.contrib import admin

from .models import Article, Broadcast, Feedback, Subscriber

@admin.register(Article)
class ArticleAdmin(admin.ModelAdmin):
    list_display = ("title_en", "is_active", "sort_order", "updated_at")
    list_editable = ("is_active", "sort_order")


admin.site.register(Feedback)
admin.site.register(Broadcast)