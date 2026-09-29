from django.urls import path
from . import views

urlpatterns = [
    path("", views.landing, name="landing"),
    path("login/", views.login_view, name="login"),
    path("logout/", views.logout_view, name="logout"),
    path("signup/", views.signup, name="signup"),
    path("politica-privacidad/", views.politica_privacidad, name="politica_privacidad"),

    path("portal/", views.dashboard, name="portal_dashboard"),
    path("portal/notificaciones/", views.notifications, name="portal_notifications"),
    path("portal/especialistas/", views.specialists, name="portal_specialists"),
    path("portal/perfil/<int:doctor_id>/", views.profile, name="portal_profile"),
    path("portal/configuracion/", views.settings_view, name="portal_settings"),
    path("portal/update-profile/", views.update_profile, name="update_profile"),

    path("portal/calendario/", views.calendar_view, name="portal_calendar"),
    path("portal/calendario/paciente/", views.calendar_patient, name="portal_calendar_patient"),
    path("portal/calendario/doctor/", views.calendar_doctor, name="portal_calendar_doctor"),
    path("portal/appointment/create/", views.appointment_create, name="appointment_create"),
    path("portal/appointment/<int:appt_id>/status/<str:new_status>/", views.appointment_update_status, name="appointment_update_status"),
    path("portal/appointment/<int:appt_id>/cancel/", views.appointment_cancel, name="appointment_cancel"),
    path("portal/appointment/<int:appt_id>/reschedule/", views.appointment_reschedule, name="appointment_reschedule"),
    path("portal/disponibilidad/nueva/", views.availability_create, name="availability_create"),
    path("portal/disponibilidad/<int:availability_id>/eliminar/", views.availability_delete, name="availability_delete"),

    path("portal/chat/", views.chat, name="portal_chat"),
    path("portal/chat/<int:user_id>/", views.chat, name="portal_chat_with"),
    path("portal/send-message/<int:user_id>/", views.send_message, name="send_message"),
    path("portal/api/chat/thread/<int:user_id>/", views.chat_thread_api, name="chat_thread_api"),
    path("portal/api/chat/send/<int:user_id>/", views.chat_send_api, name="chat_send_api"),

    path("portal/notas-clinicas/", views.mis_notas_clinicas, name="mis_notas_clinicas"),
    path("portal/paciente/<int:patient_id>/notas/", views.notas_paciente, name="notas_paciente"),

    path("portal/llamadas/", views.video_calls, name="video_calls"),
    path("portal/video/<int:appointment_id>/", views.video_room, name="video_room"),
    path("portal/video/<int:appointment_id>/end/", views.video_end, name="video_end"),
    path("portal/api/call/<str:room_key>/pull/", views.call_signals_pull, name="call_signals_pull"),
    path("portal/api/call/<str:room_key>/push/", views.call_signals_push, name="call_signals_push"),

    path("portal/rh/doctores/", views.doctor_list, name="doctor_list"),
    path("portal/rh/doctores/nuevo/", views.doctor_create, name="doctor_create"),
]
