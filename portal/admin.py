from django.contrib import admin
from django import forms
from django.contrib.auth.admin import UserAdmin
from django.contrib.auth.forms import AdminUserCreationForm, UserChangeForm
from django.contrib.auth.models import User
from .forms import validate_unique_email
from .permissions import is_doctor, care_patient_ids
from .models import DoctorProfile, PatientProfile, Appointment, ChatMessage, CallRequest, CallSignal
from .models import SessionNote
from .models import AuditLog


class UniqueEmailMixin:
    def clean_email(self):
        email = self.cleaned_data.get("email", "").strip().lower()
        return validate_unique_email(email, self.instance.pk) if email else email


class CAPUserCreationForm(UniqueEmailMixin, AdminUserCreationForm):
    email = forms.EmailField(required=True)

    class Meta(AdminUserCreationForm.Meta):
        fields = ("username", "email")


class CAPUserChangeForm(UniqueEmailMixin, UserChangeForm):
    pass


admin.site.unregister(User)


@admin.register(User)
class CAPUserAdmin(UserAdmin):
    add_form = CAPUserCreationForm
    form = CAPUserChangeForm
    add_fieldsets = UserAdmin.add_fieldsets + (("Contacto", {"fields": ("email",)}),)


class ClinicalNoteAdminForm(forms.ModelForm):
    class Meta:
        model = SessionNote
        exclude = ("doctor",)

    def clean(self):
        data = super().clean()
        appointment = data.get("appointment")
        patient = data.get("patient")
        if appointment and patient and appointment.patient_id != patient.pk:
            self.add_error("appointment", "La cita debe pertenecer al paciente seleccionado.")
        return data

@admin.register(DoctorProfile)
class DoctorProfileAdmin(admin.ModelAdmin):
    list_display = (
        "user",
        "especialidad",
        "cedula",
        "telefono",
        "modalidad",
        "duracion_sesion",
        "activo",
    )
    search_fields = (
        "user__first_name",
        "user__last_name",
        "user__email",
        "especialidad",
        "cedula",
    )
    list_filter = ("activo", "modalidad", "especialidad")


@admin.register(ChatMessage)
class ChatMessageAdmin(admin.ModelAdmin):
    list_display = ("sender", "receiver", "created_at", "is_read")
    search_fields = ("sender__username", "receiver__username", "text")
    list_filter = ("is_read", "created_at")


@admin.register(PatientProfile)
class PatientProfileAdmin(admin.ModelAdmin):
    list_display = ("user", "telefono")
    search_fields = ("user__first_name", "user__last_name", "user__email", "telefono")


@admin.register(Appointment)
class AppointmentAdmin(admin.ModelAdmin):
    list_display = ("patient", "doctor", "start_at", "end_at", "status")
    list_filter = ("status", "start_at")
    search_fields = (
        "patient__first_name",
        "patient__last_name",
        "doctor__first_name",
        "doctor__last_name",
    )


@admin.register(CallRequest)
class CallRequestAdmin(admin.ModelAdmin):
    list_display = ("user", "doctor", "call_type", "status", "created_at")
    list_filter = ("status", "call_type", "created_at")


@admin.register(CallSignal)
class CallSignalAdmin(admin.ModelAdmin):
    list_display = ("room_key", "sender", "id")

@admin.register(SessionNote)
class SessionNoteAdmin(admin.ModelAdmin):
    form = ClinicalNoteAdminForm
    list_display = ('titulo', 'doctor', 'patient', 'estado_emocional', 'created_at')
    list_filter = ('estado_emocional', 'created_at')
    search_fields = ('titulo', 'doctor__username', 'patient__username', 'observaciones')
    readonly_fields = ('created_at',)

    def get_queryset(self, request):
        return super().get_queryset(request).filter(
            doctor=request.user, patient_id__in=care_patient_ids(request.user),
        )

    def has_module_permission(self, request):
        return is_doctor(request.user) and super().has_module_permission(request)

    def has_view_permission(self, request, obj=None):
        return is_doctor(request.user) and super().has_view_permission(request, obj) and (
            obj is None or self.get_queryset(request).filter(pk=obj.pk).exists()
        )

    def has_add_permission(self, request):
        return is_doctor(request.user) and super().has_add_permission(request)

    def has_change_permission(self, request, obj=None):
        return is_doctor(request.user) and super().has_change_permission(request, obj) and (
            obj is None or self.get_queryset(request).filter(pk=obj.pk).exists()
        )

    def has_delete_permission(self, request, obj=None):
        return is_doctor(request.user) and super().has_delete_permission(request, obj) and (
            obj is None or self.get_queryset(request).filter(pk=obj.pk).exists()
        )

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name == "patient":
            kwargs["queryset"] = User.objects.filter(
                pk__in=care_patient_ids(request.user), groups__name="Pacientes",
                is_active=True, is_staff=False, is_superuser=False,
            ).exclude(groups__name="Doctores").distinct()
        elif db_field.name == "appointment":
            kwargs["queryset"] = Appointment.objects.filter(
                doctor=request.user, status__in=("approved", "done"),
            )
        return super().formfield_for_foreignkey(db_field, request, **kwargs)

    def save_model(self, request, obj, form, change):
        obj.doctor = request.user
        super().save_model(request, obj, form, change)

@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    list_display = ("usuario", "accion", "modulo", "ip", "fecha")
    search_fields = ("usuario__username", "accion", "modulo")
    list_filter = ("modulo", "fecha")
