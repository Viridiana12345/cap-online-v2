from datetime import time
from importlib import import_module
from types import SimpleNamespace

from django.apps import apps
from django.contrib.auth.models import Group, User
from django.test import TestCase
from django.urls import reverse

from .models import DoctorAvailability, DoctorProfile


class DefaultHoursTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("hours-doctor")
        self.user.groups.add(Group.objects.get_or_create(name="Doctores")[0])
        self.doctor = DoctorProfile.objects.create(user=self.user)
        self.client.force_login(self.user)

    def test_new_doctor_gets_weekday_hours_once(self):
        self.assertEqual(list(self.doctor.availability.values_list("weekday", "start_time", "end_time")),
                         [(d, time(8), time(17)) for d in range(5)])
        self.doctor.save()
        self.assertEqual(self.doctor.availability.count(), 5)
        self.doctor.availability.all().delete()
        self.doctor.save()
        self.client.get(reverse("portal_calendar_doctor"))
        self.assertFalse(self.doctor.availability.exists())

    def test_edit_survives_redirect_and_refresh(self):
        slot = self.doctor.availability.first()
        response = self.client.post(reverse("availability_edit", args=[slot.pk]),
            {"weekday": 0, "start_time": "10:00", "end_time": "15:00", "active": "on"}, follow=True)
        self.assertEqual(response.status_code, 200)
        slot.refresh_from_db()
        self.assertEqual((slot.start_time, slot.end_time), (time(10), time(15)))
        self.doctor.save()
        self.client.get(reverse("portal_calendar_doctor"))
        slot.refresh_from_db()
        self.assertEqual(slot.start_time, time(10))

    def test_invalid_edit_preserves_form_and_database(self):
        slot = self.doctor.availability.first()
        response = self.client.post(reverse("availability_edit", args=[slot.pk]),
            {"weekday": 0, "start_time": "16:00", "end_time": "10:00", "active": "on"})
        self.assertTrue(response.context["form"].errors)
        self.assertEqual(response.context["form"]["start_time"].value(), "16:00")
        slot.refresh_from_db()
        self.assertEqual(slot.start_time, time(8))

    def test_migration_preserves_custom_hours_and_seeds_missing_only(self):
        slot = self.doctor.availability.first()
        slot.start_time = time(11)
        slot.save()
        other = DoctorProfile.objects.create(user=User.objects.create_user("missing-hours"))
        other.availability.all().delete()
        seed = import_module("portal.migrations.0014_default_doctor_availability").seed_hours
        seed(apps, SimpleNamespace(connection=SimpleNamespace(alias="default")))
        seed(apps, SimpleNamespace(connection=SimpleNamespace(alias="default")))
        slot.refresh_from_db()
        self.assertEqual(slot.start_time, time(11))
        self.assertEqual(other.availability.count(), 5)
