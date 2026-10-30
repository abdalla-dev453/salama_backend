from django.contrib import admin
from django.urls import include, path
from django.views.generic import RedirectView

admin.site.site_header = "SALAMA Admin"
admin.site.site_title = "SALAMA"
admin.site.index_title = "Administration"

urlpatterns = [
    path("", RedirectView.as_view(url="/dashboard/", permanent=False)),
    path("admin/", admin.site.urls),
    path("dashboard/", include("cases.web_urls")),
    path("api/", include("accounts.api_urls")),
    path("api/", include("cases.api_urls")),
    path("api/", include("extras.api_urls")),
]
