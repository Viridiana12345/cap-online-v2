import json
from datetime import timedelta

from django.contrib.auth.models import Group, User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from .models import Appointment, DoctorProfile, PatientProfile


class MobileApiTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        pg = Group.objects.create(name="Pacientes")
        dg = Group.objects.create(name="Doctores")
        cls.patient = User.objects.create_user("p@example.com", "p@example.com", "StrongPass123!")
        cls.patient.groups.add(pg); PatientProfile.objects.create(user=cls.patient)
        cls.doctor = User.objects.create_user("d@example.com", "d@example.com", "StrongPass123!", first_name="Elena")
        cls.doctor.groups.add(dg)
        DoctorProfile.objects.create(user=cls.doctor, especialidad="Psicología clínica", cedula="ABC", activo=True)
        start = timezone.now() + timedelta(days=1)
        cls.appt = Appointment.objects.create(patient=cls.patient, doctor=cls.doctor, start_at=start,
                                              end_at=start + timedelta(hours=1), modalidad="online", status="approved")

    def login(self):
        r = self.client.post(reverse("api_v1_login"), data=json.dumps({"email":"p@example.com","password":"StrongPass123!"}), content_type="application/json")
        self.assertEqual(r.status_code, 200)
        return r.json()["token"]

    def auth(self, token):
        return {"HTTP_AUTHORIZATION": f"Bearer {token}"}

    def test_login_me_and_doctors(self):
        token = self.login()
        self.assertEqual(self.client.get(reverse("api_v1_me"), **self.auth(token)).json()["user"]["role"], "patient")
        doctors = self.client.get(reverse("api_v1_doctors"), **self.auth(token)).json()["doctors"]
        self.assertEqual(doctors[0]["name"], "Elena")

    def test_appointments_are_scoped(self):
        token = self.login()
        data = self.client.get(reverse("api_v1_appointments"), **self.auth(token)).json()["appointments"]
        self.assertEqual([x["id"] for x in data], [self.appt.id])

    def test_video_call_requires_participant_and_approved_online(self):
        token = self.login()
        r = self.client.post(reverse("api_v1_video_call", args=[self.appt.id]), data="{}", content_type="application/json", **self.auth(token))
        self.assertEqual(r.status_code, 200)
        self.assertIn("cap-appointment-", r.json()["video_call"]["room_key"])

    def test_invalid_token_rejected(self):
        self.assertEqual(self.client.get(reverse("api_v1_me"), HTTP_AUTHORIZATION="Bearer bad").status_code, 401)
