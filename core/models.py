from django.db import models
from django.contrib.auth.models import AbstractUser
from django.core.exceptions import ValidationError
from django.conf import settings
from decimal import Decimal
from core.fields import EncryptedCharField

# Create your models here.


class User(AbstractUser):
    """
    Modelo de Usuario personalizado.
    Hereda de AbstractUser para tener todos los campos de autenticación de Django.
    Roles simples con booleanos.
    """

    first_name = models.CharField("Nombre", max_length=150, blank=False)
    last_name = models.CharField("Apellido", max_length=150, blank=False)
    email = models.EmailField("Correo electrónico", blank=False)
    is_owner = models.BooleanField("owner status", default=False)

    def __str__(self):
        return self.username


class Hairdresser(models.Model):
    """
    Representa una peluquería.
    Vinculada 1-a-1 con un usuario que es 'dueño' (owner).
    """

    owner = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="hairdresser_profile",
    )
    name = models.CharField(max_length=100, verbose_name="Nombre")
    address = models.CharField(max_length=255, verbose_name="Dirección")
    phone_number = models.CharField(
        max_length=20, blank=True, verbose_name="Número de teléfono"
    )
    description = models.TextField(blank=True, verbose_name="Descripción")
    latitude = models.FloatField(blank=True, null=True, verbose_name="Latitud")
    longitude = models.FloatField(blank=True, null=True, verbose_name="Longitud")
    created_at = models.DateTimeField(auto_now_add=True)
    cover_image = models.ForeignKey(
        "HairdresserImage",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
        help_text="La imagen que se mostrará como principal",
    )
    mercadopago_active = models.BooleanField(
        default=False, verbose_name="Habilitar cobros digitales"
    )
    mercadopago_access_token = EncryptedCharField(
        max_length=512, blank=True, verbose_name="Token de acceso de MercadoPago"
    )
    mercadopago_refresh_token = EncryptedCharField(
        max_length=512, blank=True, verbose_name="Token de refresco de MercadoPago"
    )
    mercadopago_user_id = models.CharField(
        max_length=100, blank=True, verbose_name="ID de usuario de MercadoPago"
    )
    mercadopago_token_expires_at = models.DateTimeField(
        blank=True,
        null=True,
        verbose_name="Fecha de expiración del token de MercadoPago",
    )
    requires_deposit = models.BooleanField(
        default=False, verbose_name="Requerir seña obligatoria al reservar"
    )
    default_deposit_type = models.CharField(
        max_length=10,
        choices=[("FIXED", "Monto fijo"), ("PERCENTAGE", "Porcentaje")],
        default="FIXED",
        verbose_name="Tipo de seña por defecto",
    )
    default_deposit_value = models.DecimalField(
        max_digits=8,
        decimal_places=2,
        default=0.00,
        verbose_name="Valor de seña por defecto",
    )
    default_allow_prepayment = models.BooleanField(
        default=True,
        verbose_name="Permitir pago adelantado (100% online) por defecto",
    )
    default_allow_on_site_payment = models.BooleanField(
        default=True,
        verbose_name="Permitir pago en el local por defecto",
    )

    def clean(self):
        super().clean()
        if not self.default_allow_prepayment and not self.default_allow_on_site_payment:
            raise ValidationError(
                "Debe permitir al menos un medio de pago (pago adelantado o pago en el local)."
            )

        if self.mercadopago_active and not self.mercadopago_access_token:
            raise ValidationError(
                {
                    "mercadopago_access_token": "Debe ingresar el token de acceso para habilitar los cobros digitales."
                }
            )

        if self.default_deposit_value < 0:
            raise ValidationError(
                {"default_deposit_value": "El valor de la seña no puede ser negativo."}
            )
        if (
            self.default_deposit_type == "PERCENTAGE"
            and self.default_deposit_value > 100
        ):
            raise ValidationError(
                {
                    "default_deposit_value": "El porcentaje de la seña no puede superar el 100%."
                }
            )

    def __str__(self):
        return self.name

    def is_complete(self):
        """
        Verifica si el perfil de la peluquería está "completo" para aparecer en
        el home. Requiere nombre, dirección, latitud, longitud, al menos un
        horario y al menos un servicio
        """
        return all(
            [
                self.name,
                self.address,
                self.latitude,
                self.longitude,
                self.working_hours.exists(),  # type: ignore
                self.services.exists(),  # type: ignore
            ]
        )

    def average_rating(self):
        """Calcula la calificación promedio basada en todas las reseñas de sus
        servicios."""
        return (
            Review.objects.filter(appointment__service__hairdresser=self)
            .aggregate(avg_rating=models.Avg("rating"))
            .get("avg_rating")
            or 0
        )

    def review_count(self):
        """Cuuenta el número total de reseñas."""
        return Review.objects.filter(appointment__service__hairdresser=self).count()


class Service(models.Model):
    """
    Un servicio específico ofrecido por una peluquería (Hairdresser).
    """

    hairdresser = models.ForeignKey(
        Hairdresser, on_delete=models.CASCADE, related_name="services"
    )
    name = models.CharField(max_length=100)
    description = models.TextField(blank=True)
    price = models.DecimalField(max_digits=8, decimal_places=2)
    duration_minutes = models.PositiveIntegerField(help_text="Duración en minutos")
    override_deposit = models.BooleanField(
        default=False, verbose_name="Sobrescribir configuración de seña"
    )
    deposit_type = models.CharField(
        max_length=10,
        choices=[("FIXED", "Monto fijo"), ("PERCENTAGE", "Porcentaje")],
        default="FIXED",
        verbose_name="Tipo de seña específico",
    )
    deposit_value = models.DecimalField(
        max_digits=8,
        decimal_places=2,
        default=0.00,
        verbose_name="Valor de seña específico",
    )
    override_payment_modes = models.BooleanField(
        default=False, verbose_name="Sobrescribir formas de pago"
    )
    allow_prepayment = models.BooleanField(
        default=True, verbose_name="Permitir pago adelantado (100% online)"
    )
    allow_on_site_payment = models.BooleanField(
        default=True, verbose_name="Permitir pago en el local"
    )

    def clean(self):
        super().clean()
        if self.override_payment_modes:
            if not self.allow_prepayment and not self.allow_on_site_payment:
                raise ValidationError(
                    {
                        "override_payment_modes": "Debe permitir al menos un medio de pago si sobrescribe las formas de pago."
                    }
                )
        if self.override_deposit:
            if self.deposit_value < 0:
                raise ValidationError(
                    {"deposit_value": "El valor de la seña no puede ser negativo."}
                )
            if self.deposit_type == "PERCENTAGE" and self.deposit_value > 100:
                raise ValidationError(
                    {
                        "deposit_value": "El porcentaje de la seña no puede superar el 100%."
                    }
                )

    def get_required_deposit_amount(self):
        if (
            not self.hairdresser.requires_deposit
            or not self.hairdresser.mercadopago_active
        ):
            return Decimal("0.00")

        if self.override_deposit:
            dep_type = self.deposit_type
            dep_val = self.deposit_value
        else:
            dep_type = self.hairdresser.default_deposit_type
            dep_val = self.hairdresser.default_deposit_value

        if not dep_val:
            return Decimal("0.00")

        if dep_type == "PERCENTAGE":
            return (self.price * (dep_val / Decimal("100.00"))).quantize(
                Decimal("0.01")
            )
        else:
            return dep_val.quantize(Decimal("0.01"))

    @property
    def required_deposit_amount(self):
        return self.get_required_deposit_amount()

    def get_payment_modes(self):
        if not self.hairdresser.mercadopago_active:
            return {
                "allow_prepayment": False,
                "allow_on_site_payment": True,
            }
        if self.override_payment_modes:
            return {
                "allow_prepayment": self.allow_prepayment,
                "allow_on_site_payment": self.allow_on_site_payment,
            }
        else:
            return {
                "allow_prepayment": self.hairdresser.default_allow_prepayment,
                "allow_on_site_payment": self.hairdresser.default_allow_on_site_payment,
            }

    @property
    def payment_modes(self):
        return self.get_payment_modes()

    def __str__(self):
        return f"{self.name} - {self.hairdresser.name}"

    def average_rating(self):
        """Calcula la calificación promedio para este servicio específico."""
        # Usamos la relación inversa 'appointments' y luego 'review'
        # El doble guion bajo __ permite atravesar relaciones.
        avg = self.appointments.aggregate(avg_rating=models.Avg("review__rating")).get(  # type: ignore
            "avg_rating"
        )

        return avg or 0

    def review_count(self):
        """Cuenta el número de reseñas para este servicio."""
        return self.appointments.filter(review__isnull=False).count()  # type: ignore


class Appointment(models.Model):
    """
    Un turno reservado por un cliente para un servicio específico.
    """

    STATUS_CHOICES = [
        ("PENDING", "Pendiente"),
        ("CONFIRMED", "Confirmado"),
        ("COMPLETED", "Completado"),
        ("CANCELLED", "Cancelado"),
        ("NO_SHOW", "No se presentó"),
    ]
    client = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,  # Si el cliente se borra, no borrar el turno
        null=True,
        related_name="appointments",
    )
    service = models.ForeignKey(
        Service, on_delete=models.CASCADE, related_name="appointments"
    )
    start_time = models.DateTimeField()
    end_time = models.DateTimeField(editable=False)  # Se autocalculará
    amount = models.DecimalField(
        max_digits=8,
        decimal_places=2,
        help_text="El precio del servicio en el momento de la reserva",
    )
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default="PENDING")
    created_at = models.DateTimeField(auto_now_add=True)
    payment_method = models.CharField(
        max_length=10,
        choices=[
            ("CASH", "Pago en el local / Saldo en el local"),
            ("FULL", "Pago completo adelantado"),
        ],
        default="CASH",
        verbose_name="Método de pago",
    )
    amount_paid = models.DecimalField(
        max_digits=8,
        decimal_places=2,
        default=0.00,
        verbose_name="Monto pagado",
    )
    expires_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name="Expira en",
        help_text="Para turnos PENDING con pago digital pendiente: fecha/hora límite para completar el pago antes de que se libere el slot.",
    )
    mercadopago_payment_id = models.CharField(
        max_length=100,
        blank=True,
        null=True,
        verbose_name="ID de pago de MercadoPago",
        help_text="ID del pago en MercadoPago para procesar reembolsos",
    )

    def get_required_deposit_amount(self):
        if (
            not self.service.hairdresser.requires_deposit
            or not self.service.hairdresser.mercadopago_active
        ):
            return Decimal("0.00")

        if self.service.override_deposit:
            dep_type = self.service.deposit_type
            dep_val = self.service.deposit_value
        else:
            dep_type = self.service.hairdresser.default_deposit_type
            dep_val = self.service.hairdresser.default_deposit_value

        if not dep_val:
            return Decimal("0.00")

        price = self.amount if self.amount is not None else self.service.price

        if dep_type == "PERCENTAGE":
            return (price * (dep_val / Decimal("100.00"))).quantize(Decimal("0.01"))
        else:  # FIXED
            return dep_val.quantize(Decimal("0.01"))

    def get_expected_payment_amount(self):
        """
        Retorna el monto exacto que se espera cobrar digitalmente por este turno.
        Si es FULL (pago completo), es self.amount (o self.service.price si self.amount es None).
        Si es CASH, es el depósito/seña requerido.
        """
        if self.payment_method == "FULL":
            return self.amount if self.amount is not None else self.service.price
        return self.get_required_deposit_amount()

    def get_payment_modes(self):
        if not self.service.hairdresser.mercadopago_active:
            return {
                "allow_prepayment": False,
                "allow_on_site_payment": True,
            }
        if self.service.override_payment_modes:
            return {
                "allow_prepayment": self.service.allow_prepayment,
                "allow_on_site_payment": self.service.allow_on_site_payment,
            }
        else:
            return {
                "allow_prepayment": self.service.hairdresser.default_allow_prepayment,
                "allow_on_site_payment": self.service.hairdresser.default_allow_on_site_payment,
            }

    def save(self, *args, **kwargs):
        # Lógica para autocalcular end_time
        from datetime import timedelta

        self.end_time = self.start_time + timedelta(
            minutes=self.service.duration_minutes
        )

        is_new = self.pk is None
        is_cancelled = False
        is_just_confirmed = False

        if self.pk:
            try:
                old_instance = Appointment.objects.get(pk=self.pk)
                if old_instance.status != "CANCELLED" and self.status == "CANCELLED":
                    is_cancelled = True
                # Detectar transición a CONFIRMED desde cualquier otro estado
                if old_instance.status != "CONFIRMED" and self.status == "CONFIRMED":
                    is_just_confirmed = True
            except Appointment.DoesNotExist:
                pass

        if is_new:
            # Si el turno es nuevo congelamos el precio.
            self.amount = self.service.price

        super().save(*args, **kwargs)

        # Enviar notificaciones después de guardar exitosamente
        from core.utils import notify_user

        # Notificaciones de confirmación: solo cuando el turno pasa a CONFIRMED.
        # - Si el turno fue creado directamente como CONFIRMED (pago en el local sin seña),
        #   is_new=True y is_just_confirmed=False, pero el status ya es CONFIRMED.
        # - Si el turno fue creado como PENDING y luego se confirma vía webhook/fallback,
        #   is_just_confirmed=True.
        # Usamos una condición unificada: notificar si es nuevo y ya CONFIRMED,
        # O si acaba de transicionar a CONFIRMED.
        should_notify_confirmed = (
            is_new and self.status == "CONFIRMED"
        ) or is_just_confirmed

        # Solicitud de turno pendiente de confirmación manual por el dueño
        # (PENDING sin expires_at = no requiere pago online, el dueño confirma manualmente).
        is_pending_request = is_new and self.status == "PENDING" and not self.expires_at

        if should_notify_confirmed:
            if self.client:
                notify_user(
                    user=self.client,
                    event_type="APPOINTMENT_SUCCESS_CLIENT",
                    context={"appointment": self},
                    subject="Confirmación de Turno - Stilo",
                )
            owner = self.service.hairdresser.owner
            if owner:
                notify_user(
                    user=owner,
                    event_type="APPOINTMENT_SUCCESS_OWNER",
                    context={"appointment": self},
                    subject="Nueva Reserva Recibida - Stilo",
                )
        elif is_pending_request:
            if self.client:
                notify_user(
                    user=self.client,
                    event_type="APPOINTMENT_REQUEST_CLIENT",
                    context={"appointment": self},
                    subject="Solicitud de Turno Recibida - Stilo",
                )
            owner = self.service.hairdresser.owner
            if owner:
                notify_user(
                    user=owner,
                    event_type="APPOINTMENT_REQUEST_OWNER",
                    context={"appointment": self},
                    subject="Nueva Solicitud de Turno - Stilo",
                )
        elif is_cancelled:
            if self.client:
                notify_user(
                    user=self.client,
                    event_type="APPOINTMENT_CANCELLED_CLIENT",
                    context={"appointment": self},
                    subject="Turno Cancelado - Stilo",
                )
            owner = self.service.hairdresser.owner
            if owner:
                notify_user(
                    user=owner,
                    event_type="APPOINTMENT_CANCELLED_OWNER",
                    context={"appointment": self},
                    subject="Reserva Cancelada - Stilo",
                )

    def get_payment_status_info(self):
        """
        Devuelve un dict con la información de pago para mostrar en la UI:
        - label: texto legible
        - badge_class: clase CSS de Bootstrap para el badge
        - icon: clase de icono Bootstrap Icons
        - detail: texto adicional con montos (opcional)
        """
        amount_paid = self.amount_paid or Decimal("0.00")
        deposit_required = self.get_required_deposit_amount()

        if self.payment_method == "FULL":
            if amount_paid >= self.amount:
                return {
                    "label": "Pagado",
                    "badge_class": "bg-success",
                    "icon": "bi-check-circle-fill",
                    "detail": f"${self.amount}",
                }
            else:
                return {
                    "label": "Pendiente de pago",
                    "badge_class": "bg-warning text-dark",
                    "icon": "bi-clock-fill",
                    "detail": f"${self.amount}",
                }
        else:  # CASH
            if deposit_required > 0:
                if amount_paid >= deposit_required:
                    remaining = self.amount - amount_paid
                    return {
                        "label": "Señado",
                        "badge_class": "bg-info text-dark",
                        "icon": "bi-cash-stack",
                        "detail": f"Seña ${amount_paid} — Resta ${remaining} en el local",
                    }
                else:
                    return {
                        "label": "Pendiente de seña",
                        "badge_class": "bg-warning text-dark",
                        "icon": "bi-clock-fill",
                        "detail": f"Seña requerida: ${deposit_required}",
                    }
            else:
                return {
                    "label": "Se paga en el local",
                    "badge_class": "bg-secondary",
                    "icon": "bi-shop",
                    "detail": f"${self.amount}",
                }

    def get_payment_summary(self):
        """
        Devuelve un resumen conciso del estado de pago para mostrar en notificaciones.
        """

        def format_curr(val):
            if val == int(val):
                return f"${int(val)}"
            return f"${val:.2f}".replace(".", ",")

        amount_paid = self.amount_paid or Decimal("0.00")
        deposit_required = self.get_required_deposit_amount()

        if self.payment_method == "FULL":
            if amount_paid >= self.amount:
                return f"Pagado online ({format_curr(self.amount)})"
            else:
                return f"Pago online pendiente ({format_curr(self.amount)})"
        else:  # CASH
            if deposit_required > 0:
                if amount_paid >= deposit_required:
                    remaining = self.amount - amount_paid
                    return f"Seña de {format_curr(amount_paid)} pagada (Resta {format_curr(remaining)} en el local)"
                else:
                    return f"Seña pendiente de {format_curr(deposit_required)} (Total: {format_curr(self.amount)})"
            else:
                return f"En el local ({format_curr(self.amount)})"

    def __str__(self):
        return f"Turno para {self.client} en {self.service.hairdresser.name} a las {self.start_time.strftime('%Y-%m-%d %H:%M')}"


class Review(models.Model):
    """
    Una reseña dejada por un cliente sobre una peluquería.
    """

    appointment = models.OneToOneField(
        Appointment, on_delete=models.CASCADE, related_name="review"
    )
    rating = models.PositiveIntegerField(choices=[(i, str(i)) for i in range(1, 6)])
    comment = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Reseña de {self.rating} estrellas para {self.appointment.service.hairdresser.name}"


class HairdresserImage(models.Model):
    """
    Imágenes para la galería de una peluquería.
    """

    hairdresser = models.ForeignKey(
        Hairdresser, on_delete=models.CASCADE, related_name="images"
    )
    image = models.ImageField(upload_to="hairdressers/")
    caption = models.CharField(max_length=150, blank=True)

    def __str__(self):
        return f"Imagen para {self.hairdresser.name}"


class Offer(models.Model):
    """
    Ofertas o promociones especiales de una peluquería.
    """

    hairdresser = models.ForeignKey(
        Hairdresser, on_delete=models.CASCADE, related_name="offers"
    )
    title = models.CharField(max_length=100)
    description = models.TextField()
    discount_percentage = models.DecimalField(
        max_digits=5, decimal_places=2, null=True, blank=True
    )
    start_date = models.DateField()
    end_date = models.DateField()
    is_active = models.BooleanField(default=True)

    def __str__(self):
        return f"{self.title} ({self.discount_percentage}%)"


class WorkingHours(models.Model):
    """
    Horario de trabajo semanal de una peluquería.
    Permite definir múltiples franjas horarias por día.
    """

    DAYS_OF_WEEK = [
        (0, "Lunes"),
        (1, "Martes"),
        (2, "Miércoles"),
        (3, "Jueves"),
        (4, "Viernes"),
        (5, "Sábado"),
        (6, "Domingo"),
    ]

    hairdresser = models.ForeignKey(
        Hairdresser, on_delete=models.CASCADE, related_name="working_hours"
    )
    day_of_week = models.IntegerField(
        verbose_name="Día de la semana",
        choices=DAYS_OF_WEEK,
        help_text="Día de la semana (0=Lunes, 6=Domingo)",
    )
    start_time = models.TimeField(help_text="Hora de apertura de esta franja horaria")
    end_time = models.TimeField(help_text="Hora de cierre de esta franja horaria")

    class Meta:
        ordering = ["day_of_week", "start_time"]
        # Asegura que no haya superposición de horarios para el mismo día
        constraints = [
            models.CheckConstraint(
                check=models.Q(start_time__lt=models.F("end_time")),
                name="valid_working_hours_range",
            )
        ]

    def clean(self):
        super().clean()

        # 0. Campos obligatorios
        if self.day_of_week is None or self.start_time is None or self.end_time is None:
            return

        # 1. Validación básica de la franja horaria
        if self.start_time >= self.end_time:
            raise ValidationError(
                {"end_time": "La hora de fin debe ser posterior a la hora de inicio."}
            )

        # 2. Validación de superposición con horarios existentes en la BD
        # Asegurarse de que tenemos los datos necesarios para la consulta
        if self.hairdresser is None:
            return

        # Construir la consulta base para buscar superposiciones
        overlapping_hours = WorkingHours.objects.filter(
            hairdresser=self.hairdresser,
            day_of_week=self.day_of_week,
            # Lógica de superposición: (StartA < EndB) y (EndA > StartB)
            start_time__lt=self.end_time,
            end_time__gt=self.start_time,
        )

        # Si estamos actualizando un objeto existente, debemos excluirlo de la comprobación
        if self.pk:
            overlapping_hours = overlapping_hours.exclude(pk=self.pk)

        if overlapping_hours.exists():
            # Este error se asociará con el formulario que representa este modelo.
            raise ValidationError(
                "Este horario se superpone con otro ya existente para el mismo día.",
                code="overlap_existing",
            )

    def __str__(self):
        days = dict(self.DAYS_OF_WEEK)
        return f"{days.get(self.day_of_week, 'Día inválido')}: {self.start_time.strftime('%H:%M')} - {self.end_time.strftime('%H:%M')}"


class PushSubscription(models.Model):
    """
    Guarda la información de suscripción de notificaciones push de un dispositivo del usuario.
    """

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="push_subscriptions",
    )
    endpoint = models.TextField(verbose_name="Endpoint")
    auth = models.CharField(max_length=255, verbose_name="Auth")
    p256dh = models.CharField(max_length=255, verbose_name="P256dh")
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Suscripción de {self.user.username} ({self.id})"


class WebhookEvent(models.Model):
    """
    Registra los eventos de webhook de MercadoPago para asegurar la idempotencia.
    """

    payment_id = models.CharField(max_length=100, unique=True, verbose_name="ID de pago")
    mp_request_id = models.CharField(
        max_length=100,
        null=True,
        blank=True,
        verbose_name="ID de request de MercadoPago",
    )
    received_at = models.DateTimeField(auto_now_add=True, verbose_name="Fecha de recepción")
    processed = models.BooleanField(default=False, verbose_name="Procesado con éxito")

    def __str__(self):
        return f"WebhookEvent(payment_id={self.payment_id}, processed={self.processed})"


class PendingRefund(models.Model):
    appointment = models.OneToOneField(
        'Appointment',
        on_delete=models.CASCADE,
        related_name="pending_refund",
        verbose_name="Turno"
    )
    payment_id = models.CharField(max_length=100, verbose_name="ID de pago de MercadoPago")
    amount = models.DecimalField(max_digits=10, decimal_places=2, verbose_name="Monto a reembolsar")
    attempts = models.PositiveIntegerField(default=0, verbose_name="Intentos de reembolso")
    last_error = models.TextField(blank=True, null=True, verbose_name="Último error")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Creado el")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="Actualizado el")

    class Meta:
        verbose_name = "Reembolso pendiente"
        verbose_name_plural = "Reembolsos pendientes"

    def __str__(self):
        return f"Reembolso pendiente para Turno #{self.appointment_id} - Pago: {self.payment_id}"


class PaymentTransaction(models.Model):
    """
    Guarda el registro de auditoría inmutable de cada transacción de pago exitosa o fallida.
    """
    appointment = models.ForeignKey(
        Appointment,
        on_delete=models.PROTECT,
        related_name="transactions",
        verbose_name="Turno"
    )
    payment_id = models.CharField(
        max_length=100,
        unique=True,
        verbose_name="ID de pago de MercadoPago"
    )
    amount = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        verbose_name="Monto transaccionado"
    )
    status = models.CharField(
        max_length=50,
        verbose_name="Estado del pago"
    )
    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name="Fecha de creación"
    )

    class Meta:
        verbose_name = "Transacción de pago"
        verbose_name_plural = "Transacciones de pago"

    def delete(self, *args, **kwargs):
        raise ValidationError("Las transacciones de pago son registros de auditoría inmutables.")

    def __str__(self):
        return f"Transacción #{self.id} - Turno #{self.appointment_id} - Pago: {self.payment_id} - Estado: {self.status}"


