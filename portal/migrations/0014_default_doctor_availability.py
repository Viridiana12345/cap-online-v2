from datetime import time
from django.db import migrations


def seed_hours(apps, schema_editor):
    Doctor = apps.get_model("portal", "DoctorProfile")
    Availability = apps.get_model("portal", "DoctorAvailability")
    alias = schema_editor.connection.alias
    existing = Availability.objects.using(alias).values("doctor_id")
    doctors = Doctor.objects.using(alias).exclude(pk__in=existing).values_list("pk", flat=True)
    Availability.objects.using(alias).bulk_create([
        Availability(doctor_id=doctor_id, weekday=day, start_time=time(8), end_time=time(17), active=True)
        for doctor_id in doctors for day in range(5)
    ], batch_size=500)


class Migration(migrations.Migration):
    dependencies = [("portal", "0013_assign_doctor_group")]
    operations = [migrations.RunPython(seed_hours, migrations.RunPython.noop)]
