from django import forms
from django.utils import timezone
from django.contrib.auth.forms import UserCreationForm
from .models import User, Hairdresser, Appointment, Service


class SignUpForm(UserCreationForm):
    ROLE_CHOICES = (
        ("CLIENT", "Soy un cliente"),
        ("OWNER", "Soy dueño de una peluquería"),
    )
    role = forms.ChoiceField(
        choices=ROLE_CHOICES,
        required=True,
        label="Quiero registrarme como",
        widget=forms.RadioSelect,
    )

    # Si es dueño:
    hairdresser_name = forms.CharField(
        max_length=100, required=False, label="Nombre de la peluquería"
    )
    hairdresser_address = forms.CharField(
        max_length=255, required=False, label="Dirección de la peluquería"
    )

    class Meta:
        model = User
        fields = (
            *(UserCreationForm._meta.fields or ()),
            "first_name",
            "last_name",
            "email",
        )

    def clean(self):
        cleaned_data = super().clean()
        role = cleaned_data.get("role")
        if role == "OWNER":
            if not cleaned_data.get("hairdresser_name"):
                self.add_error(
                    "hairdresser_name",
                    "Este campo es obligatorio si eres dueño de una peluquería.",
                )
            if not cleaned_data.get("hairdresser_address"):
                self.add_error(
                    "hairdresser_address",
                    "Este campo es obligatorio si eres dueño de una peluquería.",
                )
        return cleaned_data

    def save(self, commit=True):
        user = super().save(commit=False)
        if self.cleaned_data["role"] == "CLIENT":
            user.is_client = True
            user.is_owner = False
        else:
            user.is_owner = True
            user.is_client = False

        if commit:
            user.save()
            if user.is_owner:
                # Crear peluquería asociada
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
