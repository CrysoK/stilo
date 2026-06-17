import requests

def get_ip(request):
    """Obtiene la IP real del usuario, incluso si está detrás de un proxy."""
    x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
    if x_forwarded_for:
        ip = x_forwarded_for.split(',')[0]
    else:
        ip = request.META.get('REMOTE_ADDR')
    return ip

def get_location_from_ip(request):
    """Obtiene latitud y longitud a partir de la IP del usuario usando ipinfo.io."""
    ip = get_ip(request)
    
    # Coordenadas de fallback por defecto (si todo lo demás falla)
    default_coords = {'lat': -34.6037, 'lon': -58.3816} # Buenos Aires

    # No se puede geolocalizar una IP local, devolvemos el fallback.
    if ip == '127.0.0.1' or ip == 'localhost':
        return default_coords

    try:
        # Hacemos la llamada a la API
        response = requests.get(f'https://ipinfo.io/{ip}/json', timeout=3)
        response.raise_for_status()  # Lanza un error si la respuesta es 4xx o 5xx
        data = response.json()

        # Parseamos las coordenadas
        if 'loc' in data:
            lat, lon = data['loc'].split(',')
            return {'lat': float(lat), 'lon': float(lon)}
        else:
            return default_coords
            
    except (requests.RequestException, ValueError, KeyError) as e:
        # Si la API falla, el JSON es inválido o no tiene 'loc', usamos el fallback
        print(f"Error getting location from IP {ip}: {e}")
        return default_coords

def geocode_address(address):
    """
    Geocodifica una dirección usando la API de Nominatim (OpenStreetMap).
    Retorna un diccionario con 'latitude' y 'longitude', o None si falla.
    """
    if not address or not isinstance(address, str) or not address.strip():
        return None

    url = "https://nominatim.openstreetmap.org/search"
    params = {
        'q': address.strip(),
        'format': 'json',
        'limit': 1
    }
    headers = {
        'User-Agent': 'Stilo Hairdresser App (UNSa Desarrollo Web; contacto@stilo.com)'
    }
    
    try:
        response = requests.get(url, params=params, headers=headers, timeout=5)
        response.raise_for_status()
        results = response.json()
        
        if results and isinstance(results, list) and len(results) > 0:
            return {
                'latitude': float(results[0]['lat']),
                'longitude': float(results[0]['lon'])
            }
        return None
    except Exception as e:
        print(f"Error in geocode_address: {e}")
        return None


from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string
from django.utils.html import strip_tags
from django.conf import settings
import logging

logger = logging.getLogger(__name__)

def send_html_email(subject, template_name, context, recipient_list):
    """
    Envía un correo electrónico con contenido HTML y una alternativa de texto plano.
    """
    try:
        html_content = render_to_string(template_name, context)
        text_content = strip_tags(html_content)
        
        from_email = getattr(settings, 'DEFAULT_FROM_EMAIL', getattr(settings, 'EMAIL_HOST_USER', 'webmaster@localhost'))
        
        email = EmailMultiAlternatives(subject, text_content, from_email, recipient_list)
        email.attach_alternative(html_content, "text/html")
        email.send()
        return True
    except Exception as e:
        logger.error(f"Error al enviar correo ({subject}): {e}")
        return False


from pywebpush import webpush, WebPushException
import json
import logging
import threading
from django.db import connection
from django.utils import timezone

logger = logging.getLogger(__name__)

def send_push_to_subscription(subscription, title, message):
    """
    Envía una notificación push a una suscripción específica usando pywebpush.
    """
    subscription_info = {
        "endpoint": subscription.endpoint,
        "keys": {
            "p256dh": subscription.p256dh,
            "auth": subscription.auth
        }
    }
    
    vapid_private_key = getattr(settings, 'VAPID_PRIVATE_KEY', None)
    if not vapid_private_key:
        logger.error("VAPID_PRIVATE_KEY no está configurada en settings.")
        return

    try:
        webpush(
            subscription_info=subscription_info,
            data=json.dumps({
                "title": title,
                "body": message,
            }),
            vapid_private_key=vapid_private_key,
            vapid_claims={
                "sub": "mailto:contacto@stilo.com",
            }
        )
    except WebPushException as ex:
        # Si la suscripción ha expirado o es inválida, la removemos de la base de datos (404 Not Found o 410 Gone)
        if ex.response is not None and ex.response.status_code in [404, 410]:
            logger.info(f"Removiendo suscripción inactiva/expirada {subscription.id}.")
            subscription.delete()
        else:
            logger.error(f"Error al enviar notificación push a la suscripción {subscription.id}: {ex}")
    except Exception as ex:
        logger.error(f"Error inesperado al enviar push a la suscripción {subscription.id}: {ex}")


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
        logger.error(f"Error en el hilo de notificaciones push para el usuario {user_id}: {e}")
    finally:
        # No cerrar la conexión en modo testing para no invalidar la conexión de la suite de pruebas
        if 'test' not in sys.argv:
            connection.close()


def send_push_notification(user, title, message):
    """
    Busca todas las suscripciones activas del usuario y realiza el envío a cada dispositivo en segundo plano.
    En modo de pruebas, se ejecuta de manera síncrona para evitar bloqueos en SQLite.
    """
    if not user or not user.pk:
        return
        
    import sys
    if 'test' in sys.argv:
        # Ejecutar sincrónicamente durante las pruebas unitarias
        _send_push_notification_thread(user.pk, title, message)
    else:
        thread = threading.Thread(
            target=_send_push_notification_thread,
            args=(user.pk, title, message)
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
        'WELCOME': 'emails/welcome.html',
        'PASSWORD_CHANGED': 'emails/password_changed.html',
        'APPOINTMENT_SUCCESS_CLIENT': 'emails/appointment_success_client.html',
        'APPOINTMENT_SUCCESS_OWNER': 'emails/appointment_success_owner.html',
        'APPOINTMENT_CANCELLED_CLIENT': 'emails/appointment_cancelled_client.html',
        'APPOINTMENT_CANCELLED_OWNER': 'emails/appointment_cancelled_owner.html',
        'APPOINTMENT_REMINDER': 'emails/appointment_reminder.html',
    }

    template_name = template_map.get(event_type)
    if template_name and getattr(user, 'email', None):
        success = send_html_email(
            subject=subject,
            template_name=template_name,
            context=context,
            recipient_list=[user.email]
        )

    # 2. Notificaciones Push
    if not push_title or not push_message:
        appointment = context.get('appointment')
        if appointment:
            service_name = appointment.service.name
            hairdresser_name = appointment.service.hairdresser.name
            local_time = timezone.localtime(appointment.start_time)
            time_str = local_time.strftime("%d/%m %H:%M")
            
            if event_type == 'APPOINTMENT_SUCCESS_CLIENT':
                push_title = "Confirmación de Turno"
                push_message = f"Tu turno para {service_name} en {hairdresser_name} el {time_str} ha sido reservado."
            elif event_type == 'APPOINTMENT_SUCCESS_OWNER':
                push_title = "Nueva Reserva"
                push_message = f"Has recibido una nueva reserva de {appointment.client.first_name or appointment.client.username} para {service_name} el {time_str}."
            elif event_type == 'APPOINTMENT_CANCELLED_CLIENT':
                push_title = "Turno Cancelado"
                push_message = f"Tu turno para {service_name} en {hairdresser_name} el {time_str} ha sido cancelado."
            elif event_type == 'APPOINTMENT_CANCELLED_OWNER':
                push_title = "Reserva Cancelada"
                push_message = f"La reserva de {appointment.client.first_name or appointment.client.username} para {service_name} el {time_str} ha sido cancelada."
            elif event_type == 'APPOINTMENT_REMINDER':
                push_title = "Recordatorio de Turno"
                push_message = f"Recuerda tu turno para {service_name} en {hairdresser_name} mañana el {time_str}."

    if push_title and push_message:
        send_push_notification(user, push_title, push_message)

    return success

