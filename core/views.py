from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse_lazy, reverse
from django.http import HttpResponseRedirect, JsonResponse, Http404
from django.utils import timezone
from django.db.models import Sum, Count, Avg, Q
from decimal import Decimal
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
import logging
import requests

logger = logging.getLogger(__name__)
mp_logger = logging.getLogger('mp')
cron_logger = logging.getLogger('cron')

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
    PaymentTransaction,
)
from .utils import get_location_from_ip, geocode_address

# Create your views here.


class SignUpView(CreateView):
    form_class = SignUpForm
    template_name = "signup.html"
    success_url = reverse_lazy("home")

    def form_valid(self, form):
        user = form.save()
        login(self.request, user)
        if user.email:
            login_url = self.request.build_absolute_uri(reverse("login"))
            from core.utils import notify_user
            notify_user(
                user=user,
                event_type="WELCOME",
                context={"user": user, "login_url": login_url},
                subject="¡Te damos la bienvenida a Stilo!",
            )
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
        self.object = form.save()
        messages.success(self.request, "Servicio creado exitosamente.")
        return JsonResponse({"success": True})

    def form_invalid(self, form):
        return JsonResponse({"success": False, "errors": form.errors}, status=400)

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
        self.object = form.save()
        messages.success(self.request, "Servicio actualizado exitosamente.")
        return JsonResponse({"success": True})

    def form_invalid(self, form):
        return JsonResponse({"success": False, "errors": form.errors}, status=400)

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
        queryset = (
            super()
            .get_queryset()
            .prefetch_related("working_hours", "services", "images")
        )
        
        q = self.request.GET.get("q", "").strip()
        service = self.request.GET.get("service", "").strip()
        
        if q:
            queryset = queryset.filter(
                Q(name__icontains=q) |
                Q(address__icontains=q) |
                Q(description__icontains=q)
            )
            
        if service:
            if service == "corte":
                queryset = queryset.filter(services__name__icontains="corte")
            elif service == "color":
                queryset = queryset.filter(
                    Q(services__name__icontains="color") |
                    Q(services__name__icontains="tinte") |
                    Q(services__name__icontains="mechas")
                )
            elif service == "barberia":
                queryset = queryset.filter(
                    Q(services__name__icontains="barba") |
                    Q(services__name__icontains="barber")
                )
            elif service == "peinado":
                queryset = queryset.filter(
                    Q(services__name__icontains="peinado") |
                    Q(services__name__icontains="secado")
                )
            elif service == "tratamientos":
                queryset = queryset.filter(
                    Q(services__name__icontains="tratamiento") |
                    Q(services__name__icontains="keratina")
                )
                
        return queryset.distinct()

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        # self.object_list contains the queryset returned by get_queryset()
        # Filter for complete hairdressers
        complete_hairdressers = [h for h in self.get_queryset() if h.is_complete()]
        context["hairdressers"] = complete_hairdressers

        q = self.request.GET.get("q", "").strip()
        service = self.request.GET.get("service", "").strip()

        # Omitir destacados en búsquedas para centrar la atención en los resultados
        if q or service:
            context["featured_hairdressers"] = []
        else:
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
        # El formulario de reserva solo se incluye para clientes, no para owners.
        if not (self.request.user.is_authenticated and self.request.user.is_owner):
            context["form"] = AppointmentForm(hairdresser=hairdresser)
        # Pasamos las reseñas a la plantilla
        context["reviews"] = (
            Review.objects.filter(appointment__service__hairdresser=hairdresser)
            .select_related("appointment__client")
            .order_by("-created_at")
        )
        return context

    def post(self, request, *args, **kwargs):
        from django.db import transaction

        if not request.user.is_authenticated or request.user.is_owner:
            return JsonResponse(
                {"success": False, "error": "No tienes permiso para reservar."},
                status=403,
            )

        hairdresser = self.get_object()
        form = AppointmentForm(request.POST, hairdresser=hairdresser)

        if form.is_valid():
            # Determinamos si se requiere pago antes de guardar,
            # para poder establecer expires_at y evitar notificaciones prematuras.
            service = form.cleaned_data["service"]
            payment_method = form.cleaned_data["payment_method"]

            # Calculamos si requiere pago digital usando una instancia temporal
            temp_app = Appointment(service=service, payment_method=payment_method, amount=service.price)
            requires_payment = False
            payment_amount = Decimal('0.00')

            if payment_method == 'FULL':
                requires_payment = True
                payment_amount = service.price
            else:  # CASH
                deposit_amount = temp_app.get_required_deposit_amount()
                if deposit_amount > 0:
                    requires_payment = True
                    payment_amount = deposit_amount

            try:
                with transaction.atomic():
                    appointment = form.save(commit=False)
                    appointment.client = request.user
                    appointment.status = 'PENDING'

                    if requires_payment:
                        # El turno expira en 10 minutos si no se completa el pago
                        appointment.expires_at = timezone.now() + timedelta(minutes=10)

                    appointment.save()

                    if not requires_payment:
                        # No requiere pago inmediato: el turno queda PENDING
                        # esperando que el dueño lo confirme manualmente.
                        # Las notificaciones de "solicitud recibida" se envían
                        # automáticamente desde Appointment.save().
                        messages.success(self.request, "Tu solicitud de turno fue enviada. Recibirás una notificación cuando el local la confirme.")
                        return JsonResponse(
                            {"success": True, "redirect_url": reverse("my_appointments")}
                        )
            except Exception as e:

                logger.error(f"Error guardando el turno: {str(e)}")
                return JsonResponse(
                    {"success": False, "error": "Error al crear la reserva. Intente nuevamente."},
                    status=500
                )

            # requires_payment=True: crear preferencia en MercadoPago
            try:
                import requests as http_requests

                from django.conf import settings as app_settings
                # En sandbox, usamos el token de prueba del panel (no-marketplace)
                # porque el token OAuth genera preferencias en modo marketplace,
                # que falla en sandbox con "algo anduvo mal".
                if app_settings.MERCADOPAGO_SANDBOX and app_settings.MERCADOPAGO_TEST_ACCESS_TOKEN:
                    access_token = app_settings.MERCADOPAGO_TEST_ACCESS_TOKEN
                else:
                    access_token = hairdresser.mercadopago_access_token
                if not access_token:
                    raise ValueError("La peluquería no tiene un token de MercadoPago configurado.")

                pref_url = "https://api.mercadopago.com/checkout/preferences"
                mp_headers = {
                    "Authorization": f"Bearer {access_token}",
                    "Content-Type": "application/json"
                }

                back_url = request.build_absolute_uri(reverse("my_appointments"))
                notification_url = request.build_absolute_uri(
                    reverse("mercadopago_webhook", args=[hairdresser.id])
                )

                title = f"Turno Stilo - {appointment.service.name}"
                if appointment.payment_method == 'FULL':
                    title += " (Pago Completo)"
                else:
                    title += " (Seña)"

                payload = {
                    "items": [
                        {
                            "id": str(appointment.service.id),
                            "title": title,
                            "description": f"Turno para {appointment.service.name} en {hairdresser.name}",
                            "quantity": 1,
                            "currency_id": "ARS",
                            "unit_price": float(payment_amount)
                        }
                    ],
                    "payer": {
                        "name": appointment.client.first_name,
                        "surname": appointment.client.last_name,
                        "email": appointment.client.email,
                    },
                    "back_urls": {
                        "success": back_url,
                        "failure": back_url,
                        "pending": back_url
                    },
                    "auto_return": "approved",
                    "binary_mode": True,
                    "notification_url": notification_url,
                    "statement_descriptor": "Stilo",
                    "external_reference": str(appointment.id)
                }

                # Comisión del marketplace (Application Fee)
                commission_str = getattr(app_settings, "MERCADOPAGO_COMMISSION_PERCENTAGE", "3.0")
                try:
                    commission_percentage = Decimal(str(commission_str))
                except Exception:
                    commission_percentage = Decimal("3.0")

                if commission_percentage > 0:
                    # OJO: Solo cobramos comisión si NO estamos usando el token de prueba global.
                    # En sandbox con el token de prueba general daría error "marketplace_fee_not_allowed"
                    # porque no hay un flujo OAuth real (el vendedor y el marketplace son el mismo usuario).
                    is_test_token = app_settings.MERCADOPAGO_SANDBOX and access_token == app_settings.MERCADOPAGO_TEST_ACCESS_TOKEN
                    if not is_test_token:
                        marketplace_fee = (payment_amount * (commission_percentage / Decimal("100.00"))).quantize(Decimal("0.01"))
                        payload["marketplace_fee"] = float(marketplace_fee)


                mp_logger.info(f"Creando preferencia MP para turno {appointment.id} por monto {payment_amount}")

                mp_response = http_requests.post(pref_url, json=payload, headers=mp_headers, timeout=10)
                mp_response.raise_for_status()
                pref_data = mp_response.json()

                redirect_url = pref_data.get("sandbox_init_point") if app_settings.MERCADOPAGO_SANDBOX else pref_data.get("init_point")
                if not redirect_url:
                    redirect_url = pref_data.get("init_point") or pref_data.get("sandbox_init_point")
                if not redirect_url:
                    raise ValueError("No se pudo obtener el punto de inicio de MercadoPago (init_point/sandbox_init_point).")

                return JsonResponse(
                    {"success": True, "redirect_url": redirect_url}
                )
            except Exception as e:
                # En caso de error, cancelamos la creación del turno
                appointment.delete()

                mp_logger.error(f"Error creando preferencia de MercadoPago: {str(e)}")
                return JsonResponse(
                    {"success": False, "error": f"Error al iniciar el pago con MercadoPago: {str(e)}"},
                    status=500
                )
        else:
            # Devolver el primer error encontrado para mostrarlo en el modal
            error_message = "Por favor, corrige los errores."
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

    def get(self, request, *args, **kwargs):
        # Los owners tienen su propia vista de gestión de turnos.
        if request.user.is_owner:
            return redirect("owner_appointments")

        # Capturar parámetros de retorno de MercadoPago para fallback/sincronización instantánea
        payment_id = request.GET.get("payment_id") or request.GET.get("collection_id")
        status = request.GET.get("status") or request.GET.get("collection_status")
        external_reference = request.GET.get("external_reference")

        if payment_id and status == "approved" and external_reference:
            try:
                # Verificar que el turno pertenezca al usuario logueado
                appointment = Appointment.objects.get(pk=external_reference, client=request.user)

                # Si el turno no está confirmado o el monto pagado sigue siendo cero, consultamos
                if appointment.status != 'CONFIRMED' or appointment.amount_paid == Decimal('0.00'):
                    hairdresser = appointment.service.hairdresser
                    from django.conf import settings as app_settings

                    if app_settings.MERCADOPAGO_SANDBOX and app_settings.MERCADOPAGO_TEST_ACCESS_TOKEN:
                        access_token = app_settings.MERCADOPAGO_TEST_ACCESS_TOKEN
                    else:
                        access_token = hairdresser.mercadopago_access_token

                    if access_token:
                        url = f"https://api.mercadopago.com/v1/payments/{payment_id}"
                        headers = {"Authorization": f"Bearer {access_token}"}
                        response = requests.get(url, headers=headers, timeout=10)
                        if response.status_code == 200:
                            payment_data = response.json()
                            api_status = payment_data.get('status')
                            api_ext_ref = str(payment_data.get('external_reference'))
                            transaction_amount = payment_data.get('transaction_amount')

                            # Registrar la transacción de pago para auditoría (inmutable)
                            try:
                                PaymentTransaction.objects.update_or_create(
                                    payment_id=str(payment_id),
                                    defaults={
                                        "appointment": appointment,
                                        "amount": Decimal(str(transaction_amount)),
                                        "status": api_status,
                                    }
                                )
                            except Exception as trans_err:
                                mp_logger.error(
                                    f"Error al registrar PaymentTransaction en fallback para pago {payment_id}: {str(trans_err)}"
                                )

                            if api_status == 'approved' and api_ext_ref == str(appointment.id):
                                from django.db import transaction
                                try:
                                    with transaction.atomic():
                                        # Bloquear la fila del turno para evitar concurrencia
                                        appointment_locked = Appointment.objects.select_for_update().get(pk=appointment.id)
                                        
                                        if appointment_locked.status != 'CONFIRMED':
                                            # Verificar si ya existe otro turno CONFIRMADO que se superpone con este
                                            has_overlap = Appointment.objects.filter(
                                                service__hairdresser=appointment_locked.service.hairdresser,
                                                status="CONFIRMED",
                                                start_time__lt=appointment_locked.end_time,
                                                end_time__gt=appointment_locked.start_time,
                                            ).exclude(pk=appointment_locked.id).exists()

                                            if has_overlap:
                                                # El turno ya fue ocupado: cancelar y reembolsar
                                                appointment_locked.status = 'CANCELLED'
                                                appointment_locked.amount_paid = Decimal(str(transaction_amount))
                                                appointment_locked.mercadopago_payment_id = str(payment_id)
                                                appointment_locked.expires_at = None
                                                appointment_locked.save()

                                                # Realizar reembolso en MercadoPago
                                                try:
                                                    refund_url = f"https://api.mercadopago.com/v1/payments/{payment_id}/refunds"
                                                    refund_resp = requests.post(refund_url, headers=headers, json={}, timeout=10)
                                                    refund_resp.raise_for_status()
                                                    messages.warning(request, "El turno seleccionado ya fue confirmado por otro usuario. Se ha realizado un reembolso automático a tu cuenta.")
                                                except Exception as refund_err:

                                                    mp_logger.error(f"Error reembolsando pago {payment_id} para turno {appointment_locked.id}: {str(refund_err)}")
                                                    # Registrar reembolso pendiente
                                                    from core.models import PendingRefund
                                                    PendingRefund.objects.get_or_create(
                                                        appointment=appointment_locked,
                                                        defaults={
                                                            'payment_id': payment_id,
                                                            'amount': Decimal(str(transaction_amount)),
                                                            'last_error': str(refund_err)
                                                        }
                                                    )
                                                    messages.error(request, "El turno ya no está disponible. No se pudo procesar tu reembolso automático en este momento, pero el sistema lo reintentará automáticamente. Por favor contacta al local.")

                                                # Notificar al cliente
                                                from core.utils import notify_user
                                                notify_user(
                                                    user=appointment_locked.client,
                                                    event_type="APPOINTMENT_CANCELLED_CLIENT",
                                                    context={"appointment": appointment_locked, "overbooked_refund": True},
                                                    subject="Reembolso de Turno - Stilo",
                                                    push_title="Turno cancelado y reembolsado",
                                                    push_message=f"Tu turno en {appointment_locked.service.hairdresser.name} no estaba disponible y fue reembolsado automáticamente."
                                                )
                                            else:
                                                # Verificar que el monto pagado sea suficiente
                                                expected_amount = appointment_locked.get_expected_payment_amount()
                                                paid_amount = Decimal(str(transaction_amount))

                                                if paid_amount < expected_amount:
                                                    # Pago insuficiente: cancelar y reembolsar automáticamente
                                                    appointment_locked.status = 'CANCELLED'
                                                    appointment_locked.amount_paid = paid_amount
                                                    appointment_locked.mercadopago_payment_id = str(payment_id)
                                                    appointment_locked.expires_at = None
                                                    appointment_locked.save()

                                                    # Realizar reembolso en MercadoPago
                                                    try:
                                                        refund_url = f"https://api.mercadopago.com/v1/payments/{payment_id}/refunds"
                                                        refund_resp = requests.post(refund_url, headers=headers, json={}, timeout=10)
                                                        refund_resp.raise_for_status()
                                                        messages.error(request, "El pago realizado es insuficiente. Se ha cancelado el turno y se ha realizado un reembolso automático a tu cuenta.")
                                                    except Exception as refund_err:

                                                        mp_logger.error(f"Error reembolsando pago insuficiente {payment_id} para turno {appointment_locked.id}: {str(refund_err)}")
                                                        # Registrar reembolso pendiente
                                                        from core.models import PendingRefund
                                                        PendingRefund.objects.get_or_create(
                                                            appointment=appointment_locked,
                                                            defaults={
                                                                'payment_id': payment_id,
                                                                'amount': paid_amount,
                                                                'last_error': str(refund_err)
                                                            }
                                                        )
                                                        messages.error(request, "El pago realizado es insuficiente. No se pudo procesar tu reembolso automático en este momento, pero el sistema lo reintentará automáticamente. Por favor contacta al local.")

                                                    # Notificar al cliente
                                                    from core.utils import notify_user
                                                    notify_user(
                                                        user=appointment_locked.client,
                                                        event_type="APPOINTMENT_CANCELLED_CLIENT",
                                                        context={"appointment": appointment_locked, "underpaid_refund": True},
                                                        subject="Reembolso de Turno - Stilo",
                                                        push_title="Turno cancelado por pago insuficiente",
                                                        push_message=f"Tu turno en {appointment_locked.service.hairdresser.name} fue cancelado y reembolsado porque el pago fue menor al requerido."
                                                    )
                                                else:
                                                    # Confirmar normalmente
                                                    appointment_locked.status = 'CONFIRMED'
                                                    appointment_locked.amount_paid = paid_amount
                                                    appointment_locked.mercadopago_payment_id = str(payment_id)
                                                    appointment_locked.expires_at = None
                                                    appointment_locked.save()
                                                    messages.success(request, "¡Tu pago ha sido acreditado y tu turno está confirmado!")
                                except Exception as e:

                                    mp_logger.error(f"Error procesando confirmación atómica en vista: {str(e)}")

            except Appointment.DoesNotExist:
                pass
            except Exception as e:

                mp_logger.error(f"Error en fallback de MercadoPago en AppointmentListView: {str(e)}")

        return super().get(request, *args, **kwargs)

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


class OwnerAppointmentListView(OwnerRequiredMixin, ListView):
    """
    Vista de gestión de turnos exclusiva para owners.
    Muestra todos los turnos de su peluquería con filtros por estado y fecha.
    """
    model = Appointment
    template_name = "owner_appointments.html"
    context_object_name = "appointments"
    paginate_by = 25

    def get_queryset(self):
        hairdresser = self.request.user.hairdresser_profile  # type: ignore
        qs = (
            Appointment.objects.filter(service__hairdresser=hairdresser)
            .select_related("client", "service", "review")
            .order_by("-start_time")
        )

        # Filtro por estado
        status_filter = self.request.GET.get("status", "")
        if status_filter:
            qs = qs.filter(status=status_filter)

        # Filtro por fecha (mes, formato YYYY-MM)
        month_str = self.request.GET.get("month", "")
        if month_str:
            try:
                from datetime import datetime as dt
                selected = dt.strptime(month_str, "%Y-%m").date()
                import calendar
                _, num_days = calendar.monthrange(selected.year, selected.month)
                qs = qs.filter(
                    start_time__date__gte=selected.replace(day=1),
                    start_time__date__lte=selected.replace(day=num_days),
                )
            except ValueError:
                pass

        return qs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["status_filter"] = self.request.GET.get("status", "")
        context["month_filter"] = self.request.GET.get("month", "")
        context["status_choices"] = Appointment.STATUS_CHOICES
        # Contadores por estado para el resumen rápido
        hairdresser = self.request.user.hairdresser_profile  # type: ignore
        context["pending_count"] = Appointment.objects.filter(
            service__hairdresser=hairdresser, status="PENDING", expires_at__isnull=True
        ).count()
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
    
    q = request.GET.get("q", "").strip()
    service = request.GET.get("service", "").strip()
    
    if q:
        hairdressers = hairdressers.filter(
            Q(name__icontains=q) |
            Q(address__icontains=q) |
            Q(description__icontains=q)
        )
        
    if service:
        if service == "corte":
            hairdressers = hairdressers.filter(services__name__icontains="corte")
        elif service == "color":
            hairdressers = hairdressers.filter(
                Q(services__name__icontains="color") |
                Q(services__name__icontains="tinte") |
                Q(services__name__icontains="mechas")
            )
        elif service == "barberia":
            hairdressers = hairdressers.filter(
                Q(services__name__icontains="barba") |
                Q(services__name__icontains="barber")
            )
        elif service == "peinado":
            hairdressers = hairdressers.filter(
                Q(services__name__icontains="peinado") |
                Q(services__name__icontains="secado")
            )
        elif service == "tratamientos":
            hairdressers = hairdressers.filter(
                Q(services__name__icontains="tratamiento") |
                Q(services__name__icontains="keratina")
            )
            
    # Sincronizar con is_complete()
    hairdressers = hairdressers.prefetch_related("working_hours", "services").distinct()
    complete_hairdressers = [h for h in hairdressers if h.is_complete()]
    
    data = [
        {
            "name": h.name,
            "lat": h.latitude,
            "lon": h.longitude,
            "url": reverse("hairdresser_detail", args=[h.pk]),
        }
        for h in complete_hairdressers
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
def geocode_address_api(request):
    address = request.GET.get("address", "").strip()
    if not address:
        return JsonResponse({"error": "La dirección es requerida."}, status=400)

    coords = geocode_address(address)
    if coords:
        return JsonResponse({
            "success": True,
            "latitude": coords["latitude"],
            "longitude": coords["longitude"],
        })
    else:
        return JsonResponse({
            "success": False,
            "error": "No se pudo encontrar la dirección en el mapa.",
        }, status=404)


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
            status__in=["COMPLETED", "CONFIRMED"],
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
    # Devuelve los turnos de una peluquería como eventos de FullCalendar.
    # Se bloquean:
    #   - CONFIRMED: turnos confirmados.
    #   - PENDING sin expires_at: solicitudes esperando confirmación del dueño (ocupan el slot).
    # No se bloquean los PENDING con expires_at (checkout de pago en curso, expiran solos).
    from django.db.models import Q
    appointments = Appointment.objects.filter(
        service__hairdresser_id=hairdresser_id,
    ).filter(
        Q(status="CONFIRMED") |
        Q(status="PENDING", expires_at__isnull=True)
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
        response = super().form_valid(form)
        user = self.request.user
        if user.email:
            from core.utils import notify_user
            notify_user(
                user=user,
                event_type="PASSWORD_CHANGED",
                context={"user": user},
                subject="Confirmación de seguridad: Cambio de contraseña - Stilo",
            )
        messages.success(self.request, "Tu contraseña ha sido cambiada exitosamente.")
        return response



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
            "override_deposit": service.override_deposit,
            "deposit_type": service.deposit_type,
            "deposit_value": str(service.deposit_value),
            "override_payment_modes": service.override_payment_modes,
            "allow_prepayment": service.allow_prepayment,
            "allow_on_site_payment": service.allow_on_site_payment,
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

        # Separar los turnos finalizados (completados, ausentes o cancelados) de los activos
        active_appointments = []
        for app in appointments_today:
            if app.status in ["COMPLETED", "NO_SHOW", "CANCELLED"]:
                completed_appointments.append(app)
            else:
                active_appointments.append(app)

        # Clasificar los turnos activos cronológicamente
        for app in active_appointments:
            # Si el turno ya comenzó (o debió comenzar) y aún no tenemos un turno actual en curso, se asigna como actual
            if app.start_time <= now and not current_appointment:
                current_appointment = app
            else:
                # Si empieza en el futuro, o si ya tenemos un turno en curso, se asigna como siguiente o futuro
                if not next_appointment:
                    next_appointment = app
                else:
                    upcoming_appointments.append(app)

        context["current_appointment"] = current_appointment
        context["next_appointment"] = next_appointment
        context["upcoming_appointments"] = upcoming_appointments
        context["completed_appointments"] = completed_appointments
        context["hairdresser"] = hairdresser

        # Cantidad de solicitudes pendientes de confirmación manual para otros días
        context["pending_requests_count"] = (
            Appointment.objects.filter(
                service__hairdresser=hairdresser,
                status="PENDING",
                expires_at__isnull=True,
            )
            .exclude(start_time__date=today)  # las de hoy ya aparecen arriba
            .count()
        )
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
        
        # Validar que se envió un status
        if not new_status:
            return JsonResponse(
                {"status": "error", "message": "Status es requerido."}, status=400
            )
        
        # Estados finales que no pueden cambiar
        if appointment.status in ["COMPLETED", "NO_SHOW"]:
            status_labels = dict(Appointment.STATUS_CHOICES)
            status_label = status_labels.get(appointment.status, appointment.status)
            return JsonResponse(
                {"status": "error", "message": f"No se puede cambiar un turno en estado {status_label}."}, status=400
            )
        
        # Definir transiciones válidas según el estado actual
        valid_statuses = []
        
        if appointment.status == "PENDING":
            # Desde PENDING: confirmar, cancelar, marcar como no presentado o completar directamente
            valid_statuses = ["CONFIRMED", "CANCELLED", "NO_SHOW", "COMPLETED"]
        elif appointment.status == "CONFIRMED":
            # Desde CONFIRMED: marcar como completado, cancelar o no se presentó
            valid_statuses = ["COMPLETED", "CANCELLED", "NO_SHOW"]
        elif appointment.status == "CANCELLED":
            # Ya está cancelado
            return JsonResponse(
                {"status": "error", "message": "Este turno ya fue cancelado."}, status=400
            )
        else:
            # Estado desconocido
            return JsonResponse(
                {"status": "error", "message": f"Estado del turno desconocido: {appointment.status}"}, status=400
            )

        if new_status not in valid_statuses:
            return JsonResponse(
                {"status": "error", "message": f"No se puede cambiar a estado '{new_status}' desde '{appointment.status}'."}, status=400
            )
        
        # Si se cancela un turno pagado por MercadoPago, procesar refund PRIMERO
        refund_status = None
        if new_status == "CANCELLED" and appointment.amount_paid > 0:
            from core.utils import process_mercadopago_refund, get_mercadopago_payment_id_from_api
            from decimal import Decimal

            
            # Si no tiene payment_id guardado, intentar obtenerlo de la API (fallback)
            payment_id = appointment.mercadopago_payment_id
            if not payment_id:
                mp_logger.info(f"[CANCEL] No hay payment_id guardado, intentando obtenerlo de MercadoPago...")
                payment_id = get_mercadopago_payment_id_from_api(
                    hairdresser=appointment.service.hairdresser,
                    appointment_id=appointment.id
                )
                if payment_id:
                    # Guardar el payment_id para futuras referencias
                    appointment.mercadopago_payment_id = payment_id
                    appointment.save(update_fields=['mercadopago_payment_id'])
                    mp_logger.info(f"[CANCEL] payment_id obtenido y guardado: {payment_id}")
            
            if payment_id:
                mp_logger.info(f"[CANCEL] Iniciando refund para appointment {pk}: payment_id={payment_id}, amount={appointment.amount_paid}")
                
                refund_result = process_mercadopago_refund(
                    hairdresser=appointment.service.hairdresser,
                    payment_id=payment_id,
                    amount=Decimal(str(appointment.amount_paid))
                )
                
                mp_logger.info(f"[CANCEL] Refund result: {refund_result}")
                
                if refund_result['success']:
                    refund_status = 'success'
                    mp_logger.info(f"[CANCEL] Refund successful: {refund_result['refund_id']}")
                    # Refund exitoso, continuar con la cancelación
                else:
                    # REFUND FALLÓ - Cancelamos el turno igualmente y encolamos el reembolso
                    refund_status = 'pending'
                    error_detail = refund_result.get('error', 'Error desconocido')
                    mp_logger.error(f"[CANCEL] Refund failed - Enqueuing pending refund: {error_detail}")
                    from core.models import PendingRefund
                    PendingRefund.objects.get_or_create(
                        appointment=appointment,
                        defaults={
                            'payment_id': payment_id,
                            'amount': Decimal(str(appointment.amount_paid)),
                            'last_error': error_detail
                        }
                    )
            else:
                # No se encontró payment_id - No cancelar si hay dinero
                mp_logger.warning(f"[CANCEL] No se pudo obtener payment_id para refund - NO cancelling appointment")
                return JsonResponse({
                    "status": "error", 
                    "message": f"No se pudo localizar el pago en MercadoPago para procesar el reembolso de ${appointment.amount_paid}. El turno NO fue cancelado. Por favor contacta a soporte."
                }, status=402)
        elif new_status == "CANCELLED":

            mp_logger.info(f"[CANCEL] Cancelando turno sin refund: amount_paid={appointment.amount_paid}, payment_id={appointment.mercadopago_payment_id}")
        
        # SOLO guardar cambio de estado si no hay error (refunds exitosos o sin dinero)
        appointment.status = new_status
        appointment.save()
        
        # Respuesta de éxito
        response_msg = "Turno actualizado."
        if new_status == "CANCELLED":
            if refund_status == 'success':
                response_msg = f"✓ Turno cancelado y reembolso de ${appointment.amount_paid} procesado exitosamente."
            elif refund_status == 'pending':
                response_msg = f"✓ Turno cancelado. El reembolso de ${appointment.amount_paid} falló y se reintentará automáticamente."
            else:
                response_msg = "✓ Turno cancelado."
        elif new_status == "COMPLETED":
            # Verificar si se completó antes de tiempo y ofrecer al próximo
            now = timezone.now()
            if now < appointment.end_time:
                minutes_early = int(round((appointment.end_time - now).total_seconds() / 60))
                if minutes_early >= 5:
                    # Buscar el próximo turno del día
                    next_app = Appointment.objects.filter(
                        service__hairdresser=appointment.service.hairdresser,
                        start_time__date=now.date(),
                        start_time__gt=now
                    ).exclude(status__in=["COMPLETED", "NO_SHOW", "CANCELLED"]).order_by("start_time").first()

                    if next_app:
                        import uuid
                        from datetime import timedelta
                        from core.models import EarlyStartOffer
                        from core.utils import notify_user
                        
                        token = str(uuid.uuid4())
                        # La oferta propone adelantar el turno al momento actual (now)
                        offer = EarlyStartOffer.objects.create(
                            appointment=next_app,
                            token=token,
                            minutes_available=minutes_early,
                            new_start_time=now,
                            expires_at=now + timedelta(minutes=2)
                        )
                        accept_url = request.build_absolute_uri(
                            reverse("accept_early_start", kwargs={"token": offer.token})
                        )
                        # Notificar al cliente
                        notify_user(
                            user=next_app.client,
                            event_type="APPOINTMENT_EARLY_OFFER",
                            context={"appointment": next_app, "offer": offer, "accept_url": accept_url},
                            subject="¡Adelantá tu Turno! - Stilo"
                        )
                        response_msg = f"✓ Turno completado {minutes_early} min antes. Se ofreció adelantar el horario al próximo cliente."
                    else:
                        response_msg = f"✓ Turno completado {minutes_early} min antes."
                else:
                    response_msg = f"✓ Turno completado."
            else:
                response_msg = "✓ Turno completado."
        
        return JsonResponse({"status": "success", "message": response_msg})

    except Exception as e:
        return JsonResponse({"status": "error", "message": str(e)}, status=500)


@login_required
@require_POST
def adjust_appointment_time(request, pk):
    if not request.user.is_owner:
        return JsonResponse(
            {"status": "error", "message": "Permission denied"}, status=403
        )

    try:
        appointment = get_object_or_404(
            Appointment, pk=pk, service__hairdresser=request.user.hairdresser_profile
        )

        delta = request.POST.get("delta")
        if not delta:
            return JsonResponse(
                {"status": "error", "message": "Delta es requerido."}, status=400
            )

        try:
            delta_mins = int(delta)
        except ValueError:
            return JsonResponse(
                {"status": "error", "message": "Delta debe ser un entero."}, status=400
            )

        # No permitir reducir por debajo de la duración original del servicio
        new_extra = appointment.extra_minutes + delta_mins
        if appointment.service.duration_minutes + new_extra < 5:
            return JsonResponse(
                {"status": "error", "message": "La duración total del turno no puede ser menor a 5 minutos."},
                status=400
            )

        # Actualizar extra_minutes
        appointment.extra_minutes = new_extra
        appointment.save()

        # Reprogramar turnos posteriores en cascada
        from core.utils import reschedule_subsequent_appointments, notify_rescheduled_appointments
        affected_to_notify = reschedule_subsequent_appointments(appointment, delta_mins)
        notify_rescheduled_appointments(affected_to_notify)

        msg = f"Turno ajustado en {delta_mins:+} min. Se reprogramaron turnos posteriores."
        return JsonResponse({"status": "success", "message": msg})

    except Exception as e:
        return JsonResponse({"status": "error", "message": str(e)}, status=500)


def accept_early_start(request, token):
    from core.models import EarlyStartOffer, Appointment
    from django.utils import timezone
    from core.utils import reschedule_subsequent_appointments, notify_rescheduled_appointments

    offer = get_object_or_404(EarlyStartOffer, token=token)

    now = timezone.now()
    if offer.expires_at < now and not offer.accepted:
        # Expirada
        return render(request, "early_start_result.html", {
            "success": False,
            "message": "La oferta de adelanto ha expirado (tenía un límite de 2 minutos)."
        })

    if offer.accepted:
        return render(request, "early_start_result.html", {
            "success": False,
            "message": "Esta oferta ya fue aceptada previamente."
        })

    if offer.appointment.status in ["COMPLETED", "NO_SHOW", "CANCELLED"]:
        return render(request, "early_start_result.html", {
            "success": False,
            "message": "El turno ya no está activo."
        })

    # Aceptar la oferta
    offer.accepted = True
    offer.save()

    # Calcular la diferencia de minutos para reprogramar en cascada
    # de forma negativa (el turno se adelanta!)
    old_start = offer.appointment.start_time
    new_start = offer.new_start_time

    # El cambio en minutos (negativo porque se adelanta)
    delta_mins = int((new_start - old_start).total_seconds() / 60)

    # Actualizar el turno actual de la oferta
    offer.appointment.start_time = new_start
    offer.appointment.save()

    # Reprogramar turnos posteriores en cascada (desplazamiento negativo)
    affected_to_notify = reschedule_subsequent_appointments(offer.appointment, delta_mins)
    notify_rescheduled_appointments(affected_to_notify)

    return render(request, "early_start_result.html", {
        "success": True,
        "appointment": offer.appointment,
        "message": f"¡Excelente! Tu turno ha sido adelantado para las {timezone.localtime(new_start).strftime('%H:%M')} hs."
    })




def send_reminders_view(request):
    """
    Endpoint para enviar recordatorios de turnos programados para el día siguiente.
    Protegido por un token/clave secreta.
    """
    token = request.GET.get("token") or request.headers.get("X-Cron-Secret")
    from django.conf import settings
    if not token or token != settings.CRON_SECRET:
        return JsonResponse({"error": "No autorizado"}, status=403)

    import datetime
    from django.utils import timezone
    from core.utils import notify_user

    # Obtenemos la fecha de mañana en la zona horaria local configurada
    local_now = timezone.localtime(timezone.now())
    tomorrow_date = local_now.date() + datetime.timedelta(days=1)

    # Filtrar solo los turnos CONFIRMED para el día siguiente.
    # Los turnos PENDING que nunca fueron pagados no deben recibir recordatorios.
    appointments = Appointment.objects.filter(
        start_time__date=tomorrow_date,
        status="CONFIRMED"
    ).select_related("client", "service__hairdresser")

    sent_count = 0
    for app in appointments:
        if app.client:
            success = notify_user(
                user=app.client,
                event_type="APPOINTMENT_REMINDER",
                context={"appointment": app},
                subject="Recordatorio de Turno - Stilo",
            )
            if success:
                sent_count += 1

    return JsonResponse({
        "success": True,
        "sent_count": sent_count,
        "total_filtered": appointments.count()
    })


import json
from django.views.decorators.http import require_POST
from django.contrib.auth.decorators import login_required
import os

@login_required
@require_POST
def push_subscribe(request):
    """
    Endpoint para registrar o actualizar suscripciones push del frontend.
    """
    try:
        data = json.loads(request.body)
        endpoint = data.get('endpoint')
        keys = data.get('keys', {})
        p256dh = keys.get('p256dh')
        auth = keys.get('auth')

        if not endpoint or not p256dh or not auth:
            return JsonResponse({'error': 'Parámetros incompletos'}, status=400)

        from core.models import PushSubscription
        
        # Eliminar cualquier suscripción existente con este mismo endpoint para otros usuarios
        PushSubscription.objects.filter(endpoint=endpoint).exclude(user=request.user).delete()

        subscription, created = PushSubscription.objects.update_or_create(
            user=request.user,
            endpoint=endpoint,
            defaults={
                'auth': auth,
                'p256dh': p256dh
            }
        )
        return JsonResponse({'success': True, 'created': created})
    except json.JSONDecodeError:
        return JsonResponse({'error': 'JSON inválido'}, status=400)
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)


@login_required
@require_POST
def push_unsubscribe(request):
    """
    Endpoint para eliminar una suscripción push específica del usuario.
    """
    try:
        data = json.loads(request.body)
        endpoint = data.get('endpoint')
        if not endpoint:
            return JsonResponse({'error': 'Parámetros incompletos'}, status=400)

        from core.models import PushSubscription
        PushSubscription.objects.filter(user=request.user, endpoint=endpoint).delete()
        return JsonResponse({'success': True})
    except json.JSONDecodeError:
        return JsonResponse({'error': 'JSON inválido'}, status=400)
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)


def service_worker(request):
    """
    Sirve el archivo JS del service worker con el tipo MIME correcto desde la raíz.
    """
    from django.conf import settings
    from django.http import HttpResponse
    path = os.path.join(settings.BASE_DIR, 'core', 'static', 'js', 'service-worker.js')
    try:
        with open(path, 'rb') as f:
            return HttpResponse(f.read(), content_type='application/javascript')
    except FileNotFoundError:
        return HttpResponse('Service worker file not found', status=404)


@login_required
def mercadopago_auth_redirect(request):
    from django.conf import settings
    if not request.user.is_owner:
        messages.error(request, "No tienes permisos para realizar esta acción.")
        return redirect("home")
    
    hairdresser = getattr(request.user, "hairdresser_profile", None)
    if not hairdresser:
        messages.error(request, "Perfil de peluquería no encontrado.")
        return redirect("home")

    client_id = getattr(settings, "MERCADOPAGO_CLIENT_ID", None)
    if not client_id:
        messages.error(request, "MercadoPago Client ID no configurado en el servidor.")
        return redirect("my_hairdresser_info")

    redirect_uri = request.build_absolute_uri(reverse("mercadopago_callback"))
    state = str(hairdresser.id)
    
    auth_url = f"https://auth.mercadopago.com.ar/authorization?response_type=code&client_id={client_id}&redirect_uri={redirect_uri}&state={state}"
    return redirect(auth_url)


@login_required
def mercadopago_unlink(request):
    if not request.user.is_owner:
        messages.error(request, "No tienes permisos para realizar esta acción.")
        return redirect("home")
    
    hairdresser = getattr(request.user, "hairdresser_profile", None)
    if not hairdresser:
        messages.error(request, "Perfil de peluquería no encontrado.")
        return redirect("home")

    hairdresser.mercadopago_access_token = ""
    hairdresser.mercadopago_refresh_token = ""
    hairdresser.mercadopago_user_id = ""
    hairdresser.mercadopago_token_expires_at = None
    hairdresser.mercadopago_active = False
    hairdresser.save()
    
    messages.success(request, "Cuenta de MercadoPago desvinculada exitosamente.")
    return redirect("my_hairdresser_info")


@login_required
def mercadopago_callback(request):
    from django.conf import settings
    import requests
    
    if not request.user.is_owner:
        messages.error(request, "No tienes permisos para realizar esta acción.")
        return redirect("home")
    
    code = request.GET.get("code")
    state = request.GET.get("state")
    
    if not code or not state:
        messages.error(request, "Faltan parámetros en la respuesta de MercadoPago.")
        return redirect("my_hairdresser_info")
        
    try:
        hairdresser = Hairdresser.objects.get(pk=state, owner=request.user)
    except Hairdresser.DoesNotExist:
        messages.error(request, "Peluquería no encontrada o no te pertenece.")
        return redirect("home")

    client_id = getattr(settings, "MERCADOPAGO_CLIENT_ID", None)
    client_secret = getattr(settings, "MERCADOPAGO_CLIENT_SECRET", None)
    
    if not client_id or not client_secret:
        messages.error(request, "Credenciales de MercadoPago no configuradas en el servidor.")
        return redirect("my_hairdresser_info")
        
    token_url = "https://api.mercadopago.com/oauth/token"
    payload = {
        "grant_type": "authorization_code",
        "client_id": client_id,
        "client_secret": client_secret,
        "code": code,
        "redirect_uri": request.build_absolute_uri(reverse("mercadopago_callback"))
    }
    if settings.DEBUG:
        payload["test_token"] = "true"
    headers = {
        "accept": "application/json",
        "content-type": "application/x-www-form-urlencoded"
    }
    
    try:
        response = requests.post(token_url, data=payload, headers=headers, timeout=10)
        response.raise_for_status()
        data = response.json()
        
        hairdresser.mercadopago_access_token = data.get("access_token", "")
        hairdresser.mercadopago_refresh_token = data.get("refresh_token", "")
        hairdresser.mercadopago_user_id = str(data.get("user_id", ""))
        
        expires_in = data.get("expires_in")
        from django.utils import timezone
        from datetime import timedelta
        if expires_in:
            hairdresser.mercadopago_token_expires_at = timezone.now() + timedelta(seconds=int(expires_in))
        else:
            hairdresser.mercadopago_token_expires_at = timezone.now() + timedelta(days=180)
            
        hairdresser.mercadopago_active = True
        hairdresser.save()
        
        messages.success(request, "¡Cuenta de MercadoPago vinculada exitosamente!")
    except requests.exceptions.HTTPError as http_err:

        try:
            error_data = response.json()
            error_msg = error_data.get("message") or error_data.get("error_description") or str(http_err)
        except Exception:
            error_msg = str(http_err)
        mp_logger.error(f"Error swapping oauth code for token: {error_msg}")
        messages.error(request, f"Error al vincular con MercadoPago: {error_msg}")
    except Exception as e:

        mp_logger.error(f"Error swapping oauth code for token: {str(e)}")
        messages.error(request, f"Error al vincular con MercadoPago: {str(e)}")
        
    return redirect("my_hairdresser_info")


def cancel_expired_appointments_view(request):
    """
    Endpoint para cancelar los turnos PENDING cuyo tiempo de espera de pago ha expirado.
    Protegido por token/clave secreta.
    """
    token = request.GET.get("token") or request.headers.get("X-Cron-Secret")
    from django.conf import settings
    if not token or token != settings.CRON_SECRET:
        return JsonResponse({"error": "No autorizado"}, status=403)

    from django.utils import timezone
    from core.models import Appointment

    now = timezone.now()
    cron_logger.info("[CRON] Ejecutando cancel-expired-appointments")
    expired = Appointment.objects.filter(
        status="PENDING",
        expires_at__isnull=False,
        expires_at__lt=now,
    )

    count = expired.count()
    cancelled = 0
    for app in expired:
        try:
            app.status = "CANCELLED"
            app.save()
            cancelled += 1
        except Exception as e:
            cron_logger.error(f"Error al cancelar turno #{app.pk}: {e}")

    cron_logger.info(f"[CRON] cancel-expired finalizado: procesados={count}, cancelados={cancelled}")
    return JsonResponse({
        "status": "success",
        "processed": count,
        "cancelled": cancelled
    })


def retry_refunds_cron_view(request):
    """
    Endpoint cron para procesar la cola de reembolsos pendientes.
    Protegido por token/clave secreta.
    """
    token = request.GET.get("token") or request.headers.get("X-Cron-Secret")
    from django.conf import settings
    if not token or token != settings.CRON_SECRET:
        return JsonResponse({"error": "No autorizado"}, status=403)

    from core.models import PendingRefund
    from core.utils import process_mercadopago_refund

    # Reintentar aquellos con menos de 5 intentos
    cron_logger.info("[CRON] Ejecutando retry-refunds")
    pending_refunds = PendingRefund.objects.filter(attempts__lt=5)
    processed = pending_refunds.count()
    succeeded = 0
    failed = 0

    for pr in pending_refunds:
        try:
            pr.attempts += 1
            # Realizar el reembolso llamando al helper común
            res = process_mercadopago_refund(
                hairdresser=pr.appointment.service.hairdresser,
                payment_id=pr.payment_id,
                amount=pr.amount
            )
            if res['success']:
                pr.delete()  # Si se reembolsó correctamente, se elimina de la cola
                succeeded += 1
            else:
                pr.last_error = res.get('error', 'Error desconocido')
                pr.save()
                failed += 1
        except Exception as e:
            pr.last_error = str(e)
            pr.save()
            failed += 1

    cron_logger.info(f"[CRON] retry-refunds finalizado: procesados={processed}, exitosos={succeeded}, fallidos={failed}")
    return JsonResponse({
        "status": "success",
        "processed": processed,
        "succeeded": succeeded,
        "failed": failed
    })


def developer_required(view_func):
    """
    Decorador que permite el acceso solo si DEBUG=True o si el usuario es staff/superuser.
    """
    from django.conf import settings
    from django.http import HttpResponseForbidden

    def _wrapped_view(request, *args, **kwargs):
        if settings.DEBUG or (request.user.is_authenticated and (request.user.is_staff or request.user.is_superuser)):
            return view_func(request, *args, **kwargs)
        return HttpResponseForbidden("Acceso restringido a desarrolladores.")
    return _wrapped_view


@developer_required
def email_preview_list(request):
    templates = [
        ("WELCOME", "emails/welcome.html", "Bienvenida a nuevos usuarios"),
        ("PASSWORD_CHANGED", "emails/password_changed.html", "Cambio de contraseña"),
        ("APPOINTMENT_REQUEST_CLIENT", "emails/appointment_request_client.html", "Solicitud recibida (Cliente)"),
        ("APPOINTMENT_REQUEST_OWNER", "emails/appointment_request_owner.html", "Nueva solicitud recibida (Dueño)"),
        ("APPOINTMENT_SUCCESS_CLIENT", "emails/appointment_success_client.html", "Confirmación de turno (Cliente)"),
        ("APPOINTMENT_SUCCESS_OWNER", "emails/appointment_success_owner.html", "Nueva reserva confirmada (Dueño)"),
        ("APPOINTMENT_CANCELLED_CLIENT", "emails/appointment_cancelled_client.html", "Turno cancelado (Cliente)"),
        ("APPOINTMENT_CANCELLED_OWNER", "emails/appointment_cancelled_owner.html", "Reserva cancelada (Dueño)"),
        ("APPOINTMENT_REMINDER", "emails/appointment_reminder.html", "Recordatorio de turno"),
    ]
    return render(request, "debug_email_list.html", {"templates": templates})


from django.views.decorators.clickjacking import xframe_options_exempt

@xframe_options_exempt
@developer_required
def email_preview_render(request, template_name):
    template_map = {
        'WELCOME': 'emails/welcome.html',
        'PASSWORD_CHANGED': 'emails/password_changed.html',
        'APPOINTMENT_REQUEST_CLIENT': 'emails/appointment_request_client.html',
        'APPOINTMENT_REQUEST_OWNER': 'emails/appointment_request_owner.html',
        'APPOINTMENT_SUCCESS_CLIENT': 'emails/appointment_success_client.html',
        'APPOINTMENT_SUCCESS_OWNER': 'emails/appointment_success_owner.html',
        'APPOINTMENT_CANCELLED_CLIENT': 'emails/appointment_cancelled_client.html',
        'APPOINTMENT_CANCELLED_OWNER': 'emails/appointment_cancelled_owner.html',
        'APPOINTMENT_REMINDER': 'emails/appointment_reminder.html',
    }

    path = template_map.get(template_name)
    if not path:
        raise Http404("Plantilla no encontrada")

    # Crear objetos mock
    dummy_owner = User(first_name="Diego", last_name="Maradona", email="owner@stilo.com", username="diego")
    dummy_client = User(first_name="Lionel", last_name="Messi", email="client@stilo.com", username="leo")
    
    # Hairdresser
    payment_state = request.GET.get("payment_state", "full")
    requires_deposit = (payment_state == "deposit")
    mercadopago_active = (payment_state in ["full", "deposit"])

    dummy_hairdresser = Hairdresser(
        owner=dummy_owner,
        name="Estilo & Clase",
        address="Av. Siempre Viva 742, Springfield",
        phone_number="+54 387 1234567",
        requires_deposit=requires_deposit,
        mercadopago_active=mercadopago_active,
        default_deposit_type="PERCENTAGE",
        default_deposit_value=Decimal("20.00")
    )
    
    # Service
    dummy_service = Service(
        hairdresser=dummy_hairdresser,
        name="Corte Masculino + Barba",
        price=Decimal("1500.00"),
        duration_minutes=45
    )
    
    # Appointment parameters based on query string
    if payment_state == "full":
        payment_method = "FULL"
        amount_paid = Decimal("1500.00")
    elif payment_state == "deposit":
        payment_method = "CASH"
        amount_paid = Decimal("300.00")
    else: # cash
        payment_method = "CASH"
        amount_paid = Decimal("0.00")

    dummy_app = Appointment(
        client=dummy_client,
        service=dummy_service,
        start_time=timezone.now() + timedelta(days=1),
        end_time=timezone.now() + timedelta(days=1, minutes=45),
        amount=Decimal("1500.00"),
        payment_method=payment_method,
        amount_paid=amount_paid,
        status="CONFIRMED" if template_name not in ["APPOINTMENT_CANCELLED_CLIENT", "APPOINTMENT_CANCELLED_OWNER"] else "CANCELLED"
    )

    context = {
        "user": dummy_client,
        "login_url": request.build_absolute_uri("/login/"),
        "appointment": dummy_app,
        "overbooked_refund": request.GET.get("overbooked_refund") == "true",
    }
    return render(request, path, context)


def refresh_mercadopago_tokens_cron_view(request):
    """
    Endpoint de cron para renovar de forma automática los tokens de MercadoPago
    próximos a expirar (menos de 30 días restantes) o vacíos (para compatibilidad).
    """
    token = request.GET.get("token") or request.headers.get("X-Cron-Secret")
    from django.conf import settings
    if not token or token != settings.CRON_SECRET:
        return JsonResponse({"error": "No autorizado"}, status=403)

    from core.models import Hairdresser
    from django.utils import timezone
    from datetime import timedelta
    from django.db.models import Q

    cron_logger.info("[CRON] Ejecutando refresh-mercadopago-tokens")

    # Buscar peluquerías que expiren en menos de 30 días o que tengan el campo nulo pero tengan refresh_token
    limit_date = timezone.now() + timedelta(days=30)
    to_refresh = Hairdresser.objects.filter(
        mercadopago_active=True
    ).exclude(
        mercadopago_refresh_token=""
    ).filter(
        Q(mercadopago_token_expires_at__isnull=True) |
        Q(mercadopago_token_expires_at__lt=limit_date)
    )

    processed = to_refresh.count()
    succeeded = 0
    failed = 0
    errors = []

    from core.utils import refresh_mercadopago_token

    for hd in to_refresh:
        try:
            refresh_mercadopago_token(hd)
            succeeded += 1
        except Exception as e:
            failed += 1
            err_msg = f"Error al renovar token para Peluquería ID {hd.pk}: {str(e)}"
            cron_logger.error(err_msg)
            errors.append(err_msg)

    return JsonResponse({
        "status": "success",
        "processed": processed,
        "succeeded": succeeded,
        "failed": failed,
        "errors": errors
    })


