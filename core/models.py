from django.db import models
from django.contrib.auth.models import AbstractUser
from django.conf import settings

# Create your models here.


class User(AbstractUser):
    """
    Modelo de Usuario personalizado.
    Hereda de AbstractUser para tener todos los campos de autenticación de Django.
    Roles simples con booleanos.
    """

    is_client = models.BooleanField("client status", default=False)
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
    name = models.CharField(max_length=100)
    address = models.CharField(max_length=255)
    phone_number = models.CharField(max_length=20, blank=True)
    description = models.TextField(blank=True)
    latitude = models.FloatField(blank=True, null=True)
    longitude = models.FloatField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name


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
