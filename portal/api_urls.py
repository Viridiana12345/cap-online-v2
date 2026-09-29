from django.urls import path
from . import api_v1

urlpatterns = [
    path("auth/login/", api_v1.login_api, name="api_v1_login"),
    path("auth/logout/", api_v1.logout_api, name="api_v1_logout"),
    path("me/", api_v1.me_api, name="api_v1_me"),
    path("doctors/", api_v1.doctors_api, name="api_v1_doctors"),
    path("appointments/", api_v1.appointments_api, name="api_v1_appointments"),
    path("appointments/<int:appointment_id>/cancel/", api_v1.appointment_cancel_api, name="api_v1_appointment_cancel"),
    path("appointments/<int:appointment_id>/video/", api_v1.video_call_api, name="api_v1_video_call"),
    path("conversations/", api_v1.conversations_api, name="api_v1_conversations"),
    path("messages/<int:other_id>/", api_v1.messages_api, name="api_v1_messages"),
    path("notifications/", api_v1.notifications_api, name="api_v1_notifications"),
]
