from django.urls import path

from . import web_views

app_name = "dashboard"

urlpatterns = [
    path("", web_views.index, name="index"),
    path("cases/", web_views.case_list, name="cases"),
    path("cases/<uuid:pk>/assign/", web_views.assign, name="assign"),
    path("chws/", web_views.chw_list, name="chws"),
]
