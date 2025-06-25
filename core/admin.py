from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from .models import (
    User,
    Hairdresser,
    Service,
    Appointment,
    Review,
    HairdresserImage,
    Offer,
    WorkingHours,
)

# Register your models here.


class CustomUserAdmin(UserAdmin):
    """
    Extiende el UserAdmin para mostrar nuestros campos personalizados.
    """

    # Añade los campos personalizados a la vista de lista
    list_display = (
        "username",
        "email",
        "first_name",
        "last_name",
        "is_staff",
        "is_client",
        "is_owner",
    )

    # Añade los campos a los fieldsets para poder editarlos
    # Copiamos los fieldsets originales y añadimos el nuestro
    fieldsets = list(UserAdmin.fieldsets) + [
        ("Roles", {"fields": ("is_client", "is_owner")}),
    ]
    add_fieldsets = list(UserAdmin.add_fieldsets) + [
        ("Roles", {"fields": ("is_client", "is_owner")}),
    ]


class ServiceInline(admin.TabularInline):
    """Permite editar servicios directamente desde la vista de la peluquería."""

    model = Service
    extra = 1  # Muestra un formulario para un nuevo servicio por defecto


class HairdresserImageInline(admin.TabularInline):
    """Permite subir imágenes directamente desde la vista de la peluquería."""

    model = HairdresserImage
    extra = 1


class WorkingHoursInline(admin.TabularInline):
    """Permite editar los horarios directamente desde la vista de la peluquería."""
    model = WorkingHours
    extra = 1
    ordering = ['day_of_week', 'start_time']


@admin.register(Hairdresser)
class HairdresserAdmin(admin.ModelAdmin):
    list_display = ("name", "owner", "address", "phone_number")
    search_fields = ("name", "address", "owner__username")
    inlines = [ServiceInline, HairdresserImageInline, WorkingHoursInline]


@admin.register(Appointment)
class AppointmentAdmin(admin.ModelAdmin):
    list_display = ("id", "client", "service", "start_time", "status")
    list_filter = ("status", "service__hairdresser")
    search_fields = ("client__username", "service__name")
    list_editable = ("status",)  # Permite cambiar el estado desde la lista


admin.site.register(User, CustomUserAdmin)
admin.site.register(Service)
admin.site.register(Review)
admin.site.register(Offer)
admin.site.register(HairdresserImage)
