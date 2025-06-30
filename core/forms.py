from django import forms
from django.utils import timezone
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
        fields = ["name", "address", "phone_number", "description"]


class WorkingHoursForm(forms.ModelForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["day_of_week"].widget.choices = WorkingHours.DAYS_OF_WEEK  # type: ignore
        # Make day_of_week field initially empty
        self.fields["day_of_week"].initial = None

    def clean(self):
        # If the form is marked for deletion, skip validation entirely
        if self.cleaned_data.get("DELETE"):
            return self.cleaned_data

        cleaned_data = super().clean()

        # If either start_time or end_time is filled, both should be required
        start_time = cleaned_data.get("start_time")
        end_time = cleaned_data.get("end_time")

        if start_time and not end_time:
            self.add_error(
                "end_time",
                "Si especifica hora de inicio, debe especificar hora de fin.",
            )
        elif end_time and not start_time:
            self.add_error(
                "start_time",
                "Si especifica hora de fin, debe especificar hora de inicio.",
            )
        if self.cleaned_data.get("DELETE"):
            # Clear any errors that might have been added by super().clean()
            self._errors = {}
            return cleaned_data

        start_time = cleaned_data.get("start_time")
        end_time = cleaned_data.get("end_time")
        day_of_week = cleaned_data.get("day_of_week")

        if start_time and end_time and day_of_week:
            # Check for overlapping hours on the same day
            # Ensure self.instance exists and has a hairdresser
            hairdresser_instance = None
            if self.instance and hasattr(self.instance, "hairdresser"):
                hairdresser_instance = self.instance.hairdresser

            overlapping = WorkingHours.objects.filter(
                hairdresser=hairdresser_instance, day_of_week=day_of_week
            ).exclude(
                pk=self.instance.pk if self.instance and self.instance.pk else None
            )

            for schedule in overlapping:
                if start_time < schedule.end_time and end_time > schedule.start_time:
                    raise forms.ValidationError(
                        "Este horario se superpone con otro horario existente para el mismo día."
                    )

        return cleaned_data

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
    pass


WorkingHoursFormSet = forms.inlineformset_factory(
    Hairdresser,
    WorkingHours,
    form=WorkingHoursForm,
    formset=BaseWorkingHoursFormSet,
    extra=1,
    can_delete=True,
)


class CustomPasswordChangeForm(PasswordChangeForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Modificar autocomplete para cada campo de contraseña
        self.fields["old_password"].widget.attrs["autocomplete"] = "current-password"
        self.fields["new_password1"].widget.attrs["autocomplete"] = "new-password"
        self.fields["new_password2"].widget.attrs["autocomplete"] = "new-password"
