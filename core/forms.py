from django import forms
from django.utils import timezone
from django.contrib.auth.forms import UserCreationForm, AuthenticationForm
from .models import User, Hairdresser, Appointment, Service


class ServiceForm(forms.ModelForm):
    class Meta:
        model = Service
        fields = ["name", "description", "price", "duration_minutes"]


class LoginForm(AuthenticationForm):
    pass


class SignUpForm(UserCreationForm):
    is_owner = forms.BooleanField(
        required=False,
        label="Soy dueño de una peluquería",
        help_text="Marca esta opción si deseas registrar tu peluquería",
    )

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
            "is_owner",
            "hairdresser_name",
            "hairdresser_address",
        )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["hairdresser_name"].widget.attrs["class"] = "hairdresser-field"
        self.fields["hairdresser_address"].widget.attrs["class"] = "hairdresser-field"
        
        # Reorder fields to move is_owner after common fields
        field_order = [
            "username",
            "first_name",
            "last_name",
            "email",
            "password1",
            "password2",
            "is_owner",
            "hairdresser_name",
            "hairdresser_address"
        ]
        self.order_fields(field_order)

    def clean(self):
        cleaned_data = super().clean()
        is_owner = cleaned_data.get("is_owner")
        if is_owner:
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
    def __init__(self, *args, **kwargs):
        hairdresser = kwargs.pop("hairdresser", None)
        super().__init__(*args, **kwargs)

        # Update service queryset if hairdresser is provided
        if hairdresser:
            self.fields["service"].queryset = Service.objects.filter(
                hairdresser=hairdresser
            )
        else:
            self.fields["service"].queryset = Service.objects.none()

        # Set minimum datetime
        now = timezone.now()
        self.fields["start_time"].widget.attrs["min"] = timezone.localtime(
            now
        ).strftime("%Y-%m-%dT%H:%M:%S")

    class Meta:
        model = Appointment
        fields = ["service", "start_time"]

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
