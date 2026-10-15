from django import forms
from django.utils import timezone
from .models import Appointment, SessionNote


class SessionNoteForm(forms.ModelForm):
    class Meta:
        model = SessionNote
        fields = ["titulo", "appointment", "estado_emocional", "observaciones", "recomendaciones", "proxima_sesion"]
        labels = {"titulo": "Título", "appointment": "Cita relacionada (opcional)",
                  "estado_emocional": "Estado emocional", "observaciones": "Observaciones",
                  "recomendaciones": "Recomendaciones", "proxima_sesion": "Fecha sugerida de seguimiento"}
        widgets = {"observaciones": forms.Textarea(attrs={"rows": 5}),
                   "recomendaciones": forms.Textarea(attrs={"rows": 3}),
                   "proxima_sesion": forms.DateInput(format="%Y-%m-%d", attrs={"type": "date"})}

    def __init__(self, *args, doctor, patient, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["appointment"].queryset = Appointment.objects.filter(
            doctor=doctor, patient=patient).order_by("-start_at")
        self.fields["appointment"].label_from_instance = lambda a: f"{timezone.localtime(a.start_at):%d/%m/%Y %H:%M} · {a.get_status_display()}"
        self.fields["proxima_sesion"].help_text = "Es un recordatorio; no reserva ni modifica una cita."
