from django.urls import path

from . import api

urlpatterns = [
    path("chat/<str:case_ref>/", api.SurvivorChat.as_view()),
    path("chat-staff/<uuid:case_id>/", api.StaffChat.as_view()),
    path("survivor-devices/", api.SurvivorDeviceView.as_view()),
    path("evidence/item/<int:pk>/", api.EvidenceItem.as_view()),
    path("evidence/<str:case_ref>/", api.EvidenceUpload.as_view()),
    path("case-evidence/<uuid:case_id>/", api.CaseEvidenceList.as_view()),
    path("checkin/<uuid:device_id>/", api.CheckInView.as_view()),
    path("checkin/<uuid:device_id>/ok/", api.CheckInOk.as_view()),
    path("feedback/", api.FeedbackView.as_view()),
    path("awareness/", api.AwarenessView.as_view()),
    path("subscribe/", api.SubscribeView.as_view()),
    path("tasks/mine/", api.MyTasks.as_view()),
    path("case-visits/<uuid:case_id>/", api.CaseVisits.as_view()),
]
