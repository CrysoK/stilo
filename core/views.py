from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse_lazy, reverse
from django.http import HttpResponseRedirect, JsonResponse
from django.utils import timezone
from django.db.models import Sum, Count
from django.db.models.functions import TruncMonth
from django.contrib.auth import login
from django.contrib.auth.views import LoginView, PasswordChangeView
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.contrib import messages
from django.views.generic import (
    ListView,
    CreateView,
    UpdateView,
    DeleteView,
    DetailView,
    TemplateView,
    View,
)

from .forms import (
    SignUpForm,
    AppointmentForm,
    LoginForm,
    HairdresserSetupForm,
    WorkingHoursFormSet,
    UserProfileForm,
    CustomPasswordChangeForm,
    ServiceForm,
)
from .models import Appointment, Hairdresser, Service, User
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
    form_class = LoginForm


# Este Mixin verifica que el usuario sea 'owner' Y que tenga un perfil de peluquería
class OwnerRequiredMixin(LoginRequiredMixin, UserPassesTestMixin):
    def test_func(self):
        return self.request.user.is_owner  # type: ignore


class ServiceCreateView(OwnerRequiredMixin, CreateView):
    model = Service
    form_class = ServiceForm
    success_url = reverse_lazy("my_hairdresser_services")

    def form_valid(self, form):
        form.instance.hairdresser = self.request.user.hairdresser_profile  # type: ignore
        response = super().form_valid(form)
        messages.success(self.request, "Servicio creado exitosamente.")
        return response

    def get(self, request, *args, **kwargs):
        # Redirigir si se intenta acceder por GET, ya que el formulario está en un modal
        return redirect("my_hairdresser_services")


class ServiceUpdateView(OwnerRequiredMixin, UpdateView):
    model = Service
    form_class = ServiceForm
    success_url = reverse_lazy("my_hairdresser_services")

    def get_queryset(self):
        return Service.objects.filter(
            hairdresser=self.request.user.hairdresser_profile  # type: ignore
        )

    def form_valid(self, form):
        response = super().form_valid(form)
        messages.success(self.request, "Servicio actualizado exitosamente.")
        return response

    def get(self, request, *args, **kwargs):
        # Redirigir si se intenta acceder por GET
        return redirect("my_hairdresser_services")


class ServiceDeleteView(OwnerRequiredMixin, DeleteView):
    model = Service
    success_url = reverse_lazy("my_hairdresser_services")

    def get_queryset(self):
        # CRÍTICO: Asegurar que un dueño no pueda borrar servicios de otro.
        return Service.objects.filter(
            hairdresser=self.request.user.hairdresser_profile  # type: ignore
        )

    def form_valid(self, form):
        # Añadir mensaje de éxito
        messages.success(
            self.request, f"El servicio '{self.object.name}' ha sido borrado."
        )
        return super().form_valid(form)

    def get(self, request, *args, **kwargs):
        return redirect("my_hairdresser_services")


class HomeView(ListView):
    model = Hairdresser
    template_name = "home.html"
    context_object_name = "hairdressers"

    def get_queryset(self):
        # Prefetch related objects for efficiency when calling is_complete() and images.exists()
        return (
            super()
            .get_queryset()
            .prefetch_related("working_hours", "services", "images")
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        # self.object_list contains the queryset returned by get_queryset()
        # Filter for complete hairdressers
        complete_hairdressers = [h for h in self.get_queryset() if h.is_complete()]
        context["hairdressers"] = complete_hairdressers

        # Get featured hairdressers from the complete ones that also have images
        context["featured_hairdressers"] = [
            h for h in complete_hairdressers if h.images.exists()
        ][:5]

        fallback_coords = get_location_from_ip(self.request)
        context["fallback_lat"] = fallback_coords["lat"]
        context["fallback_lon"] = fallback_coords["lon"]

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
        if not request.user.is_authenticated:
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


class OwnerDashboardView(OwnerRequiredMixin, TemplateView):
    template_name = "owner_dashboard.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        hairdresser = self.request.user.hairdresser_profile  # type: ignore
        # Datos para las tarjetas de resumen
        today = timezone.now().date()
        start_of_month = today.replace(day=1)
        # Turnos completados este mes
        completed_this_month = Appointment.objects.filter(
            service__hairdresser=hairdresser,
            status="COMPLETED",
            start_time__gte=start_of_month,
        )
        context["monthly_revenue"] = (
            completed_this_month.aggregate(total=Sum("service__price"))["total"] or 0
        )
        context["monthly_appointments"] = completed_this_month.count()
        # Servicio más popular del mes
        top_service = (
            completed_this_month.values("service__name")
            .annotate(count=Count("service"))
            .order_by("-count")
            .first()
        )
        context["top_service"] = top_service["service__name"] if top_service else "N/A"
        return context


def earnings_chart_data(request):
    # Asegurar que el usuario sea un dueño
    if not (
        request.user.is_authenticated
        and request.user.is_owner  # type: ignore
        and hasattr(request.user, "hairdresser_profile")
    ):
        return JsonResponse({"error": "No autorizado"}, status=403)
    hairdresser = request.user.hairdresser_profile  # type: ignore
    # Agrupar turnos completados por mes y sumar precios
    data = (
        Appointment.objects.filter(service__hairdresser=hairdresser, status="COMPLETED")
        .annotate(month=TruncMonth("start_time"))
        .values("month")
        .annotate(total_earnings=Sum("service__price"))
        .order_by("month")
    )
    # Formatear para Chart.js
    labels = [d["month"].strftime("%B %Y") for d in data]
    earnings = [float(d["total_earnings"]) for d in data]

    return JsonResponse({"labels": labels, "data": earnings})


def appointment_events_data(request, hairdresser_id):
    # Devuelve los turnos de una peluquería como eventos de FullCalendar
    appointments = Appointment.objects.filter(service__hairdresser_id=hairdresser_id)
    events = []
    for app in appointments:
        events.append(
            {
                "title": "Reservado",  # Por privacidad
                "start": app.start_time.isoformat(),
                "end": app.end_time.isoformat(),
                "color": "#dc3545",
                # "display": "background",
            }
        )
    return JsonResponse(events, safe=False)


class MyHairdresserBaseMixin(LoginRequiredMixin, UserPassesTestMixin):
    """
    Mixin base que comprueba permisos y obtiene el objeto Hairdresser.
    """

    def test_func(self):
        return self.request.user.is_owner  # type: ignore

    def handle_no_permission(self):
        if not self.request.user.is_authenticated:
            return redirect("login")
        messages.error(self.request, "No tienes permisos para acceder a esta página.")
        return redirect("home")

    def get_object(self, queryset=None):
        try:
            return self.request.user.hairdresser_profile  # type: ignore
        except Hairdresser.DoesNotExist:
            return Hairdresser.objects.create(owner=self.request.user)  # type: ignore


class MyHairdresserInfoView(MyHairdresserBaseMixin, UpdateView):
    model = Hairdresser
    form_class = HairdresserSetupForm
    template_name = "my_hairdresser_info.html"
    success_url = reverse_lazy("my_hairdresser_info")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["active_tab"] = "info"
        return context

    def form_valid(self, form):
        messages.success(self.request, "La información general ha sido actualizada.")
        return super().form_valid(form)


class MyHairdresserHoursView(MyHairdresserBaseMixin, View):
    template_name = "my_hairdresser_hours.html"

    def get(self, request, *args, **kwargs):
        hairdresser = self.get_object()
        formset = WorkingHoursFormSet(instance=hairdresser)
        return render(
            request,
            self.template_name,
            {
                "object": hairdresser,
                "working_hours_formset": formset,
                "active_tab": "hours",
            },
        )

    def post(self, request, *args, **kwargs):
        hairdresser = self.get_object()
        formset = WorkingHoursFormSet(request.POST, instance=hairdresser)
        if formset.is_valid():
            formset.save()
            messages.success(request, "Los horarios de atención han sido actualizados.")
            return redirect("my_hairdresser_hours")

        # Si no es válido, renderizar de nuevo con errores
        return render(
            request,
            self.template_name,
            {
                "object": hairdresser,
                "working_hours_formset": formset,
                "active_tab": "hours",
            },
        )


class MyHairdresserServicesView(MyHairdresserBaseMixin, DetailView):
    model = Hairdresser
    template_name = "my_hairdresser_services.html"
    context_object_name = "hairdresser"  # Usamos 'hairdresser' en la plantilla

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["active_tab"] = "services"
        context["services"] = Service.objects.filter(hairdresser=self.object)
        context["service_form"] = ServiceForm()  # Para el modal de creación
        return context


class UserProfileView(LoginRequiredMixin, UpdateView):
    model = User
    form_class = UserProfileForm
    template_name = "user_profile.html"
    success_url = reverse_lazy("user_profile")

    def get_object(self, queryset=None):
        # We know this is a User model instance because of LoginRequiredMixin
        return self.request.user  # type: ignore[return-value]

    def form_valid(self, form):
        messages.success(self.request, "Tu perfil ha sido actualizado exitosamente.")
        return super().form_valid(form)


class CustomPasswordChangeView(LoginRequiredMixin, PasswordChangeView):
    template_name = "password_change.html"
    form_class = CustomPasswordChangeForm
    success_url = reverse_lazy("user_profile")

    def form_valid(self, form):
        messages.success(self.request, "Tu contraseña ha sido cambiada exitosamente.")
        return super().form_valid(form)


def get_service_detail(request, pk):
    if not request.user.is_authenticated or not request.user.is_owner:
        return JsonResponse({"error": "Unauthorized"}, status=403)

    service = get_object_or_404(
        Service, pk=pk, hairdresser=request.user.hairdresser_profile
    )
    return JsonResponse(
        {
            "name": service.name,
            "price": str(service.price),
            "duration_minutes": service.duration_minutes,
            "description": service.description,
        }
    )
