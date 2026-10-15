from datetime import datetime, timedelta
from unittest.mock import patch

from django.contrib.auth.models import Group, User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from .models import Appointment, DoctorProfile


class DoctorDashboardTests(TestCase):
    def test_patient_modifies_same_appointment_and_requires_reasons(self):
        from datetime import time
        from .models import DoctorAvailability
        day = timezone.localdate() + timedelta(days=2)
        start = timezone.make_aware(datetime.combine(day, time(10)))
        DoctorAvailability.objects.create(doctor=self.doctor.doctor_profile,
            weekday=day.weekday(), start_time=time(9), end_time=time(17))
        appt = Appointment.objects.create(doctor=self.doctor, patient=self.patient,
            start_at=start, end_at=start+timedelta(minutes=30), status="approved")
        self.client.force_login(self.patient)
        url = reverse("appointment_reschedule", args=[appt.pk])
        data = {"start_at": (start+timedelta(hours=1)).isoformat(), "end_at": (start+timedelta(minutes=90)).isoformat()}
        self.client.post(url, data)
        appt.refresh_from_db()
        self.assertEqual(appt.start_at, start)
        data["reason"] = "Cambio de horario laboral"
        self.client.post(url, data)
        appt.refresh_from_db()
        self.assertEqual(appt.start_at, start+timedelta(hours=1))
        self.assertEqual(Appointment.objects.count(), 1)
        cancel = reverse("appointment_cancel", args=[appt.pk])
        self.client.post(cancel)
        appt.refresh_from_db()
        self.assertEqual(appt.status, "pending")
        self.client.post(cancel, {"reason": "No puedo asistir"})
        appt.refresh_from_db()
        self.assertEqual(appt.status, "cancelled")
        self.assertEqual(appt.cancellation_reason, "No puedo asistir")

    def test_month_calendar_returns_half_hours_and_last_start_at_nine(self):
        from datetime import time
        from .models import DoctorAvailability
        day = timezone.localdate() + timedelta(days=2)
        DoctorAvailability.objects.create(doctor=self.doctor.doctor_profile,
            weekday=day.weekday(), start_time=time(20), end_time=time(22))
        occupied = timezone.make_aware(datetime.combine(day, time(20, 30)))
        Appointment.objects.create(doctor=self.doctor, patient=self.patient,
            start_at=occupied, end_at=occupied+timedelta(minutes=30), status="approved")
        self.client.force_login(self.patient)
        response = self.client.get(reverse("appointment_availability_api"),
            {"doctor": self.doctor.pk, "month": day.strftime("%Y-%m")})
        self.assertEqual(response.status_code, 200)
        slots = response.json()["days"][day.isoformat()]
        self.assertEqual([datetime.fromisoformat(s["start"]).strftime("%H:%M") for s in slots], ["20:00", "21:00"])
        for slot in slots:
            self.assertEqual(datetime.fromisoformat(slot["end"])-datetime.fromisoformat(slot["start"]), timedelta(minutes=30))

    def test_server_rejects_unconfigured_or_long_appointments(self):
        from portal.views import _fits_availability
        from datetime import time
        from .models import DoctorAvailability
        day = timezone.localdate() + timedelta(days=1)
        start = timezone.make_aware(datetime.combine(day, time(10)))
        self.assertFalse(_fits_availability(self.doctor, start, start+timedelta(minutes=30)))
        DoctorAvailability.objects.create(doctor=self.doctor.doctor_profile,
            weekday=day.weekday(), start_time=time(9), end_time=time(22))
        self.assertTrue(_fits_availability(self.doctor, start, start+timedelta(minutes=30)))
        self.assertFalse(_fits_availability(self.doctor, start, start+timedelta(hours=1)))
    def test_chat_opens_for_both_roles(self):
        for user in (self.doctor, self.patient):
            self.client.force_login(user)
            response = self.client.get(reverse("portal_chat"))
            self.assertEqual(response.status_code, 200)
            self.assertTemplateUsed(response, "portal/chat.html")

    def test_doctor_appointments_render_with_shared_theme(self):
        response = self.client.get(reverse("portal_calendar_doctor"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Mis citas")
        self.assertContains(response, "portal/css/portal-theme.css")

    def setUp(self):
        self.doctor = User.objects.create_user("dashboard-doctor")
        self.doctor.groups.add(Group.objects.get_or_create(name="Doctores")[0])
        DoctorProfile.objects.create(user=self.doctor, cedula="DASH-1")
        self.doctor.doctor_profile.availability.all().delete()
        self.patient = User.objects.create_user("dashboard-patient", first_name="Paciente propio")
        self.patient.groups.add(Group.objects.get_or_create(name="Pacientes")[0])
        self.client.force_login(self.doctor)

    def test_empty_dashboard_renders(self):
        response = self.client.get(reverse("portal_dashboard"))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "portal/dashboard_doctor.html")
        self.assertContains(response, "Tu agenda está libre por ahora")
        self.assertEqual(response.context["doctor_stats"]["today"], 0)

    def test_metrics_and_agenda_are_scoped_to_doctor_and_status(self):
        now = timezone.localtime().replace(hour=10, minute=0, second=0, microsecond=0)
        for status in ("approved", "pending", "done", "cancelled"):
            Appointment.objects.create(doctor=self.doctor, patient=self.patient,
                                       start_at=now, end_at=now + timedelta(hours=1), status=status)
        other = User.objects.create_user("another-doctor")
        stranger = User.objects.create_user("private-patient", first_name="Paciente ajeno")
        Appointment.objects.create(doctor=other, patient=stranger, start_at=now,
                                   end_at=now + timedelta(hours=1), status="approved")
        with patch("portal.views.timezone.now", return_value=now):
            self.client.force_login(self.doctor)
            response = self.client.get(reverse("portal_dashboard"))
        self.assertEqual(response.context["doctor_stats"], {"today": 1, "pending": 1, "completed": 1})
        self.assertEqual(response.context["patient_count"], 1)
        self.assertEqual(len(response.context["upcoming_sessions"]), 1)
        self.assertEqual(len(response.context["pending_requests"]), 1)
        self.assertNotContains(response, "Paciente ajeno")

    def test_patient_dashboard_renders(self):
        self.client.force_login(self.patient)
        response = self.client.get(reverse("portal_dashboard"))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "portal/dashboard_patient.html")

    def test_patient_metrics_exclude_other_patients_and_include_current_call(self):
        now = timezone.now()
        current = Appointment.objects.create(doctor=self.doctor, patient=self.patient,
            start_at=now - timedelta(minutes=10), end_at=now + timedelta(minutes=40),
            status="approved", modalidad="online")
        stranger = User.objects.create_user("private-dashboard-patient")
        Appointment.objects.create(doctor=self.doctor, patient=stranger,
            start_at=now, end_at=now + timedelta(hours=1), status="pending")
        self.client.force_login(self.patient)
        response = self.client.get(reverse("portal_dashboard"))
        self.assertEqual(response.context["patient_stats"], {"pending": 0, "approved": 1, "completed": 0})
        self.assertEqual(response.context["next_appointment"], current)
        self.assertEqual(len(response.context["recent_appointments"]), 1)
        self.assertContains(response, reverse("video_room", args=[current.pk]))

    def test_charts_include_zero_months_and_exclude_other_doctors_and_dates(self):
        from .dashboard_metrics import doctor_charts
        today = datetime(2026, 1, 15).date()
        start = timezone.make_aware(datetime(2026, 1, 15, 10))
        other = User.objects.create_user("chart-other-doctor")
        for doctor, status, moment in (
            (self.doctor, "done", start),
            (self.doctor, "done", timezone.make_aware(datetime(2025, 8, 1, 0))),
            (self.doctor, "done", timezone.make_aware(datetime(2025, 7, 31, 23))),
            (self.doctor, "approved", start + timedelta(days=6)),
            (self.doctor, "approved", start + timedelta(days=7)),
            (other, "done", start),
            (other, "approved", start),
        ):
            Appointment.objects.create(doctor=doctor, patient=self.patient, status=status,
                                       start_at=moment, end_at=moment + timedelta(hours=1))
        with self.assertNumQueries(3):
            charts = doctor_charts(self.doctor, today)
        self.assertEqual([bar["count"] for bar in charts["months"]], [1, 0, 0, 0, 0, 1])
        self.assertEqual(charts["completed"], 2)
        self.assertEqual(charts["total"], 2)
        self.assertEqual(charts["week_total"], 1)
        self.assertEqual(charts["week"][-1]["count"], 1)

    def test_empty_charts_have_zero_values(self):
        from .dashboard_metrics import doctor_charts
        charts = doctor_charts(self.doctor, timezone.localdate())
        self.assertEqual(charts["total"], 0)
        self.assertTrue(all(bar["height"] == 0 for bar in charts["months"]))
        self.assertTrue(all(bar["percent"] == 0 for bar in charts["statuses"]))
