from django import forms
from django.utils import timezone
from django.forms import ValidationError
from django.contrib.auth.forms import (
    UserCreationForm,
    AuthenticationForm,
    PasswordChangeForm,
)
from .models import (
    HairdresserImage,
    User,
    Hairdresser,
    Appointment,
    Service,
    WorkingHours,
    Review,
)
from datetime import timedelta
from decimal import Decimal


class UserProfileForm(forms.ModelForm):
    class Meta:
        model = User
        fields = ["username", "first_name", "last_name", "email"]


class ReviewForm(forms.ModelForm):
    rating = forms.ChoiceField(
        choices=[(i, str(i)) for i in range(5, 0, -1)],
        widget=forms.RadioSelect,
        label="Calificación",
        required=True,
    )

    class Meta:
        model = Review
        fields = [
            "rating",
            "comment",
        ]
        widgets = {
            "comment": forms.Textarea(attrs={"rows": 4, "id": "id_review_comment"}),
        }
        labels = {"comment": "Comentario (opcional)"}


class ServiceForm(forms.ModelForm):
    name = forms.CharField(label="Nombre")
    description = forms.CharField(
        label="Descripción", required=False, widget=forms.Textarea(attrs={"rows": 3})
    )
    price = forms.DecimalField(label="Precio", min_value=Decimal('0.00'))
    duration_minutes = forms.IntegerField(label="Duración (minutos)", min_value=1)

    def __init__(self, *args, **kwargs):
        self.hairdresser = kwargs.pop("hairdresser", None)
        super().__init__(*args, **kwargs)
        if not self.hairdresser and self.instance and hasattr(self.instance, "hairdresser") and self.instance.hairdresser:
            self.hairdresser = self.instance.hairdresser

    def clean_duration_minutes(self):
        duration = self.cleaned_data.get("duration_minutes")
        if duration:
            slot_dur = 15
            if self.hairdresser:
                slot_dur = self.hairdresser.slot_duration
            elif self.instance and hasattr(self.instance, "hairdresser") and self.instance.hairdresser:
                slot_dur = self.instance.hairdresser.slot_duration
                
            if duration % slot_dur != 0:
                raise forms.ValidationError(
                    f"La duración del servicio debe ser un múltiplo de {slot_dur} minutos (ej. {slot_dur}, {slot_dur * 2}, {slot_dur * 3})."
                )
        return duration

    class Meta:
        model = Service
        fields = [
            "name",
            "description",
            "price",
            "duration_minutes",
            "override_deposit",
            "deposit_type",
            "deposit_value",
            "override_payment_modes",
            "allow_prepayment",
            "allow_on_site_payment",
        ]

    def clean(self):
        cleaned_data = super().clean()
        override_deposit = cleaned_data.get("override_deposit")
        deposit_type = cleaned_data.get("deposit_type")
        deposit_value = cleaned_data.get("deposit_value")
        override_payment_modes = cleaned_data.get("override_payment_modes")
        allow_prepayment = cleaned_data.get("allow_prepayment")
        allow_on_site_payment = cleaned_data.get("allow_on_site_payment")

        if override_payment_modes:
            if not allow_prepayment and not allow_on_site_payment:
                self.add_error(
                    "override_payment_modes",
                    "Debe permitir al menos el pago adelantado o el pago en el local si sobrescribe las formas de pago.",
                )

        if override_deposit:
            if deposit_value is not None:
                if deposit_value < 0:
                    self.add_error(
                        "deposit_value", "El valor de la seña no puede ser negativo."
                    )
                if deposit_type == "PERCENTAGE" and deposit_value > 100:
                    self.add_error(
                        "deposit_value",
                        "El porcentaje de la seña no puede superar el 100%.",
                    )

        return cleaned_data


class HairdresserImageForm(forms.ModelForm):
    class Meta:
        model = HairdresserImage
        fields = ["image", "caption"]
        labels = {"image": "Archivo de imagen", "caption": "Descripción (opcional)"}


class HairdresserImageUpdateForm(forms.ModelForm):
    class Meta:
        model = HairdresserImage
        fields = ["caption"]
        labels = {"caption": "Descripción"}
        widgets = {"caption": forms.Textarea(attrs={"rows": 2})}


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
        self.hairdresser = hairdresser

        if hairdresser:
            self.fields["service"].queryset = Service.objects.filter(  # type: ignore
                hairdresser=hairdresser
            )
        else:
            self.fields["service"].queryset = Service.objects.none()  # type: ignore

        # Los campos se poblarán con JS, por lo que los ocultamos.
        self.fields["service"].widget = forms.HiddenInput()
        self.fields["start_time"].widget = forms.HiddenInput()
        self.fields["payment_method"].widget = forms.HiddenInput()

    class Meta:
        model = Appointment
        fields = ["service", "start_time", "payment_method"]

    def clean_start_time(self):
        """
        Valida que la fecha y hora del turno no sea en el pasado.
        """
        start_time = self.cleaned_data.get("start_time")
        if start_time:
            if start_time <= timezone.now():
                raise forms.ValidationError(
                    "No puedes reservar un turno en el pasado. Por favor, elige una fecha y hora futura.",
                    code="past_date",
                )
            
            slot_dur = 15
            if self.hairdresser:
                slot_dur = self.hairdresser.slot_duration
            elif self.instance and self.instance.pk and self.instance.service:
                slot_dur = self.instance.service.hairdresser.slot_duration

            if start_time.minute % slot_dur != 0:
                raise forms.ValidationError(
                    f"El turno debe comenzar en un múltiplo de {slot_dur} minutos.",
                    code="invalid_grid_time",
                )
        return start_time

    def clean(self):
        cleaned_data = super().clean()
        start_time = cleaned_data.get("start_time")
        service = cleaned_data.get("service")

        if not start_time or not service:
            return cleaned_data

        end_time = start_time + timedelta(minutes=service.duration_minutes)
        hairdresser = service.hairdresser

        # 1. Validar que el turno cabe dentro de un horario de trabajo
        valid_slot_exists = WorkingHours.objects.filter(
            hairdresser=hairdresser,
            day_of_week=start_time.weekday(),
            start_time__lte=start_time.time(),
            end_time__gte=end_time.time(),
        ).exists()

        if not valid_slot_exists:
            raise ValidationError(
                "El servicio excede el horario de atención para el día seleccionado.",
                code="outside_working_hours",
            )

        # 2. Comprobar si hay turnos que se superponen.
        # Se consideran como "ocupados" los turnos CONFIRMED, los PENDING
        # que no tienen expires_at (= solicitudes esperando confirmación del dueño),
        # y los PENDING con expires_at que aún no han expirado.
        from django.db.models import Q

        # Validar si el turno se superpone con alguna pausa del peluquero
        from core.models import Pause
        overlapping_pauses = Pause.objects.filter(
            hairdresser=hairdresser,
            start_time__lt=end_time,
            end_time__gt=start_time,
        )
        if overlapping_pauses.exists():
            raise ValidationError(
                "Este horario no está disponible por el momento.",
                code="overlap_pause",
            )

        overlapping_appointments = Appointment.objects.filter(
            service__hairdresser=hairdresser,
            start_time__lt=end_time,
            end_time__gt=start_time,
        ).filter(
            Q(status="CONFIRMED")
            | Q(status="PENDING", expires_at__isnull=True)
            | Q(status="PENDING", expires_at__gt=timezone.now())
        )

        if overlapping_appointments.exists():
            raise ValidationError(
                "El horario seleccionado ya no está disponible. Por favor, elija otro.",
                code="overlap",
            )

        # 3. Validar método de pago
        payment_method = cleaned_data.get("payment_method")
        if payment_method:
            temp_app = Appointment(service=service)
            modes = temp_app.get_payment_modes()
            if payment_method == "FULL" and not modes["allow_prepayment"]:
                raise ValidationError(
                    "El pago completo por adelantado no está disponible para este servicio.",
                    code="prepayment_disabled",
                )
            if payment_method == "CASH" and not modes["allow_on_site_payment"]:
                raise ValidationError(
                    "El pago en el local no está disponible para este servicio. Debe abonar el 100% online.",
                    code="cash_disabled",
                )

        return cleaned_data


class HairdresserSetupForm(forms.ModelForm):
    class Meta:
        model = Hairdresser
        fields = [
            "name",
            "address",
            "phone_number",
            "description",
            "mercadopago_active",
            "requires_deposit",
            "default_deposit_type",
            "default_deposit_value",
            "default_allow_prepayment",
            "default_allow_on_site_payment",
            "latitude",
            "longitude",
            "slot_duration",
        ]
        widgets = {
            "latitude": forms.HiddenInput(),
            "longitude": forms.HiddenInput(),
        }

    def clean(self):
        cleaned_data = super().clean()
        mercadopago_active = cleaned_data.get("mercadopago_active")
        requires_deposit = cleaned_data.get("requires_deposit")
        default_deposit_type = cleaned_data.get("default_deposit_type")
        default_deposit_value = cleaned_data.get("default_deposit_value")
        default_allow_prepayment = cleaned_data.get("default_allow_prepayment")
        default_allow_on_site_payment = cleaned_data.get(
            "default_allow_on_site_payment"
        )
        slot_duration = cleaned_data.get("slot_duration")

        if not default_allow_prepayment and not default_allow_on_site_payment:
            self.add_error(
                "default_allow_prepayment",
                "Debe permitir al menos un medio de pago (pago adelantado o pago en el local).",
            )

        if mercadopago_active:
            token_exists = self.instance and getattr(
                self.instance, "mercadopago_access_token", None
            )
            if not token_exists:
                self.add_error(
                    "mercadopago_active",
                    "Debes vincular tu cuenta de MercadoPago antes de activar los cobros digitales.",
                )

        if requires_deposit:
            if default_deposit_value is not None:
                if default_deposit_value < 0:
                    self.add_error(
                        "default_deposit_value",
                        "El valor de la seña no puede ser negativo.",
                    )
                if default_deposit_type == "PERCENTAGE" and default_deposit_value > 100:
                    self.add_error(
                        "default_deposit_value",
                        "El porcentaje de la seña no puede superar el 100%.",
                    )

        if slot_duration and self.instance and self.instance.pk:
            incompatible_services = self.instance.services.all()
            incompatibles = [
                s.name for s in incompatible_services if s.duration_minutes % slot_duration != 0
            ]
            if incompatibles:
                services_str = ", ".join(incompatibles)
                self.add_error(
                    "slot_duration",
                    f"No puedes cambiar la duración del slot a {slot_duration} minutos porque tienes servicios con duraciones incompatibles: {services_str}. Por favor, edita tus servicios primero."
                )

        return cleaned_data


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
                self.can_delete and form.cleaned_data.get("DELETE")  # type: ignore
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


class WalkInAppointmentForm(forms.ModelForm):
    client_name = forms.CharField(
        label="Nombre del cliente",
        required=True,
        widget=forms.TextInput(attrs={"class": "form-control", "placeholder": "Ej. Juan Pérez"})
    )
    date = forms.DateField(
        label="Fecha",
        required=True,
        widget=forms.DateInput(attrs={"type": "date", "class": "form-control"})
    )
    start_time_only = forms.TimeField(
        label="Hora de inicio",
        required=True,
        widget=forms.TimeInput(attrs={"type": "time", "class": "form-control"})
    )

    class Meta:
        model = Appointment
        fields = ["service", "client_name"]

    def __init__(self, *args, **kwargs):
        hairdresser = kwargs.pop("hairdresser", None)
        super().__init__(*args, **kwargs)
        if hairdresser:
            self.fields["service"].queryset = Service.objects.filter(hairdresser=hairdresser)
            self.fields["service"].widget.attrs.update({"class": "form-select"})
        else:
            self.fields["service"].queryset = Service.objects.none()

    def clean_service(self):
        service = self.cleaned_data.get("service")
        if not service:
            raise ValidationError("Debe seleccionar un servicio.")
        return service

    def clean(self):
        cleaned_data = super().clean()
        service = cleaned_data.get("service")
        date = cleaned_data.get("date")
        start_time_only = cleaned_data.get("start_time_only")

        if service and date and start_time_only:
            from django.utils import timezone
            from django.db.models import Q
            import datetime

            # Combinar fecha y hora
            naive_datetime = datetime.datetime.combine(date, start_time_only)
            start_time = timezone.make_aware(naive_datetime, timezone.get_current_timezone())
            cleaned_data["start_time"] = start_time

            # Validar que no sea anterior a hoy
            today = timezone.localtime(timezone.now()).date()
            if date < today:
                self.add_error("date", "No puedes registrar un turno en un día anterior al de hoy.")

            # Validar rango del turno
            end_time = start_time + datetime.timedelta(minutes=service.duration_minutes)

            # 1. Validar que el turno cabe dentro de un horario de trabajo
            valid_slot_exists = WorkingHours.objects.filter(
                hairdresser=service.hairdresser,
                day_of_week=start_time.weekday(),
                start_time__lte=start_time.time(),
                end_time__gte=end_time.time(),
            ).exists()

            if not valid_slot_exists:
                raise ValidationError("El servicio excede el horario de atención para el día seleccionado.")

            # 2. Comprobar si hay turnos que se superponen
            # Validar si el turno se superpone con alguna pausa del peluquero
            from core.models import Pause
            overlapping_pauses = Pause.objects.filter(
                hairdresser=service.hairdresser,
                start_time__lt=end_time,
                end_time__gt=start_time,
            )
            if overlapping_pauses.exists():
                raise ValidationError("Este horario no está disponible por el momento.")

            overlapping_appointments = Appointment.objects.filter(
                service__hairdresser=service.hairdresser,
                start_time__lt=end_time,
                end_time__gt=start_time,
            ).filter(
                Q(status="CONFIRMED")
                | Q(status="PENDING", expires_at__isnull=True)
                | Q(status="PENDING", expires_at__gt=timezone.now())
            )

            if overlapping_appointments.exists():
                raise ValidationError("El horario seleccionado ya no está disponible. Por favor, elija otro.")

        return cleaned_data
