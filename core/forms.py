from django import forms
from django.utils import timezone
from django.forms import ValidationError
from django.contrib.auth.forms import (
    UserCreationForm,
    AuthenticationForm,
    PasswordChangeForm,
)
from .models import User, Hairdresser, Appointment, Service, WorkingHours


class UserProfileForm(forms.ModelForm):
    class Meta:
        model = User
        fields = ["username", "first_name", "last_name", "email"]


class ServiceForm(forms.ModelForm):
    name = forms.CharField(label="Nombre")
    description = forms.CharField(
        label="Descripción", required=False, widget=forms.Textarea(attrs={"rows": 3})
    )
    price = forms.DecimalField(label="Precio")
    duration_minutes = forms.IntegerField(label="Duración (minutos)")

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

    class Meta:
        model = User
        fields = (
            *(UserCreationForm._meta.fields or ()),
            "first_name",
            "last_name",
            "email",
            "is_owner",
        )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # Reorder fields to move is_owner after common fields
        field_order = [
            "username",
            "first_name",
            "last_name",
            "email",
            "password1",
            "password2",
            "is_owner",
        ]
        self.order_fields(field_order)

    def save(self, commit=True):
        user = super().save(commit=False)
        user.is_owner = self.cleaned_data.get("is_owner", False)

        if commit:
            user.save()
        return user


class AppointmentForm(forms.ModelForm):
    def __init__(self, *args, **kwargs):
        hairdresser = kwargs.pop("hairdresser", None)
        super().__init__(*args, **kwargs)

        # Update service queryset if hairdresser is provided
        if hairdresser:
            self.fields["service"].queryset = Service.objects.filter(  # type: ignore
                hairdresser=hairdresser
            )
        else:
            self.fields["service"].queryset = Service.objects.none()  # type: ignore

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


class HairdresserSetupForm(forms.ModelForm):
    class Meta:
        model = Hairdresser
        fields = [
            "name",
            "address",
            "phone_number",
            "description",
            "latitude",
            "longitude",
        ]
        widgets = {
            "latitude": forms.HiddenInput(),
            "longitude": forms.HiddenInput(),
        }


class WorkingHoursForm(forms.ModelForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["day_of_week"].widget.choices = WorkingHours.DAYS_OF_WEEK  # type: ignore
        self.fields["day_of_week"].initial = None

    class Meta:
        model = WorkingHours
        fields = ["day_of_week", "start_time", "end_time"]
        widgets = {
            "day_of_week": forms.Select(attrs={"class": "form-select"}),
            "start_time": forms.TimeInput(
                attrs={"type": "time", "class": "form-control"}
            ),
            "end_time": forms.TimeInput(
                attrs={"type": "time", "class": "form-control"}
            ),
        }


class BaseWorkingHoursFormSet(forms.BaseInlineFormSet):
    def clean(self):
        super().clean()
        # No continuar si hay errores de validación individuales (ej. desde model.clean())
        if any(self.errors):
            return
        schedules = []
        for form in self.forms:
            if not form.has_changed() or (
                self.can_delete and form.cleaned_data.get("DELETE")
            ):
                continue

            cleaned_data = form.cleaned_data
            start_time = cleaned_data.get("start_time")
            end_time = cleaned_data.get("end_time")
            day_of_week = cleaned_data.get("day_of_week")

            if not all([start_time, end_time, day_of_week is not None]):
                continue

            # Comprobar si este horario se superpone con alguno ya procesado en este envío.
            for day, start, end in schedules:
                if day == day_of_week:
                    if start_time < end and end_time > start:
                        # Este error se mostrará en `non_form_errors` del formset.
                        raise ValidationError("Los horarios no pueden superponerse.")

            schedules.append((day_of_week, start_time, end_time))


WorkingHoursFormSet = forms.inlineformset_factory(
    Hairdresser,
    WorkingHours,
    form=WorkingHoursForm,
    formset=BaseWorkingHoursFormSet,
    extra=0,
    can_delete=True,
)


class CustomPasswordChangeForm(PasswordChangeForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Modificar autocomplete para cada campo de contraseña
        self.fields["old_password"].widget.attrs["autocomplete"] = "current-password"
        self.fields["new_password1"].widget.attrs["autocomplete"] = "new-password"
        self.fields["new_password2"].widget.attrs["autocomplete"] = "new-password"
