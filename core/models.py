from django.db import models
from django.contrib.auth.models import AbstractUser
from django.core.exceptions import ValidationError
from django.conf import settings

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
        help_text="La imagen que se mostrará como principal.",
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

    def __str__(self):
        return f"{self.name} - {self.hairdresser.name}"


class Appointment(models.Model):
    """
    Un turno reservado por un cliente para un servicio específico.
    """

    STATUS_CHOICES = [
        ("PENDING", "Pendiente"),
        ("CONFIRMED", "Confirmado"),
        ("COMPLETED", "Completado"),
        ("CANCELLED", "Cancelado"),
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
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default="PENDING")
    created_at = models.DateTimeField(auto_now_add=True)

    def save(self, *args, **kwargs):
        # Lógica para autocalcular end_time
        from datetime import timedelta

        self.end_time = self.start_time + timedelta(
            minutes=self.service.duration_minutes
        )
        super().save(*args, **kwargs)

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
