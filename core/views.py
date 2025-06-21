from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse_lazy, reverse
from django.http import HttpResponseRedirect, JsonResponse
from django.views.generic import CreateView
from django.contrib.auth import login
from django.contrib.auth.views import LoginView
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.views.generic import (
    ListView,
    CreateView,
    UpdateView,
    DeleteView,
    DetailView,
    TemplateView,
)

from .forms import SignUpForm, AppointmentForm
from .models import Appointment, Hairdresser, Service
from .utils import get_location_from_ip

# Create your views here.


class SignUpView(CreateView):
    form_class = SignUpForm
    template_name = "signup.html"
    success_url = reverse_lazy("home")

    def form_valid(self, form):
        user = form.save()
        login(self.request, user)
        return redirect(self.success_url)


class CustomLoginView(LoginView):
    template_name = "login.html"


# Este Mixin verifica que el usuario sea 'owner' Y que tenga un perfil de peluquería
class OwnerRequiredMixin(LoginRequiredMixin, UserPassesTestMixin):
    def test_func(self):
        return self.request.user.is_owner and hasattr(  # type: ignore
            self.request.user, "hairdresser_profile"  # type: ignore
        )


class ServiceListView(OwnerRequiredMixin, ListView):
    model = Service
    template_name = "service_list.html"
    context_object_name = "services"

    def get_queryset(self):
        # CRÍTICO: Solo mostrar servicios del dueño logueado
        return Service.objects.filter(
            hairdresser=self.request.user.hairdresser_profile  # type: ignore
        )


class ServiceCreateView(OwnerRequiredMixin, CreateView):
    model = Service
    fields = ["name", "description", "price", "duration_minutes"]
    template_name = "service_form.html"
    success_url = reverse_lazy("service_list")

    def form_valid(self, form):
        # CRÍTICO: Asignar el servicio a la peluquería del dueño logueado
        form.instance.hairdresser = self.request.user.hairdresser_profile  # type: ignore
        return super().form_valid(form)


class ServiceUpdateView(OwnerRequiredMixin, UpdateView):
    model = Service
    fields = ["name", "description", "price", "duration_minutes"]
    template_name = "service_form.html"
    success_url = reverse_lazy("service_list")

    def get_queryset(self):
        # CRÍTICO: Asegurar que un dueño no pueda editar servicios de otro.
        return Service.objects.filter(
            hairdresser=self.request.user.hairdresser_profile  # type: ignore
        )


class ServiceDeleteView(OwnerRequiredMixin, DeleteView):
    model = Service
    template_name = "service_confirm_delete.html"
    success_url = reverse_lazy("service_list")

    def get_queryset(self):
        # CRÍTICO: Asegurar que un dueño no pueda borrar servicios de otro.
        return Service.objects.filter(
            hairdresser=self.request.user.hairdresser_profile  # type: ignore
        )


class HomeView(ListView):
    model = Hairdresser
    template_name = "home.html"
    context_object_name = "hairdressers"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        # Obtenemos peluquerías que tienen al menos una imagen asociada
        # y las limitamos a 5 para el carrusel.
        context["featured_hairdressers"] = Hairdresser.objects.filter(
            images__isnull=False
        ).distinct()[:5]

        fallback_coords = get_location_from_ip(self.request)
        context['fallback_lat'] = fallback_coords['lat']
        context['fallback_lon'] = fallback_coords['lon']
        
        return context


class HairdresserDetailView(DetailView):
    model = Hairdresser
    template_name = "hairdresser_detail.html"
    context_object_name = "hairdresser"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        hairdresser = self.get_object()
        context["services"] = Service.objects.filter(hairdresser=hairdresser)
        # Pasamos el formulario a la plantilla
        context["form"] = AppointmentForm(hairdresser=hairdresser)
        return context

    def post(self, request, *args, **kwargs):
        # Solo clientes logueados pueden reservar
        if not request.user.is_authenticated or not request.user.is_client:
            return redirect("login")

        hairdresser = self.get_object()
        form = AppointmentForm(request.POST, hairdresser=hairdresser)

        if form.is_valid():
            appointment = form.save(commit=False)
            appointment.client = request.user
            # El end_time se calcula automáticamente en el método save() del modelo
            appointment.save()
            # Redirigimos a la nueva página 'mis turnos'
            return HttpResponseRedirect(reverse_lazy("my_appointments"))
        else:
            # Si el formulario no es válido, volvemos a renderizar la página con los errores
            context = self.get_context_data()
            context["form"] = form
            return self.render_to_response(context)


class AppointmentListView(LoginRequiredMixin, ListView):
    model = Appointment
    template_name = "my_appointments.html"
    context_object_name = "appointments"

    def get_queryset(self):
        # CRÍTICO: Solo mostrar turnos del cliente logueado.
        return Appointment.objects.filter(client=self.request.user).order_by(
            "-start_time"
        )


def hairdresser_map_data(request):
    # Filtramos peluquerías que tengan latitud Y longitud
    hairdressers = Hairdresser.objects.filter(
        latitude__isnull=False, longitude__isnull=False
    )
    data = [
        {
            "name": h.name,
            "lat": h.latitude,
            "lon": h.longitude,
            "url": reverse("hairdresser_detail", args=[h.pk]),
        }
        for h in hairdressers
    ]
    return JsonResponse(data, safe=False)


class MapView(TemplateView):
    template_name = "map.html"
