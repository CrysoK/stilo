from django import forms
from django.utils import timezone
from django.contrib.auth.forms import UserCreationForm
from .models import User, Hairdresser, Appointment, Service


class SignUpForm(UserCreationForm):
    is_owner = forms.BooleanField(
        required=False,
        label="Soy dueño de una peluquería",
        help_text="Marca esta opción si deseas registrar tu peluquería",
        widget=forms.CheckboxInput(attrs={'class': 'form-check-input'})
    )

    hairdresser_name = forms.CharField(
        max_length=100,
        required=False,
        label="Nombre de la peluquería",
        widget=forms.TextInput(attrs={'class': 'form-control'})
    )
    hairdresser_address = forms.CharField(
        max_length=255,
        required=False,
        label="Dirección de la peluquería",
        widget=forms.TextInput(attrs={'class': 'form-control'})
    )

    class Meta:
        model = User
        fields = (
            *(UserCreationForm._meta.fields or ()),
            "first_name",
            "last_name",
            "email",
            "is_owner",
        )

    def clean(self):
        cleaned_data = super().clean()
        is_owner = cleaned_data.get("is_owner")
        if is_owner:
            if not cleaned_data.get("hairdresser_name"):
                self.add_error(
                    "hairdresser_name",
                    "Este campo es obligatorio si eres dueño de una peluquería."
                )
            if not cleaned_data.get("hairdresser_address"):
                self.add_error(
                    "hairdresser_address",
                    "Este campo es obligatorio si eres dueño de una peluquería."
                )
        return cleaned_data

    def save(self, commit=True):
        user = super().save(commit=False)
        user.is_owner = self.cleaned_data.get("is_owner", False)
        
        if commit:
            user.save()
            if user.is_owner:
                Hairdresser.objects.create(
                    owner=user,
                    name=self.cleaned_data["hairdresser_name"],
                    address=self.cleaned_data["hairdresser_address"],
                )
        return user


class AppointmentForm(forms.ModelForm):
    start_time = forms.DateTimeField(
        label="Fecha y Hora del Turno",
        widget=forms.DateTimeInput(
            attrs={"type": "datetime-local"}, format="%Y-%m-%dT%H:%M"
        ),
    )

    class Meta:
        model = Appointment
        fields = ["service", "start_time"]

    def __init__(self, *args, **kwargs):
        hairdresser = kwargs.pop("hairdresser", None)
        super().__init__(*args, **kwargs)
        if hairdresser:
            self.fields["service"].queryset = Service.objects.filter(  # type: ignore
                hairdresser=hairdresser
            )
        now = timezone.now()
        local_now = timezone.localtime(now)
        min_datetime_str = local_now.strftime("%Y-%m-%dT%H:%M:%S")
        self.fields["start_time"].widget.attrs["min"] = min_datetime_str

    def clean_start_time(self):
        """
        Valida que la fecha y hora del turno no sea en el pasado.
        """
        # Obtenemos el valor del campo del formulario ya procesado por Django
        start_time = self.cleaned_data.get("start_time")

        # Comparamos con la hora actual
        if start_time and start_time <= timezone.now():
            # Si la fecha es pasada o actual, lanzamos un error de validación.
            # Este mensaje se mostrará al usuario junto al campo del formulario.
            raise forms.ValidationError(
                "No puedes reservar un turno en el pasado. Por favor, elige una fecha y hora futura.",
                code="past_date",
            )

        return start_time
