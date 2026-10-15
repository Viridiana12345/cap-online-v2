from datetime import time

from django.db.models.signals import post_save
from django.dispatch import receiver

from .models import DoctorAvailability, DoctorProfile


@receiver(post_save, sender=DoctorProfile, dispatch_uid="portal_initial_doctor_hours")
def initial_doctor_hours(sender, instance, created, raw=False, using="default", **kwargs):
    if created and not raw:
        DoctorAvailability.objects.using(using).bulk_create([
            DoctorAvailability(doctor_id=instance.pk, weekday=day,
                               start_time=time(8), end_time=time(17), active=True)
            for day in range(5)
        ])
