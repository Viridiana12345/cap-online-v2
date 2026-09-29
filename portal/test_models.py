from datetime import time, timedelta

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.utils import timezone

from .models import (
    Appointment, ChatMessage, Conversation, DoctorAvailability, DoctorProfile,
    Notification, VideoCall,
)

User = get_user_model()


class PreparedModelTests(TestCase):
    def setUp(self):
        self.patient = User.objects.create_user(username="patient-model")
        self.doctor_user = User.objects.create_user(username="doctor-model")
        self.doctor = DoctorProfile.objects.create(
            user=self.doctor_user, especialidad="Psicología", cedula="test",
        )
        self.start = timezone.now() + timedelta(days=1)

    def appointment(self, **kwargs):
        return Appointment.objects.create(
            patient=self.patient, doctor=self.doctor_user,
            start_at=self.start, end_at=self.start + timedelta(hours=1), **kwargs,
        )

    def test_existing_appointment_and_chat_creation_remain_compatible(self):
        appointment = self.appointment(notes="Motivo original")
        message = ChatMessage.objects.create(
            sender=self.patient, receiver=self.doctor_user, text="Mensaje original",
        )
        self.assertEqual(appointment.modalidad, "")
        self.assertIsNone(appointment.cancelled_at)
        self.assertIsNone(appointment.rescheduled_from_id)
        self.assertFalse(VideoCall.objects.filter(appointment=appointment).exists())
        self.assertIsNone(message.conversation_id)

    def test_availability_accepts_multiple_intervals_and_rejects_invalid_ones(self):
        for start, end in ((time(9), time(12)), (time(14), time(18))):
            DoctorAvailability.objects.create(
                doctor=self.doctor, weekday=0, start_time=start, end_time=end,
            )
        self.assertEqual(self.doctor.availability.count(), 2)
        for weekday, start, end in ((7, time(9), time(10)), (0, time(10), time(9))):
            with self.subTest(weekday=weekday, start=start):
                with self.assertRaises(IntegrityError), transaction.atomic():
                    DoctorAvailability.objects.create(
                        doctor=self.doctor, weekday=weekday, start_time=start, end_time=end,
                    )

    def test_conversation_is_unique_and_messages_validate_participants(self):
        conversation = Conversation.objects.create(patient=self.patient, doctor=self.doctor)
        with self.assertRaises(IntegrityError), transaction.atomic():
            Conversation.objects.create(patient=self.patient, doctor=self.doctor)
        message = ChatMessage(
            conversation=conversation, sender=self.patient, receiver=self.doctor_user, text="Hola",
        )
        message.full_clean()
        message.save()
        outsider = User.objects.create_user(username="outsider")
        message.receiver = outsider
        with self.assertRaises(ValidationError):
            message.full_clean()
        self.assertEqual(conversation.messages.count(), 1)

    def test_conversation_rejects_same_patient_and_doctor(self):
        with self.assertRaises(ValidationError):
            Conversation(patient=self.doctor_user, doctor=self.doctor).full_clean()

    def test_rescheduling_preserves_old_dates_and_has_one_successor(self):
        previous = self.appointment(status="rescheduled")
        replacement = self.appointment(rescheduled_from=previous)
        replacement.start_at += timedelta(days=1)
        replacement.end_at += timedelta(days=1)
        replacement.full_clean()
        replacement.save()
        previous.refresh_from_db()
        self.assertEqual(previous.start_at, self.start)
        self.assertEqual(previous.rescheduled_to, replacement)
        with self.assertRaises(IntegrityError), transaction.atomic():
            self.appointment(rescheduled_from=previous)
        replacement.rescheduled_from = replacement
        with self.assertRaises(ValidationError):
            replacement.full_clean()

    def test_cancellation_metadata_and_notification_read_state(self):
        appointment = self.appointment(
            status="cancelled", cancelled_at=timezone.now(),
            cancelled_by=self.patient, cancellation_reason="Cambio de planes",
        )
        appointment.full_clean()
        notice = Notification.objects.create(
            user=self.patient, title="Cita cancelada", message="Se canceló tu cita",
            notification_type="appointment_cancelled",
        )
        self.assertFalse(notice.is_read)
        notice.is_read = True
        notice.save(update_fields=["is_read"])
        notice.refresh_from_db()
        self.assertTrue(notice.is_read)

    def test_video_call_requires_one_appointment_without_provider(self):
        appointment = self.appointment()
        call = VideoCall.objects.create(appointment=appointment)
        self.assertEqual(appointment.video_call, call)
        with self.assertRaises(IntegrityError), transaction.atomic():
            VideoCall.objects.create(appointment=appointment)
        with self.assertRaises(IntegrityError), transaction.atomic():
            VideoCall.objects.create()
