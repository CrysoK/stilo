from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse_lazy, reverse
from django.http import HttpResponseRedirect, JsonResponse, Http404
from django.utils import timezone
from django.db.models import Sum, Count, Avg
from django.db.models.functions import TruncMonth
from django.contrib.auth import login
from django.contrib.auth.views import LoginView, PasswordChangeView
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.views.decorators.http import require_POST
from django.views.generic import (
    ListView,
    CreateView,
    UpdateView,
    DeleteView,
    DetailView,
    TemplateView,
    View,
)

from datetime import datetime, timedelta
import calendar

from .forms import (
    HairdresserImageForm,
    HairdresserImageUpdateForm,
    SignUpForm,
    AppointmentForm,
    LoginForm,
    HairdresserSetupForm,
    WorkingHoursFormSet,
    UserProfileForm,
    CustomPasswordChangeForm,
    ServiceForm,
    ReviewForm,
)
from .models import (
    Appointment,
    Hairdresser,
    Service,
    User,
    HairdresserImage,
    Review,
    WorkingHours,
)
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


class OwnerRequiredMixin(LoginRequiredMixin, UserPassesTestMixin):
    """
    Mixin que solo verifica que el usuario sea un 'owner' autenticado.
    """

    def test_func(self):
        return self.request.user.is_owner  # type: ignore

    def handle_no_permission(self):  # type: ignore
        if not self.request.user.is_authenticated:  # type: ignore
            return redirect("login")
        messages.error(self.request, "No tienes permisos para acceder a esta página.")  # type: ignore
        return redirect("home")


class CurrentHairdresserMixin:
    """
    Mixin que proporciona un get_object que devuelve la peluquería
    del usuario actual, creándola si no existe.
    """

    def get_object(self, queryset=None):
        try:
            # El owner se obtiene del usuario de la sesión
            return self.request.user.hairdresser_profile  # type: ignore
        except Hairdresser.DoesNotExist:
            # Si un owner llega aquí sin perfil, se lo creamos
            return Hairdresser.objects.create(owner=self.request.user)  # type: ignore


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
            self.request, f"El servicio '{self.object.name}' ha sido borrado."  # type: ignore
        )
        return super().form_valid(form)  # type: ignore

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

    def get_queryset(self):
        # Prefetch images y services para eficiencia
        return (
            super()
            .get_queryset()
            .prefetch_related(
                "images",
                "services__appointments__review",
                "working_hours",
            )
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        hairdresser = self.get_object()
        all_images = list(hairdresser.images.all())  # type: ignore
        if hairdresser.cover_image and hairdresser.cover_image in all_images:  # type: ignore
            all_images.remove(hairdresser.cover_image)  # type: ignore
            all_images.insert(0, hairdresser.cover_image)  # type: ignore
        context["ordered_images"] = all_images

        working_hours = hairdresser.working_hours.all()  # type: ignore
        if working_hours.exists():
            min_time = min(wh.start_time for wh in working_hours)
            max_time = max(wh.end_time for wh in working_hours)
            min_dt = datetime.combine(datetime.min.date(), min_time)
            max_dt = datetime.combine(datetime.min.date(), max_time)
            context["slot_min_time"] = (min_dt - timedelta(hours=1)).strftime(
                "%H:%M:%S"
            )
            context["slot_max_time"] = (max_dt + timedelta(hours=1)).strftime(
                "%H:%M:%S"
            )
        else:
            context["slot_min_time"] = "09:00:00"
            context["slot_max_time"] = "20:00:00"

        context["services"] = hairdresser.services.all()  # type: ignore
        # Pasamos el formulario a la plantilla
        context["form"] = AppointmentForm(hairdresser=hairdresser)
        # Pasamos las reseñas a la plantilla
        context["reviews"] = (
            Review.objects.filter(appointment__service__hairdresser=hairdresser)
            .select_related("appointment__client")
            .order_by("-created_at")
        )
        return context

    def post(self, request, *args, **kwargs):
        if not request.user.is_authenticated or request.user.is_owner:
            return JsonResponse(
                {"success": False, "error": "No tienes permiso para reservar."},
                status=403,
            )

        hairdresser = self.get_object()
        form = AppointmentForm(request.POST, hairdresser=hairdresser)

        if form.is_valid():
            appointment = form.save(commit=False)
            appointment.client = request.user
            appointment.save()
            messages.success(self.request, "¡Tu turno ha sido reservado con éxito!")
            return JsonResponse(
                {"success": True, "redirect_url": reverse("my_appointments")}
            )
        else:
            # Devolver el primer error encontrado para mostrarlo en el modal
            error_message = "Por favor, corrige los errores."
            # Los errores de `clean()` van a `__all__`
            if "__all__" in form.errors:
                error_message = form.errors["__all__"][0]
            else:
                for field in form.errors:
                    error_message = form.errors[field][0]
                    break
            return JsonResponse({"success": False, "error": error_message}, status=400)


class AppointmentListView(LoginRequiredMixin, ListView):
    model = Appointment
    template_name = "my_appointments.html"
    context_object_name = "appointments"

    def get_queryset(self):
        # CRÍTICO: Solo mostrar turnos del cliente logueado.
        return (
            Appointment.objects.filter(client=self.request.user)
            .select_related("review", "service__hairdresser")
            .order_by("-start_time")
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["review_form"] = ReviewForm()
        return context


class ReviewCreateView(LoginRequiredMixin, View):
    def post(self, request, pk):
        appointment = get_object_or_404(Appointment, pk=pk)

        # Security checks
        if not (
            appointment.client == request.user
            and appointment.status == "COMPLETED"
            and not hasattr(appointment, "review")
        ):
            return JsonResponse(
                {"error": "No tienes permiso para realizar esta acción."}, status=403
            )

        form = ReviewForm(request.POST)
        if form.is_valid():
            review = form.save(commit=False)
            review.appointment = appointment
            review.save()
            return JsonResponse(
                {"success": True, "review_pk": review.pk, "rating": review.rating}
            )

        return JsonResponse({"success": False, "errors": form.errors}, status=400)


class ReviewUpdateView(LoginRequiredMixin, View):
    def post(self, request, pk):
        review = get_object_or_404(Review, pk=pk)

        # Security check
        if review.appointment.client != request.user:
            return JsonResponse(
                {"error": "No tienes permiso para editar esta reseña."}, status=403
            )

        form = ReviewForm(request.POST, instance=review)
        if form.is_valid():
            review = form.save()
            return JsonResponse({"success": True, "rating": review.rating})

        return JsonResponse({"success": False, "errors": form.errors}, status=400)


class ReviewDeleteView(LoginRequiredMixin, View):
    def post(self, request, pk):
        review = get_object_or_404(Review, pk=pk)

        # Security check
        if review.appointment.client != request.user:
            return JsonResponse(
                {"error": "No tienes permiso para borrar esta reseña."}, status=403
            )

        review.delete()
        return JsonResponse({"success": True})


def get_review_detail(request, pk):
    # API endpoint to fetch review data for the edit modal
    review = get_object_or_404(Review, pk=pk)
    if request.user != review.appointment.client:
        raise Http404

    data = {
        "rating": review.rating,
        "comment": review.comment,
    }
    return JsonResponse(data)


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


class OwnerStatsView(OwnerRequiredMixin, TemplateView):
    template_name = "owner_stats.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        hairdresser = self.request.user.hairdresser_profile  # type: ignore

        # --- Filtro de fecha ---
        month_str = self.request.GET.get("month")  # formato YYYY-MM
        try:
            # Si se provee un mes, se usa. Si no, se usa el actual.
            if month_str:
                selected_date = datetime.strptime(month_str, "%Y-%m").date()
            else:
                selected_date = timezone.now().date()
        except ValueError:
            selected_date = timezone.now().date()

        start_of_month = selected_date.replace(day=1)
        _, num_days = calendar.monthrange(selected_date.year, selected_date.month)
        end_of_month = selected_date.replace(day=num_days)

        context["selected_month_iso"] = start_of_month.strftime("%Y-%m")
        context["start_of_month"] = start_of_month

        # Appointments base querysets for the selected month
        apps_in_month = Appointment.objects.filter(
            service__hairdresser=hairdresser,
            start_time__range=[start_of_month, end_of_month],
        )
        completed_in_month = apps_in_month.filter(status="COMPLETED")

        # --- Resumen del mes seleccionado ---
        context["monthly_revenue"] = (
            completed_in_month.aggregate(total=Sum("amount"))["total"] or 0
        )
        context["monthly_appointments"] = completed_in_month.count()

        # --- Estadísticas generales del mes seleccionado ---
        # Tasa de ausentismo
        total_finished_apps = apps_in_month.filter(
            status__in=["COMPLETED", "NO_SHOW", "CANCELLED"]
        ).count()
        absent_apps = apps_in_month.filter(status__in=["NO_SHOW", "CANCELLED"]).count()
        context["no_show_rate"] = (
            (absent_apps / total_finished_apps) * 100 if total_finished_apps > 0 else 0
        )

        # Ticket promedio
        total_revenue = context["monthly_revenue"]
        completed_count = context["monthly_appointments"]
        context["average_ticket"] = (
            total_revenue / completed_count if completed_count > 0 else 0
        )

        # Top 5 Clientes (basado en el mes seleccionado)
        context["top_clients"] = (
            completed_in_month.values("client__first_name", "client__last_name")
            .annotate(total_spent=Sum("amount"))
            .order_by("-total_spent")[:5]
        )
        return context


def _get_date_range_from_request(request):
    """Helper to get a date range for a given month from a request, or default to current month."""
    month_str = request.GET.get("month")
    try:
        if month_str:
            selected_date = datetime.strptime(month_str, "%Y-%m").date()
        else:
            selected_date = timezone.now().date()
    except ValueError:
        selected_date = timezone.now().date()

    start_of_month = selected_date.replace(day=1)
    _, num_days = calendar.monthrange(start_of_month.year, start_of_month.month)
    end_of_month = start_of_month.replace(day=num_days)

    return start_of_month, end_of_month


def owner_api_required(view_func):
    """
    Decorator to check if user is an authenticated owner for API views.
    """

    def _wrapped_view(request, *args, **kwargs):
        if not (
            request.user.is_authenticated
            and request.user.is_owner  # type: ignore
            and hasattr(request.user, "hairdresser_profile")
        ):
            return JsonResponse({"error": "No autorizado"}, status=403)
        return view_func(request, *args, **kwargs)

    return _wrapped_view


@owner_api_required
def earnings_chart_data(request):
    hairdresser = request.user.hairdresser_profile  # type: ignore
    # This chart shows all-time monthly evolution, so it's not filtered by month.
    data = (
        Appointment.objects.filter(service__hairdresser=hairdresser, status="COMPLETED")
        .annotate(month=TruncMonth("start_time"))
        .values("month")
        .annotate(total_earnings=Sum("amount"))
        .order_by("month")
    )
    labels = [d["month"].strftime("%B %Y").capitalize() for d in data]
    earnings = [float(d["total_earnings"]) for d in data]

    return JsonResponse({"labels": labels, "data": earnings})


@owner_api_required
def revenue_by_service_chart_data(request):
    hairdresser = request.user.hairdresser_profile  # type: ignore
    start_date, end_date = _get_date_range_from_request(request)

    data = (
        Appointment.objects.filter(
            service__hairdresser=hairdresser,
            status="COMPLETED",
            start_time__range=[start_date, end_date],
        )
        .values("service__name")
        .annotate(total_revenue=Sum("amount"))
        .order_by("-total_revenue")
    )

    labels = [d["service__name"] for d in data]
    revenue_data = [float(d["total_revenue"]) for d in data]

    return JsonResponse({"labels": labels, "data": revenue_data})


@owner_api_required
def busiest_days_chart_data(request):
    hairdresser = request.user.hairdresser_profile  # type: ignore
    start_date, end_date = _get_date_range_from_request(request)

    # El lookup `__week_day` devuelve 1 (Dom) a 7 (Sáb)
    day_counts = (
        Appointment.objects.filter(
            service__hairdresser=hairdresser,
            status__in=["COMPLETED", "CONFIRMED", "PENDING"],
            start_time__range=[start_date, end_date],
        )
        .values("start_time__week_day")
        .annotate(count=Count("id"))
        .order_by("start_time__week_day")
    )

    day_map = {
        1: "Domingo",
        2: "Lunes",
        3: "Martes",
        4: "Miércoles",
        5: "Jueves",
        6: "Viernes",
        7: "Sábado",
    }
    final_counts = {day: 0 for day in day_map.values()}
    for item in day_counts:
        day_name = day_map.get(item["start_time__week_day"])
        if day_name:
            final_counts[day_name] = item["count"]

    ordered_labels = [
        "Lunes",
        "Martes",
        "Miércoles",
        "Jueves",
        "Viernes",
        "Sábado",
        "Domingo",
    ]
    ordered_data = [final_counts[day] for day in ordered_labels]

    return JsonResponse({"labels": ordered_labels, "data": ordered_data})


def appointment_events_data(request, hairdresser_id):
    # Devuelve los turnos de una peluquería como eventos de FullCalendar
    appointments = Appointment.objects.filter(
        service__hairdresser_id=hairdresser_id,
        # Considerar turnos pendientes o confirmados como no disponibles
        status__in=["PENDING", "CONFIRMED"],
    )
    working_hours = WorkingHours.objects.filter(hairdresser_id=hairdresser_id)
    events = []

    # Agregar horarios de atención como eventos de fondo
    # Mapeo: Django (0=Lun..6=Dom) a FullCalendar (0=Dom..6=Sab)
    for wh in working_hours:
        fc_day = (wh.day_of_week + 1) % 7
        events.append(
            {
                "daysOfWeek": [fc_day],
                "startTime": wh.start_time.strftime("%H:%M"),
                "endTime": wh.end_time.strftime("%H:%M"),
                "display": "background",
                "groupId": "working_hours",  # Para usar en selectConstraint
            }
        )

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

    def handle_no_permission(self):  # type: ignore
        if not self.request.user.is_authenticated:  # type: ignore
            return redirect("login")
        messages.error(self.request, "No tienes permisos para acceder a esta página.")  # type: ignore
        return redirect("home")

    def get_object(self, queryset=None):
        try:
            return self.request.user.hairdresser_profile  # type: ignore
        except Hairdresser.DoesNotExist:
            return Hairdresser.objects.create(owner=self.request.user)  # type: ignore


class MyHairdresserInfoView(OwnerRequiredMixin, CurrentHairdresserMixin, UpdateView):
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


class MyHairdresserHoursView(OwnerRequiredMixin, CurrentHairdresserMixin, View):
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


class MyHairdresserServicesView(
    OwnerRequiredMixin, CurrentHairdresserMixin, DetailView
):
    model = Hairdresser
    template_name = "my_hairdresser_services.html"
    context_object_name = "hairdresser"  # Usamos 'hairdresser' en la plantilla

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["active_tab"] = "services"
        context["services"] = Service.objects.filter(hairdresser=self.object)  # type: ignore
        context["service_form"] = ServiceForm()  # Para el modal de creación
        return context


class MyHairdresserImagesView(OwnerRequiredMixin, CurrentHairdresserMixin, View):
    template_name = "my_hairdresser_images.html"

    def get(self, request, *args, **kwargs):
        hairdresser = self.get_object()
        images = HairdresserImage.objects.filter(hairdresser=hairdresser)
        upload_form = HairdresserImageForm()
        update_form = HairdresserImageUpdateForm()
        return render(
            request,
            self.template_name,
            {
                "object": hairdresser,
                "images": images,
                "upload_form": upload_form,
                "update_form": update_form,
                "active_tab": "images",
            },
        )

    def post(self, request, *args, **kwargs):
        hairdresser = self.get_object()
        action = request.POST.get("action")

        if action == "upload":
            form = HairdresserImageForm(request.POST, request.FILES)
            if form.is_valid():
                image = form.save(commit=False)
                image.hairdresser = hairdresser
                image.save()
                messages.success(request, "Imagen subida exitosamente.")
            else:
                messages.error(
                    request, "Error al subir la imagen. Verifique el archivo."
                )
        elif action == "update":
            image_pk = request.POST.get("image_pk")
            image_instance = get_object_or_404(
                HairdresserImage, pk=image_pk, hairdresser=hairdresser
            )
            form = HairdresserImageUpdateForm(request.POST, instance=image_instance)
            if form.is_valid():
                form.save()
                messages.success(
                    request, "La descripción de la imagen ha sido actualizada."
                )
            else:
                messages.error(request, "Error al actualizar la descripción.")

        return redirect("my_hairdresser_images")


class HairdresserImageDeleteView(OwnerRequiredMixin, DeleteView):
    model = HairdresserImage
    success_url = reverse_lazy("my_hairdresser_images")
    # Esta vista será solo para POST, por lo que no se necesita plantilla.

    def get_queryset(self):
        # Asegurarse de que el dueño solo puede borrar sus propias imágenes
        return HairdresserImage.objects.filter(hairdresser=self.request.user.hairdresser_profile)  # type: ignore

    def form_valid(self, form):
        hairdresser = self.request.user.hairdresser_profile  # type: ignore
        if hairdresser.cover_image == self.object:  # type: ignore
            hairdresser.cover_image = None
            hairdresser.save()

        messages.success(self.request, "La imagen ha sido borrada.")
        return super().form_valid(form)  # type: ignore

    def get(self, request, *args, **kwargs):
        # No permitir peticiones GET
        return redirect(self.success_url)


class SetCoverImageView(OwnerRequiredMixin, CurrentHairdresserMixin, View):
    def post(self, request, *args, **kwargs):
        hairdresser = self.get_object()
        image_pk = kwargs.get("pk")

        # Asegurarnos de que la imagen pertenece a la peluquería del usuario
        image_to_set = get_object_or_404(
            HairdresserImage, pk=image_pk, hairdresser=hairdresser
        )

        hairdresser.cover_image = image_to_set  # type: ignore
        hairdresser.save()
        messages.success(request, f"La imagen ha sido establecida como portada.")
        return redirect("my_hairdresser_images")

    def get(self, request, *args, **kwargs):
        return redirect("my_hairdresser_images")


class UserProfileView(LoginRequiredMixin, UpdateView):
    model = User
    form_class = UserProfileForm
    template_name = "user_profile.html"
    success_url = reverse_lazy("user_profile")

    def get_object(self, queryset=None):  # type: ignore
        # We know this is a User model instance because of LoginRequiredMixin
        return self.request.user

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


class WorkstationView(OwnerRequiredMixin, TemplateView):
    template_name = "workstation.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        hairdresser = self.request.user.hairdresser_profile
        today = timezone.now().date()

        # Obtenemos todos los turnos del día, ordenados
        appointments_today = (
            Appointment.objects.filter(
                service__hairdresser=hairdresser, start_time__date=today
            )
            .select_related("client", "service")
            .order_by("start_time")
        )

        now = timezone.now()
        current_appointment = None
        next_appointment = None
        upcoming_appointments = []
        completed_appointments = []

        found_current = False
        for app in appointments_today:
            # Clasificar los turnos
            if app.status in ["COMPLETED", "NO_SHOW", "CANCELLED"]:
                completed_appointments.append(app)
            elif app.start_time <= now < app.end_time and not current_appointment:
                current_appointment = app
                found_current = True
            elif app.start_time > now:
                if found_current and not next_appointment:
                    next_appointment = app
                else:
                    upcoming_appointments.append(app)

        # Si no hay un turno "en curso", el próximo turno futuro es el "siguiente"
        if not current_appointment and upcoming_appointments:
            next_appointment = upcoming_appointments.pop(0)

        context["current_appointment"] = current_appointment
        context["next_appointment"] = next_appointment
        context["upcoming_appointments"] = upcoming_appointments
        context["completed_appointments"] = completed_appointments
        context["hairdresser"] = hairdresser
        return context


@login_required
@require_POST
def update_appointment_status(request, pk):
    # Asegurarse que el usuario es dueño
    if not request.user.is_owner:
        return JsonResponse(
            {"status": "error", "message": "Permission denied"}, status=403
        )

    try:
        # CRÍTICO: Asegurar que el turno pertenece al peluquero logueado
        appointment = get_object_or_404(
            Appointment, pk=pk, service__hairdresser=request.user.hairdresser_profile
        )

        new_status = request.POST.get("status")
        valid_statuses = ["COMPLETED", "NO_SHOW"]

        if new_status in valid_statuses:
            appointment.status = new_status
            appointment.save()
            return JsonResponse({"status": "success", "message": "Turno actualizado."})
        else:
            return JsonResponse(
                {"status": "error", "message": "Estado inválido."}, status=400
            )

    except Exception as e:
        return JsonResponse({"status": "error", "message": str(e)}, status=500)
