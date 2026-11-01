from django.urls import path

from . import casework, chw_cases, views
from .ussd import UssdView

urlpatterns = [
    path("help-directory/", views.HelpDirectoryView.as_view()),
    path("status/<str:case_ref>/", views.CaseStatusView.as_view()),
    path("devices/", views.DeviceTokenView.as_view()),
    path("reports/anonymous/", views.AnonymousStatsView.as_view()),
    path("reports/anonymous.csv", views.ExportCsvView.as_view()),
    path("reports/response-times/", views.ResponseTimesView.as_view()),
    path("ussd/africastalking/", UssdView.as_view()),
    path("new-case/", chw_cases.CreateCaseView.as_view()),
    path("cases/<uuid:case_id>/followups/", casework.CaseFollowUps.as_view()),
    path("cases/<uuid:case_id>/referrals/", casework.CaseReferrals.as_view()),
    path("followups/mine/", casework.MyFollowUps.as_view()),
    path("followups/<int:pk>/", casework.FollowUpDetail.as_view()),
    path("referrals/<int:pk>/", casework.ReferralDetail.as_view()),
]
