import logging
import requests

logger = logging.getLogger(__name__)
mp_logger = logging.getLogger('mp')


def get_ip(request):
    """Obtiene la IP real del usuario, incluso si está detrás de un proxy."""
    x_forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR")
    if x_forwarded_for:
        ip = x_forwarded_for.split(",")[0]
    else:
        ip = request.META.get("REMOTE_ADDR")
    return ip


def get_location_from_ip(request):
    """Obtiene latitud y longitud a partir de la IP del usuario usando ipinfo.io."""
    ip = get_ip(request)

    # Coordenadas de fallback por defecto (si todo lo demás falla)
    default_coords = {"lat": -34.6037, "lon": -58.3816}  # Buenos Aires

    # No se puede geolocalizar una IP local, devolvemos el fallback.
    if ip == "127.0.0.1" or ip == "localhost":
        return default_coords

    try:
        # Hacemos la llamada a la API
        response = requests.get(f"https://ipinfo.io/{ip}/json", timeout=3)
        response.raise_for_status()  # Lanza un error si la respuesta es 4xx o 5xx
        data = response.json()

        # Parseamos las coordenadas
        if "loc" in data:
            lat, lon = data["loc"].split(",")
            return {"lat": float(lat), "lon": float(lon)}
        else:
            return default_coords

    except (requests.RequestException, ValueError, KeyError) as e:
        # Si la API falla, el JSON es inválido o no tiene 'loc', usamos el fallback
        logger.error(f"Error getting location from IP {ip}: {e}")
        return default_coords


def geocode_address(address):
    """
    Geocodifica una dirección usando la API de Nominatim (OpenStreetMap).
    Retorna un diccionario con 'latitude' y 'longitude', o None si falla.
    """
    if not address or not isinstance(address, str) or not address.strip():
        return None

    url = "https://nominatim.openstreetmap.org/search"
    params = {"q": address.strip(), "format": "json", "limit": 1}
    headers = {
        "User-Agent": "Stilo Hairdresser App (UNSa Desarrollo Web; contacto@stilo.com)"
    }

    try:
        response = requests.get(url, params=params, headers=headers, timeout=5)
        response.raise_for_status()
        results = response.json()

        if results and isinstance(results, list) and len(results) > 0:
            return {
                "latitude": float(results[0]["lat"]),
                "longitude": float(results[0]["lon"]),
            }
        return None
    except Exception as e:
        logger.error(f"Error in geocode_address: {e}")
        return None


from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string
from django.utils.html import strip_tags
from django.conf import settings



def send_html_email(subject, template_name, context, recipient_list):
    """
    Envía un correo electrónico con contenido HTML y una alternativa de texto plano.
    """
    try:
        html_content = render_to_string(template_name, context)
        text_content = strip_tags(html_content)

        from_email = getattr(
            settings,
            "DEFAULT_FROM_EMAIL",
            "webmaster@localhost",
        )

        email = EmailMultiAlternatives(
            subject, text_content, from_email, recipient_list
        )
        email.attach_alternative(html_content, "text/html")
        email.send()
        return True
    except Exception as e:
        logger.error(f"Error al enviar correo ({subject}): {e}")
        return False


from pywebpush import webpush, WebPushException
import json
import threading
from django.db import connection
from django.utils import timezone


def send_push_to_subscription(subscription, title, message):
    """
    Envía una notificación push a una suscripción específica usando pywebpush.
    """
    subscription_info = {
        "endpoint": subscription.endpoint,
        "keys": {"p256dh": subscription.p256dh, "auth": subscription.auth},
    }

    vapid_private_key = getattr(settings, "VAPID_PRIVATE_KEY", None)
    if not vapid_private_key:
        logger.error("VAPID_PRIVATE_KEY no está configurada en settings.")
        return

    try:
        webpush(
            subscription_info=subscription_info,
            data=json.dumps(
                {
                    "title": title,
                    "body": message,
                }
            ),
            vapid_private_key=vapid_private_key,
            vapid_claims={
                "sub": "mailto:contacto@stilo.com",
            },
        )
    except WebPushException as ex:
        # Si la suscripción ha expirado o es inválida, la removemos de la base de datos (404 Not Found o 410 Gone)
        if ex.response is not None and ex.response.status_code in [404, 410]:
            logger.info(f"Removiendo suscripción inactiva/expirada {subscription.id}.")
            subscription.delete()
        else:
            logger.error(
                f"Error al enviar notificación push a la suscripción {subscription.id}: {ex}"
            )
    except Exception as ex:
        logger.error(
            f"Error inesperado al enviar push a la suscripción {subscription.id}: {ex}"
        )


def _send_push_notification_thread(user_id, title, message):
    """
    Función de hilo para buscar y enviar notificaciones en segundo plano,
    liberando la conexión de base de datos al finalizar (excepto en tests).
    """
    from core.models import PushSubscription
    from django.contrib.auth import get_user_model
    import sys

    try:
        User = get_user_model()
        try:
            user = User.objects.get(pk=user_id)
        except User.DoesNotExist:
            return

        subscriptions = list(PushSubscription.objects.filter(user=user))
        for sub in subscriptions:
            send_push_to_subscription(sub, title, message)
    except Exception as e:
        logger.error(
            f"Error en el hilo de notificaciones push para el usuario {user_id}: {e}"
        )
    finally:
        # No cerrar la conexión en modo testing para no invalidar la conexión de la suite de pruebas
        if "test" not in sys.argv:
            connection.close()


def send_push_notification(user, title, message):
    """
    Busca todas las suscripciones activas del usuario y realiza el envío a cada dispositivo en segundo plano.
    En modo de pruebas, se ejecuta de manera síncrona para evitar bloqueos en SQLite.
    """
    if not user or not user.pk:
        return

    import sys

    if "test" in sys.argv:
        # Ejecutar sincrónicamente durante las pruebas unitarias
        _send_push_notification_thread(user.pk, title, message)
    else:
        thread = threading.Thread(
            target=_send_push_notification_thread, args=(user.pk, title, message)
        )
        thread.daemon = True
        thread.start()


def notify_user(user, event_type, context, subject, push_title=None, push_message=None):
    """
    Función centralizada para despachar notificaciones a través de diferentes canales (Email, Push, etc.).
    """
    if not user:
        return False

    success = False

    # 1. Enviar correo electrónico
    template_map = {
        "WELCOME": "emails/welcome.html",
        "PASSWORD_CHANGED": "emails/password_changed.html",
        "APPOINTMENT_REQUEST_CLIENT": "emails/appointment_request_client.html",
        "APPOINTMENT_REQUEST_OWNER": "emails/appointment_request_owner.html",
        "APPOINTMENT_SUCCESS_CLIENT": "emails/appointment_success_client.html",
        "APPOINTMENT_SUCCESS_OWNER": "emails/appointment_success_owner.html",
        "APPOINTMENT_CANCELLED_CLIENT": "emails/appointment_cancelled_client.html",
        "APPOINTMENT_CANCELLED_OWNER": "emails/appointment_cancelled_owner.html",
        "APPOINTMENT_REMINDER": "emails/appointment_reminder.html",
        "APPOINTMENT_RESCHEDULED_CLIENT": "emails/appointment_rescheduled_client.html",
        "APPOINTMENT_EARLY_OFFER": "emails/appointment_early_offer_client.html",
    }

    template_name = template_map.get(event_type)
    if template_name and getattr(user, "email", None):
        # Clonar context e inyectar URLs útiles absolutas
        context = dict(context or {})
        from django.urls import reverse
        base_url = settings.SITE_URL.rstrip("/")
        context.setdefault("site_url", base_url)
        context.setdefault("home_url", f"{base_url}{reverse('home')}")
        context.setdefault("my_appointments_url", f"{base_url}{reverse('my_appointments')}")
        context.setdefault("owner_appointments_url", f"{base_url}{reverse('owner_appointments')}")
        context.setdefault("workstation_url", f"{base_url}{reverse('workstation')}")
        context.setdefault("login_url", f"{base_url}{reverse('login')}")

        success = send_html_email(
            subject=subject,
            template_name=template_name,
            context=context,
            recipient_list=[user.email],
        )

    # 2. Notificaciones Push
    if not push_title or not push_message:
        appointment = context.get("appointment")
        if appointment:
            service_name = appointment.service.name
            hairdresser_name = appointment.service.hairdresser.name
            local_time = timezone.localtime(appointment.start_time)
            time_str = local_time.strftime("%d/%m %H:%M")

            pay_summary = appointment.get_payment_summary()
            pay_suffix = f" Pago: {pay_summary}."

            if event_type == "APPOINTMENT_REQUEST_CLIENT":
                push_title = "Solicitud de Turno Recibida"
                push_message = f"Tu solicitud de turno para {service_name} en {hairdresser_name} el {time_str} fue recibida. Aguardá la confirmación del local.{pay_suffix}"
            elif event_type == "APPOINTMENT_REQUEST_OWNER":
                push_title = "Nueva Solicitud de Turno"
                push_message = f"{appointment.client.first_name or appointment.client.username} solicitó un turno para {service_name} el {time_str}. Confirmálo desde tu panel.{pay_suffix}"
            elif event_type == "APPOINTMENT_SUCCESS_CLIENT":
                push_title = "Confirmación de Turno"
                push_message = f"Tu turno para {service_name} en {hairdresser_name} el {time_str} ha sido reservado.{pay_suffix}"
            elif event_type == "APPOINTMENT_SUCCESS_OWNER":
                push_title = "Nueva Reserva"
                push_message = f"Has recibido una nueva reserva de {appointment.client.first_name or appointment.client.username} para {service_name} el {time_str}.{pay_suffix}"
            elif event_type == "APPOINTMENT_CANCELLED_CLIENT":
                push_title = "Turno Cancelado"
                if appointment.amount_paid > 0:
                    push_message = f"Tu turno para {service_name} en {hairdresser_name} el {time_str} ha sido cancelado. Monto pagado: ${appointment.amount_paid}."
                else:
                    push_message = f"Tu turno para {service_name} en {hairdresser_name} el {time_str} ha sido cancelado."
            elif event_type == "APPOINTMENT_CANCELLED_OWNER":
                push_title = "Reserva Cancelada"
                if appointment.amount_paid > 0:
                    push_message = f"La reserva de {appointment.client.first_name or appointment.client.username} para {service_name} el {time_str} ha sido cancelada. Monto pagado online: ${appointment.amount_paid}."
                else:
                    push_message = f"La reserva de {appointment.client.first_name or appointment.client.username} para {service_name} el {time_str} ha sido cancelada."
            elif event_type == "APPOINTMENT_REMINDER":
                push_title = "Recordatorio de Turno"
                push_message = f"Recuerda tu turno para {service_name} en {hairdresser_name} mañana el {time_str}.{pay_suffix}"
            elif event_type == "APPOINTMENT_RESCHEDULED_CLIENT":
                push_title = "Turno Reprogramado"
                push_message = f"Tu turno para {service_name} en {hairdresser_name} ha sido reprogramado para las {timezone.localtime(appointment.start_time).strftime('%H:%M')} hs. Si no te queda bien, podés cancelarlo desde mis turnos y reservar para otro día."
            elif event_type == "APPOINTMENT_EARLY_OFFER":
                push_title = "¡Adelantá tu turno!"
                push_message = f"¿Querés adelantar tu turno para {service_name} a las {timezone.localtime(appointment.start_time).strftime('%H:%M')} hs? Tenés 2 minutos para responder."

    if push_title and push_message:
        send_push_notification(user, push_title, push_message)

    # Actualizar last_notified_start_time si es necesario
    if event_type in ["APPOINTMENT_SUCCESS_CLIENT", "APPOINTMENT_RESCHEDULED_CLIENT"]:
        appointment = context.get("appointment")
        if appointment and getattr(appointment, "pk", None) and hasattr(appointment, "last_notified_start_time"):
            appointment.last_notified_start_time = appointment.start_time
            from core.models import Appointment
            Appointment.objects.filter(pk=appointment.pk).update(
                last_notified_start_time=appointment.start_time
            )

    return success


def get_mercadopago_payment_id_from_api(hairdresser, appointment_id):
    """
    Intenta obtener el payment_id desde la API de MercadoPago buscando pagos
    con external_reference igual al appointment_id.

    Esto es un fallback para turnos anteriores al campo mercadopago_payment_id.

    Args:
        hairdresser: Instancia de Hairdresser con token de MercadoPago
        appointment_id: ID del turno a buscar

    Returns:
        str con el payment_id si lo encuentra, None si no
    """
    from django.conf import settings as app_settings

    mp_logger.info(
        f"[FALLBACK] Buscando payment_id en MercadoPago para appointment {appointment_id}"
    )

    if not hairdresser or not hairdresser.mercadopago_active:
        return None

    # Obtener el access token
    if app_settings.MERCADOPAGO_SANDBOX and app_settings.MERCADOPAGO_TEST_ACCESS_TOKEN:
        access_token = app_settings.MERCADOPAGO_TEST_ACCESS_TOKEN
    else:
        access_token = hairdresser.mercadopago_access_token

    if not access_token:
        return None

    try:
        # Buscar pagos de este peluquero con external_reference = appointment_id
        search_url = f"https://api.mercadopago.com/v1/payments/search"
        headers = {
            "Authorization": f"Bearer {access_token}",
        }
        params = {
            "external_reference": str(appointment_id),
            "sort": "date_created",
            "criteria": "desc",
            "limit": 1,
        }

        response = requests.get(search_url, headers=headers, params=params, timeout=10)
        response.raise_for_status()

        data = response.json()
        results = data.get("results", [])

        if results and len(results) > 0:
            payment_id = str(results[0].get("id"))
            status = results[0].get("status")
            mp_logger.info(
                f"[FALLBACK] Encontrado payment_id {payment_id} con status {status}"
            )
            return payment_id
        else:
            mp_logger.warning(
                f"[FALLBACK] No se encontró pago en MercadoPago para appointment {appointment_id}"
            )
            return None

    except Exception as e:
        mp_logger.error(f"[FALLBACK] Error buscando payment_id: {str(e)}")
        return None


def process_mercadopago_refund(hairdresser, payment_id, amount=None):
    """
    Procesa un reembolso (refund) en MercadoPago.

    Args:
        hairdresser: Instancia de Hairdresser con token de MercadoPago
        payment_id: ID del pago a reembolsar (string o int)
        amount: Monto a reembolsar (None para reembolso total, Decimal para parcial)

    Returns:
        dict con keys:
            - 'success': bool indicando si el refund fue exitoso
            - 'refund_id': ID del refund si fue exitoso (None si no)
            - 'error': mensaje de error si falló (None si fue exitoso)
    """
    from django.conf import settings as app_settings
    from decimal import Decimal

    mp_logger.info(
        f"[REFUND] Iniciando refund para payment_id={payment_id}, amount={amount}, hairdresser={hairdresser.id}"
    )

    if not payment_id:
        mp_logger.error("[REFUND] payment_id es requerido")
        return {"success": False, "refund_id": None, "error": "payment_id es requerido"}

    if not hairdresser or not hairdresser.mercadopago_active:
        mp_logger.error(
            f"[REFUND] MercadoPago no activo para hairdresser {hairdresser.id if hairdresser else 'None'}"
        )
        return {
            "success": False,
            "refund_id": None,
            "error": "MercadoPago no está habilitado para esta peluquería",
        }

    # Obtener el access token
    if app_settings.MERCADOPAGO_SANDBOX and app_settings.MERCADOPAGO_TEST_ACCESS_TOKEN:
        access_token = app_settings.MERCADOPAGO_TEST_ACCESS_TOKEN
        mp_logger.info("[REFUND] Usando token de SANDBOX")
    else:
        access_token = hairdresser.mercadopago_access_token
        mp_logger.info("[REFUND] Usando token de producción del owner")

    if not access_token:
        mp_logger.error(
            f"[REFUND] Token de acceso no configurado para hairdresser {hairdresser.id}"
        )
        return {
            "success": False,
            "refund_id": None,
            "error": "Token de acceso de MercadoPago no configurado",
        }

    # Construir URL y headers
    refund_url = f"https://api.mercadopago.com/v1/payments/{payment_id}/refunds"
    import uuid

    idempotency_key = str(uuid.uuid4())

    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
        "X-Idempotency-Key": idempotency_key,
    }

    # Preparar payload
    payload = {}
    if amount is not None:
        # Reembolso parcial: incluir el monto
        payload = {"amount": float(amount) if isinstance(amount, Decimal) else amount}
    # Si payload está vacío, MercadoPago interpreta como reembolso total

    mp_logger.info(f"[REFUND] Enviando POST a {refund_url} con payload: {payload}")
    mp_logger.info(f"[REFUND] X-Idempotency-Key: {idempotency_key}")

    try:
        response = requests.post(refund_url, headers=headers, json=payload, timeout=10)

        mp_logger.info(f"[REFUND] Response status: {response.status_code}")
        mp_logger.info(f"[REFUND] Response body: {response.text}")

        response.raise_for_status()

        refund_data = response.json()
        refund_id = refund_data.get("id")

        mp_logger.info(
            f"[REFUND] Refund exitoso: Payment {payment_id} → Refund {refund_id}"
        )

        return {"success": True, "refund_id": refund_id, "error": None}

    except requests.exceptions.HTTPError as e:
        error_msg = f"Error HTTP {e.response.status_code} al procesar refund: {str(e)}"
        try:
            error_data = e.response.json()
            error_msg = error_data.get("message", error_msg)
        except:
            pass
        mp_logger.error(f"[REFUND] Refund failed for payment {payment_id}: {error_msg}")
        mp_logger.error(f"[REFUND] Response text: {e.response.text}")
        return {"success": False, "refund_id": None, "error": error_msg}

    except Exception as e:
        error_msg = f"Error inesperado al procesar refund: {str(e)}"
        mp_logger.error(
            f"[REFUND] Refund failed for payment {payment_id}: {error_msg}",
            exc_info=True,
        )
        return {"success": False, "refund_id": None, "error": error_msg}


def refresh_mercadopago_token(hairdresser):
    """
    Renueva el token de acceso de MercadoPago utilizando el refresh_token.
    Actualiza mercadopago_access_token, mercadopago_refresh_token y mercadopago_token_expires_at.
    """
    from django.conf import settings as app_settings
    from django.utils import timezone
    from datetime import timedelta


    client_id = getattr(app_settings, "MERCADOPAGO_CLIENT_ID", None)
    client_secret = getattr(app_settings, "MERCADOPAGO_CLIENT_SECRET", None)
    if not client_id or not client_secret:
        raise ValueError("Credenciales de MercadoPago (Client ID / Client Secret) no configuradas.")

    if not hairdresser.mercadopago_refresh_token:
        raise ValueError(f"La peluquería ID {hairdresser.pk} no tiene un refresh token registrado.")

    token_url = "https://api.mercadopago.com/oauth/token"
    payload = {
        "grant_type": "refresh_token",
        "client_id": client_id,
        "client_secret": client_secret,
        "refresh_token": hairdresser.mercadopago_refresh_token,
    }
    headers = {
        "accept": "application/json",
        "content-type": "application/x-www-form-urlencoded"
    }

    mp_logger.info(f"[OAUTH] Renovando token de MercadoPago para peluquería ID: {hairdresser.pk}")
    
    response = requests.post(token_url, data=payload, headers=headers, timeout=10)
    response.raise_for_status()
    data = response.json()

    hairdresser.mercadopago_access_token = data.get("access_token", "")
    hairdresser.mercadopago_refresh_token = data.get("refresh_token", "")
    
    expires_in = data.get("expires_in")
    if expires_in:
        hairdresser.mercadopago_token_expires_at = timezone.now() + timedelta(seconds=int(expires_in))
    else:
        hairdresser.mercadopago_token_expires_at = timezone.now() + timedelta(days=180)

    hairdresser.save()
    mp_logger.info(f"[OAUTH] Token renovado exitosamente para peluquería ID: {hairdresser.pk}. Próxima expiración: {hairdresser.mercadopago_token_expires_at}")
    return data


def reschedule_subsequent_appointments(appointment, delta_minutes):
    """
    Desplaza en cascada los turnos posteriores del mismo peluquero para el mismo día.
    Retorna la lista de turnos que de acuerdo con el escalonamiento de notificaciones
    deben ser notificados al cliente.
    """
    from datetime import timedelta
    from django.utils import timezone
    from core.models import Appointment

    # Buscar turnos activos del día de la misma peluquería que empiecen después del actual
    today = timezone.localtime(appointment.start_time).date()
    subsequent = Appointment.objects.filter(
        service__hairdresser=appointment.service.hairdresser,
        start_time__date=today,
        start_time__gt=appointment.start_time,
    ).exclude(status__in=["COMPLETED", "NO_SHOW", "CANCELLED"]).order_by("start_time")

    affected_to_notify = []
    now = timezone.now()

    for app in subsequent:
        old_start = app.start_time
        # Desplazar start_time
        app.start_time = app.start_time + timedelta(minutes=delta_minutes)
        app.save()  # Esto recalcula y guarda end_time automáticamente

        # Lógica de notificaciones "escalonadas" para evitar spam:
        # 1. Calcular minutos restantes para el NUEVO start_time
        remaining_minutes = (app.start_time - now).total_seconds() / 60

        should_notify = False
        if not app.last_notified_start_time:
            # Si nunca fue notificado, notificar si falta menos de 2 horas (120m)
            if remaining_minutes <= 120:
                should_notify = True
        else:
            last_remaining = (app.last_notified_start_time - now).total_seconds() / 60
            
            if remaining_minutes <= 30:
                # Menos de 30 minutos: cualquier cambio se notifica
                if app.start_time != app.last_notified_start_time:
                    should_notify = True
            elif remaining_minutes <= 60 and last_remaining > 60:
                # Cruzó el escalón de 1 hora hacia abajo
                should_notify = True
            elif remaining_minutes <= 120 and last_remaining > 120:
                # Cruzó el escalón de 2 horas hacia abajo
                should_notify = True
            elif remaining_minutes > 60 and last_remaining <= 60:
                # Cruzó el escalón de 1 hora hacia arriba (retrasado)
                should_notify = True
            elif remaining_minutes > 120 and last_remaining <= 120:
                # Cruzó el escalón de 2 horas hacia arriba (retrasado)
                should_notify = True

        if should_notify:
            affected_to_notify.append(app)

    return affected_to_notify


def notify_rescheduled_appointments(appointments):
    """
    Envía notificaciones push y email a cada uno de los clientes de los turnos reprogramados.
    """
    for app in appointments:
        if app.client:
            notify_user(
                user=app.client,
                event_type="APPOINTMENT_RESCHEDULED_CLIENT",
                context={"appointment": app},
                subject="Horario de tu Turno Reprogramado - Stilo",
            )


def add_schedule_pause(hairdresser, delta_minutes):
    """
    Agrega una pausa desplazando en cascada todos los turnos futuros del día.
    Retorna el número de turnos desplazados.
    """
    from datetime import timedelta
    from django.utils import timezone
    from core.models import Appointment

    now = timezone.now()
    today = timezone.localtime(now).date()

    # Buscar todos los turnos CONFIRMED o PENDING del día de la misma peluquería que empiecen en el futuro
    subsequent = Appointment.objects.filter(
        service__hairdresser=hairdresser,
        start_time__date=today,
        start_time__gt=now,
    ).exclude(status__in=["COMPLETED", "NO_SHOW", "CANCELLED"]).order_by("start_time")

    affected_to_notify = []

    for app in subsequent:
        app.start_time = app.start_time + timedelta(minutes=delta_minutes)
        app.save()  # Esto recalcula y guarda end_time automáticamente

        # Lógica de notificaciones escalonadas para evitar spam:
        remaining_minutes = (app.start_time - now).total_seconds() / 60

        should_notify = False
        if not app.last_notified_start_time:
            if remaining_minutes <= 120:
                should_notify = True
        else:
            last_remaining = (app.last_notified_start_time - now).total_seconds() / 60
            
            if remaining_minutes <= 30:
                if app.start_time != app.last_notified_start_time:
                    should_notify = True
            elif remaining_minutes <= 60 and last_remaining > 60:
                should_notify = True
            elif remaining_minutes <= 120 and last_remaining > 120:
                should_notify = True
            elif remaining_minutes > 60 and last_remaining <= 60:
                should_notify = True
            elif remaining_minutes > 120 and last_remaining <= 120:
                should_notify = True

        if should_notify:
            affected_to_notify.append(app)

    notify_rescheduled_appointments(affected_to_notify)
    return len(subsequent)


