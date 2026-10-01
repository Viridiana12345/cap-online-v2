from django.db import migrations


def assign_doctor_group(apps, schema_editor):
    """Completa el rol de los perfiles creados anteriormente desde Django Admin."""
    Group = apps.get_model("auth", "Group")
    DoctorProfile = apps.get_model("portal", "DoctorProfile")
    doctor_group, _ = Group.objects.get_or_create(name="Doctores")
    doctor_group.user_set.add(
        *DoctorProfile.objects.values_list("user_id", flat=True)
    )


def noop_reverse(apps, schema_editor):
    # No retirar roles al revertir: el grupo puede haber sido asignado manualmente.
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("portal", "0012_alter_doctorprofile_foto"),
    ]

    operations = [
        migrations.RunPython(assign_doctor_group, noop_reverse),
    ]
