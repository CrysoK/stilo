from unittest.mock import patch, MagicMock
from django.test import TestCase, Client
from django.urls import reverse
from django.contrib.auth import get_user_model
from core.utils import geocode_address
from core.models import Hairdresser, PushSubscription
import json

User = get_user_model()


class GeocodingTestCase(TestCase):
    def setUp(self):
        self.client = Client()
        # Creamos usuario dueño
        self.owner = User.objects.create_user(
            username="owner",
            password="password123",
            first_name="Owner",
            last_name="Test",
            email="owner@test.com",
            is_owner=True,
        )
        # Creamos perfil de peluquería
        self.hairdresser = Hairdresser.objects.create(
            owner=self.owner, name="Test Hairdresser", address="Initial Address"
        )

        # Creamos cliente normal (no dueño)
        self.client_user = User.objects.create_user(
            username="client",
            password="password123",
            first_name="Client",
            last_name="Test",
            email="client@test.com",
            is_owner=False,
        )

        # Creamos un dueño sin peluquería para probar edge case
        self.owner_no_profile = User.objects.create_user(
            username="owner_no_profile",
            password="password123",
            first_name="OwnerNoProfile",
            last_name="Test",
            email="ownernoprofile@test.com",
            is_owner=True,
        )

    @patch("core.utils.requests.get")
    def test_geocode_address_success(self, mock_get):
        # Configurar mock de respuesta exitosa de Nominatim
        mock_response = MagicMock()
        mock_response.json.return_value = [{"lat": "-24.789123", "lon": "-65.412345"}]
        mock_response.status_code = 200
        mock_get.return_value = mock_response

        result = geocode_address("Av. Bolivia 5150, Salta")
        self.assertIsNotNone(result)
        self.assertEqual(result["latitude"], -24.789123)
        self.assertEqual(result["longitude"], -65.412345)

        # Verificar parámetros de llamada
        mock_get.assert_called_once()
        args, kwargs = mock_get.call_args
        self.assertEqual(kwargs["params"]["q"], "Av. Bolivia 5150, Salta")
        self.assertEqual(kwargs["params"]["format"], "json")
        self.assertIn("User-Agent", kwargs["headers"])

    @patch("core.utils.requests.get")
    def test_geocode_address_no_results(self, mock_get):
        # Nominatim retorna lista vacía
        mock_response = MagicMock()
        mock_response.json.return_value = []
        mock_response.status_code = 200
        mock_get.return_value = mock_response

        result = geocode_address("Direccion Invalida 123456")
        self.assertIsNone(result)

    @patch("core.utils.requests.get")
    def test_geocode_address_network_error(self, mock_get):
        # Nominatim lanza error de red
        import requests

        mock_get.side_effect = requests.RequestException("Network error")

        result = geocode_address("Av. Bolivia 5150, Salta")
        self.assertIsNone(result)

    def test_geocode_address_empty_input(self):
        self.assertIsNone(geocode_address(""))
        self.assertIsNone(geocode_address("   "))
        self.assertIsNone(geocode_address(None))

    def test_api_unauthenticated_access(self):
        # Usuario no autenticado debe recibir 403
        response = self.client.get(reverse("geocode_address_api") + "?address=Salta")
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json(), {"error": "No autorizado"})

    def test_api_client_access(self):
        # Usuario cliente (is_owner=False) debe recibir 403
        self.client.login(username="client", password="password123")
        response = self.client.get(reverse("geocode_address_api") + "?address=Salta")
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json(), {"error": "No autorizado"})

    def test_api_owner_no_profile_access(self):
        # Dueño sin peluquería debe recibir 403
        self.client.login(username="owner_no_profile", password="password123")
        response = self.client.get(reverse("geocode_address_api") + "?address=Salta")
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json(), {"error": "No autorizado"})

    @patch("core.views.geocode_address")
    def test_api_owner_success(self, mock_geocode):
        # Dueño autenticado consulta dirección válida
        mock_geocode.return_value = {"latitude": -24.789, "longitude": -65.412}
        self.client.login(username="owner", password="password123")

        response = self.client.get(reverse("geocode_address_api") + "?address=Salta")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data["success"])
        self.assertEqual(data["latitude"], -24.789)
        self.assertEqual(data["longitude"], -65.412)
        mock_geocode.assert_called_once_with("Salta")

    @patch("core.views.geocode_address")
    def test_api_owner_not_found(self, mock_geocode):
        # Dirección no geocodificable
        mock_geocode.return_value = None
        self.client.login(username="owner", password="password123")

        response = self.client.get(reverse("geocode_address_api") + "?address=Invalida")
        self.assertEqual(response.status_code, 404)
        data = response.json()
        self.assertFalse(data["success"])
        self.assertEqual(data["error"], "No se pudo encontrar la dirección en el mapa.")

    def test_api_owner_missing_address(self):
        # Parámetro address ausente o vacío
        self.client.login(username="owner", password="password123")

        response = self.client.get(reverse("geocode_address_api"))
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json(), {"error": "La dirección es requerida."})

        response = self.client.get(reverse("geocode_address_api") + "?address=   ")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json(), {"error": "La dirección es requerida."})


from django.core import mail
from django.conf import settings
from django.utils import timezone
from core.models import Service, Appointment
import datetime


class NotificationTestCase(TestCase):
    def setUp(self):
        self.client = Client()
        self.owner = User.objects.create_user(
            username="owner_notify",
            password="password123",
            first_name="OwnerName",
            last_name="OwnerLastName",
            email="owner_notify@test.com",
            is_owner=True,
        )
        self.hairdresser = Hairdresser.objects.create(
            owner=self.owner, name="Salon Notify", address="Av. Siempre Viva 742"
        )
        self.client_user = User.objects.create_user(
            username="client_notify",
            password="password123",
            first_name="ClientName",
            last_name="ClientLastName",
            email="client_notify@test.com",
            is_owner=False,
        )
        self.service = Service.objects.create(
            hairdresser=self.hairdresser,
            name="Corte Clasico",
            price=20.0,
            duration_minutes=30,
        )

    def test_welcome_email_on_signup(self):
        mail.outbox = []
        signup_data = {
            "username": "new_user",
            "first_name": "Nuevo",
            "last_name": "Usuario",
            "email": "new_user@test.com",
            "password1": "SecurePass123!",
            "password2": "SecurePass123!",
            "is_owner": False,
        }
        response = self.client.post(reverse("signup"), signup_data)
        self.assertEqual(response.status_code, 302)  # Redirige al home
        self.assertEqual(len(mail.outbox), 1)
        email = mail.outbox[0]
        self.assertEqual(email.to, ["new_user@test.com"])
        self.assertIn("¡Te damos la bienvenida a Stilo!", email.subject)
        self.assertIn("Nuevo", email.body)

    def test_password_change_email(self):
        self.client.login(username="client_notify", password="password123")
        mail.outbox = []
        change_password_data = {
            "old_password": "password123",
            "new_password1": "NewSecurePass123!",
            "new_password2": "NewSecurePass123!",
        }
        response = self.client.post(reverse("password_change"), change_password_data)
        self.assertEqual(response.status_code, 302)  # Redirige al perfil
        self.assertEqual(len(mail.outbox), 1)
        email = mail.outbox[0]
        self.assertEqual(email.to, ["client_notify@test.com"])
        self.assertIn(
            "Confirmación de seguridad: Cambio de contraseña - Stilo", email.subject
        )

    def test_appointment_creation_emails(self):
        # Escenario 1: turno creado como PENDING (sin expires_at)
        # → solicitud esperando confirmación del dueño
        mail.outbox = []
        start_time = timezone.now() + datetime.timedelta(days=2)
        appointment_pending = Appointment.objects.create(
            client=self.client_user,
            service=self.service,
            start_time=start_time,
            status="PENDING",
            # expires_at no se pasa → es None → es una solicitud manual
        )
        self.assertEqual(len(mail.outbox), 2)
        recipients = [email.to[0] for email in mail.outbox]
        self.assertIn("client_notify@test.com", recipients)
        self.assertIn("owner_notify@test.com", recipients)

        subjects = [email.subject for email in mail.outbox]
        self.assertIn("Solicitud de Turno Recibida - Stilo", subjects)
        self.assertIn("Nueva Solicitud de Turno - Stilo", subjects)

        # Escenario 2: turno creado directamente como CONFIRMED
        # (por ejemplo, el admin o una lógica interna lo confirma directamente)
        mail.outbox = []
        start_time_2 = timezone.now() + datetime.timedelta(days=3)
        appointment_confirmed = Appointment.objects.create(
            client=self.client_user,
            service=self.service,
            start_time=start_time_2,
            status="CONFIRMED",
        )
        self.assertEqual(len(mail.outbox), 2)
        recipients_2 = [email.to[0] for email in mail.outbox]
        self.assertIn("client_notify@test.com", recipients_2)
        self.assertIn("owner_notify@test.com", recipients_2)

        subjects_2 = [email.subject for email in mail.outbox]
        self.assertIn("Confirmación de Turno - Stilo", subjects_2)
        self.assertIn("Nueva Reserva Recibida - Stilo", subjects_2)

    def test_appointment_cancellation_emails(self):
        start_time = timezone.now() + datetime.timedelta(days=2)
        appointment = Appointment.objects.create(
            client=self.client_user, service=self.service, start_time=start_time
        )
        mail.outbox = []
        appointment.status = "CANCELLED"
        appointment.save()

        self.assertEqual(len(mail.outbox), 2)
        recipients = [email.to[0] for email in mail.outbox]
        self.assertIn("client_notify@test.com", recipients)
        self.assertIn("owner_notify@test.com", recipients)

        subjects = [email.subject for email in mail.outbox]
        self.assertIn("Turno Cancelado - Stilo", subjects)
        self.assertIn("Reserva Cancelada - Stilo", subjects)

    def test_send_reminders_unauthorized(self):
        # Sin token
        response = self.client.get(reverse("send_reminders"))
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json(), {"error": "No autorizado"})

        # Token inválido
        response = self.client.get(reverse("send_reminders") + "?token=wrong_token")
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json(), {"error": "No autorizado"})

    def test_send_reminders_success(self):
        tomorrow = timezone.localtime(timezone.now()) + datetime.timedelta(days=1)
        appointment = Appointment.objects.create(
            client=self.client_user,
            service=self.service,
            start_time=tomorrow,
            status="CONFIRMED",
        )

        today = timezone.localtime(timezone.now())
        appointment_today = Appointment.objects.create(
            client=self.client_user,
            service=self.service,
            start_time=today,
            status="CONFIRMED",
        )

        appointment_cancelled = Appointment.objects.create(
            client=self.client_user,
            service=self.service,
            start_time=tomorrow,
            status="CANCELLED",
        )

        mail.outbox = []

        url = reverse("send_reminders") + f"?token={settings.CRON_SECRET}"
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data["success"])
        self.assertEqual(data["sent_count"], 1)

        self.assertEqual(len(mail.outbox), 1)
        email = mail.outbox[0]
        self.assertEqual(email.to, ["client_notify@test.com"])
        self.assertIn("Recordatorio de Turno - Stilo", email.subject)

    @patch("core.utils.send_push_notification")
    def test_appointment_notifications_contain_payment_info(self, mock_send_push):
        # 1. Crear un turno con pago adelantado completo y confirmado (ej: simula MP aprobado)
        start_time = timezone.now() + datetime.timedelta(days=2)

        # Primero limpiamos el outbox
        mail.outbox = []

        app = Appointment.objects.create(
            client=self.client_user,
            service=self.service,
            start_time=start_time,
            status="CONFIRMED",
            payment_method="FULL",
            amount_paid=Decimal("20.00"),  # El precio del servicio es 20.0
        )

        # Deben haberse enviado 2 correos (cliente y dueño)
        self.assertEqual(len(mail.outbox), 2)

        client_email = [
            email for email in mail.outbox if email.to == ["client_notify@test.com"]
        ][0]
        owner_email = [
            email for email in mail.outbox if email.to == ["owner_notify@test.com"]
        ][0]

        # Verificar que el correo de cliente contiene información de pago
        self.assertIn("Pago", client_email.body)
        self.assertIn("Pagado online", client_email.body)

        # Verificar que el correo del dueño contiene información de pago
        self.assertIn("Pago", owner_email.body)
        self.assertIn("Pagado online", owner_email.body)

        # Verificar que la notificación push al cliente contiene detalles de pago
        mock_send_push.assert_called()
        calls = [call[0] for call in mock_send_push.call_args_list]
        client_push = [c for c in calls if c[0] == self.client_user][0]
        self.assertEqual(client_push[1], "Confirmación de Turno")
        self.assertIn("Pago: Pagado online", client_push[2])

    @patch("core.utils.send_push_notification")
    def test_appointment_cancelled_notification_payment_info(self, mock_send_push):
        # Crear un turno pagado
        start_time = timezone.now() + datetime.timedelta(days=2)
        app = Appointment.objects.create(
            client=self.client_user,
            service=self.service,
            start_time=start_time,
            status="CONFIRMED",
            payment_method="FULL",
            amount_paid=Decimal("20.00"),
        )

        # Cancelar el turno
        mail.outbox = []
        app.status = "CANCELLED"
        app.save()  # Esto enviará correos de cancelación normales

        client_email = [
            email for email in mail.outbox if email.to == ["client_notify@test.com"]
        ][0]
        self.assertIn("Monto pagado online", client_email.body)
        self.assertTrue(any(x in client_email.body for x in ["$20.00", "$20,00"]))
        self.assertIn("Información de reembolso", client_email.body)

        # Verificar notificación push
        calls = [call[0] for call in mock_send_push.call_args_list]
        client_push_cancel = [
            c for c in calls if c[0] == self.client_user and c[1] == "Turno Cancelado"
        ][0]
        self.assertIn("Monto pagado: $20.00", client_push_cancel[2])


class EmailPreviewTestCase(TestCase):
    def setUp(self):
        self.client = Client()
        self.staff_user = User.objects.create_user(
            username="staff_preview", password="password123", is_staff=True
        )
        self.normal_user = User.objects.create_user(
            username="normal_preview", password="password123", is_staff=False
        )

    def test_email_preview_access_restricted_when_debug_false(self):
        with patch.object(settings, "DEBUG", False):
            # 1. Sin autenticar -> 403
            response = self.client.get(reverse("email_preview_list"))
            self.assertEqual(response.status_code, 403)

            # 2. Usuario normal -> 403
            self.client.login(username="normal_preview", password="password123")
            response = self.client.get(reverse("email_preview_list"))
            self.assertEqual(response.status_code, 403)
            self.client.logout()

            # 3. Usuario staff -> 200
            self.client.login(username="staff_preview", password="password123")
            response = self.client.get(reverse("email_preview_list"))
            self.assertEqual(response.status_code, 200)

            # Renderizado individual -> 200
            response = self.client.get(
                reverse("email_preview_render", args=["WELCOME"])
            )
            self.assertEqual(response.status_code, 200)
            self.client.logout()

    def test_email_preview_access_allowed_when_debug_true(self):
        with patch.object(settings, "DEBUG", True):
            response = self.client.get(reverse("email_preview_list"))
            self.assertEqual(response.status_code, 200)

            response = self.client.get(
                reverse("email_preview_render", args=["WELCOME"])
            )
            self.assertEqual(response.status_code, 200)
            self.assertIn("Lionel", response.content.decode())


class WebPushTestCase(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(
            username="pusher",
            password="password123",
            first_name="Push",
            last_name="Test",
            email="push@test.com",
        )

    def test_push_subscribe_unauthenticated(self):
        response = self.client.post(reverse("push_subscribe"), {})
        self.assertEqual(response.status_code, 302)

    def test_push_subscribe_invalid_json(self):
        self.client.login(username="pusher", password="password123")
        response = self.client.post(
            reverse("push_subscribe"), "invalid json", content_type="application/json"
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json(), {"error": "JSON inválido"})

    def test_push_subscribe_missing_params(self):
        self.client.login(username="pusher", password="password123")
        response = self.client.post(
            reverse("push_subscribe"),
            json.dumps({"endpoint": "https://push.com/123"}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json(), {"error": "Parámetros incompletos"})

    def test_push_subscribe_success_and_update(self):
        self.client.login(username="pusher", password="password123")
        payload = {
            "endpoint": "https://push.example.com/12345",
            "keys": {"p256dh": "some_p256dh_key", "auth": "some_auth_token"},
        }
        # Crear suscripción
        response = self.client.post(
            reverse("push_subscribe"),
            json.dumps(payload),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["success"])
        self.assertTrue(response.json()["created"])

        # Verificar en base de datos
        sub = PushSubscription.objects.get(user=self.user)
        self.assertEqual(sub.endpoint, payload["endpoint"])
        self.assertEqual(sub.p256dh, payload["keys"]["p256dh"])
        self.assertEqual(sub.auth, payload["keys"]["auth"])

        # Actualizar suscripción
        payload["keys"]["auth"] = "new_auth_token"
        response = self.client.post(
            reverse("push_subscribe"),
            json.dumps(payload),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["success"])
        self.assertFalse(response.json()["created"])  # Modificada, no creada

        sub.refresh_from_db()
        self.assertEqual(sub.auth, "new_auth_token")

    def test_service_worker_serves_js(self):
        response = self.client.get(reverse("service_worker"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/javascript")

    @patch("core.utils.webpush")
    def test_send_push_notification_success(self, mock_webpush):
        sub = PushSubscription.objects.create(
            user=self.user,
            endpoint="https://push.example.com/12345",
            auth="auth_token",
            p256dh="p256dh_key",
        )

        from core.utils import send_push_notification
        import time

        with patch.object(settings, "VAPID_PRIVATE_KEY", "dummy_private_key"):
            send_push_notification(self.user, "Test Title", "Test Message")

            # Esperamos a que corra el hilo secundario
            time.sleep(0.5)

            mock_webpush.assert_called_once()
            args, kwargs = mock_webpush.call_args
            self.assertEqual(kwargs["vapid_private_key"], "dummy_private_key")
            self.assertEqual(kwargs["subscription_info"]["endpoint"], sub.endpoint)
            self.assertIn("Test Title", kwargs["data"])
            self.assertIn("Test Message", kwargs["data"])

    def test_push_unsubscribe_unauthenticated(self):
        response = self.client.post(reverse("push_unsubscribe"), {})
        self.assertEqual(response.status_code, 302)

    def test_push_unsubscribe_success(self):
        self.client.login(username="pusher", password="password123")
        sub = PushSubscription.objects.create(
            user=self.user,
            endpoint="https://push.example.com/12345",
            auth="auth_token",
            p256dh="p256dh_key",
        )
        self.assertEqual(PushSubscription.objects.filter(user=self.user).count(), 1)

        response = self.client.post(
            reverse("push_unsubscribe"),
            json.dumps({"endpoint": "https://push.example.com/12345"}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["success"])
        self.assertEqual(PushSubscription.objects.filter(user=self.user).count(), 0)

    def test_push_subscribe_multiuser_endpoint_conflict(self):
        # 1. Crear otro usuario
        other_user = User.objects.create_user(
            username="other_pusher",
            password="password123",
            first_name="Other",
            last_name="Push",
            email="other@test.com",
        )

        # 2. El primer usuario se suscribe
        self.client.login(username="pusher", password="password123")
        payload = {
            "endpoint": "https://push.example.com/shared-browser",
            "keys": {"p256dh": "some_p256dh_key", "auth": "some_auth_token"},
        }
        response = self.client.post(
            reverse("push_subscribe"),
            json.dumps(payload),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            PushSubscription.objects.filter(endpoint=payload["endpoint"]).count(), 1
        )
        self.assertEqual(
            PushSubscription.objects.filter(
                user=self.user, endpoint=payload["endpoint"]
            ).count(),
            1,
        )
        self.client.logout()

        # 3. El segundo usuario se suscribe al mismo endpoint
        self.client.login(username="other_pusher", password="password123")
        response = self.client.post(
            reverse("push_subscribe"),
            json.dumps(payload),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)

        # 4. Verificar que se eliminó la suscripción del primer usuario y se creó la del segundo
        self.assertEqual(
            PushSubscription.objects.filter(endpoint=payload["endpoint"]).count(), 1
        )
        self.assertEqual(
            PushSubscription.objects.filter(
                user=other_user, endpoint=payload["endpoint"]
            ).count(),
            1,
        )
        self.assertEqual(
            PushSubscription.objects.filter(
                user=self.user, endpoint=payload["endpoint"]
            ).count(),
            0,
        )


from decimal import Decimal
from django.core.exceptions import ValidationError as DjangoValidationError
from core.forms import HairdresserSetupForm, ServiceForm
from core.models import Service, Appointment, WebhookEvent


class MercadoPagoIntegrationTestCase(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user(
            username="owner_mp",
            password="password123",
            first_name="Owner",
            last_name="MP",
            email="owner_mp@test.com",
            is_owner=True,
        )
        self.hairdresser = Hairdresser.objects.create(
            owner=self.owner,
            name="MP Salon",
            address="Av. Siempre Viva 123",
            mercadopago_active=True,
            mercadopago_access_token="APP_USR-test-token",
            requires_deposit=True,
            default_deposit_type="PERCENTAGE",
            default_deposit_value=Decimal("20.00"),
            default_allow_prepayment=True,
            default_allow_on_site_payment=True,
        )
        self.client_user = User.objects.create_user(
            username="client_mp",
            password="password123",
            first_name="Client",
            last_name="MP",
            email="client_mp@test.com",
            is_owner=False,
        )
        self.service = Service.objects.create(
            hairdresser=self.hairdresser,
            name="Corte Premium",
            price=Decimal("1000.00"),
            duration_minutes=45,
        )

    def test_deposit_calculation_percentage_and_fixed(self):
        import datetime
        from django.utils import timezone

        # 1. Porcentaje por defecto de la peluquería (20% de 1000 = 200)
        app = Appointment.objects.create(
            client=self.client_user,
            service=self.service,
            start_time=timezone.now() + datetime.timedelta(days=1),
            amount=self.service.price,
        )
        self.assertEqual(app.get_required_deposit_amount(), Decimal("200.00"))

        # 2. Sobrescribir con monto fijo en el servicio
        self.service.override_deposit = True
        self.service.deposit_type = "FIXED"
        self.service.deposit_value = Decimal("150.00")
        self.service.save()

        app.refresh_from_db()
        self.assertEqual(app.get_required_deposit_amount(), Decimal("150.00"))

        # 3. Sin seña requerida
        self.hairdresser.requires_deposit = False
        self.hairdresser.save()
        app.refresh_from_db()
        self.assertEqual(app.get_required_deposit_amount(), Decimal("0.00"))

    def test_payment_modes_resolution(self):
        import datetime
        from django.utils import timezone

        app = Appointment.objects.create(
            client=self.client_user,
            service=self.service,
            start_time=timezone.now() + datetime.timedelta(days=1),
            amount=self.service.price,
        )
        # Por defecto debe resolver a la peluquería
        modes = app.get_payment_modes()
        self.assertTrue(modes["allow_prepayment"])
        self.assertTrue(modes["allow_on_site_payment"])

        # Sobrescribir en el servicio
        self.service.override_payment_modes = True
        self.service.allow_prepayment = True
        self.service.allow_on_site_payment = False
        self.service.save()

        app.refresh_from_db()
        modes = app.get_payment_modes()
        self.assertTrue(modes["allow_prepayment"])
        self.assertFalse(modes["allow_on_site_payment"])

    def test_hairdresser_setup_form_validation(self):
        # 1. Inválido: MP activo pero sin token en la instancia
        form_data = {
            "name": "Invalid Salon",
            "address": "Address",
            "phone_number": "1234",
            "description": "Desc",
            "mercadopago_active": True,
            "requires_deposit": False,
            "default_deposit_type": "FIXED",
            "default_deposit_value": Decimal("0.00"),
            "default_allow_prepayment": True,
            "default_allow_on_site_payment": True,
            "latitude": -34.60,
            "longitude": -58.38,
        }
        form = HairdresserSetupForm(data=form_data)
        self.assertFalse(form.is_valid())
        self.assertIn("mercadopago_active", form.errors)

        # 2. Inválido: ninguna forma de pago seleccionada (con instancia que sí tiene token)
        form_data["default_allow_prepayment"] = False
        form_data["default_allow_on_site_payment"] = False
        hairdresser_with_token = Hairdresser(mercadopago_access_token="TEST_TOKEN")
        form = HairdresserSetupForm(data=form_data, instance=hairdresser_with_token)
        self.assertFalse(form.is_valid())
        self.assertIn("default_allow_prepayment", form.errors)

        # 3. Válido: pago adelantado activo pero MP inactivo (desactivación temporal permitida)
        form_data["mercadopago_active"] = False
        form_data["default_allow_prepayment"] = True
        form_data["default_allow_on_site_payment"] = True
        form = HairdresserSetupForm(data=form_data)
        self.assertTrue(form.is_valid())

    def test_service_form_validation(self):
        # Inválido: Sobrescribir formas de pago y desactivar ambas
        form_data = {
            "name": "Invalid Service",
            "description": "Desc",
            "price": Decimal("500.00"),
            "duration_minutes": 30,
            "override_deposit": False,
            "deposit_type": "FIXED",
            "deposit_value": Decimal("0.00"),
            "override_payment_modes": True,
            "allow_prepayment": False,
            "allow_on_site_payment": False,
        }
        form = ServiceForm(data=form_data)
        self.assertFalse(form.is_valid())
        self.assertIn("override_payment_modes", form.errors)

    @patch("core.webhooks._verify_mp_signature", return_value=True)
    @patch("core.webhooks.requests.get")
    def test_webhook_payment_approved(self, mock_get, mock_verify_signature):
        # Crear cita PENDING
        import datetime
        from django.utils import timezone

        appointment = Appointment.objects.create(
            client=self.client_user,
            service=self.service,
            start_time=timezone.now() + datetime.timedelta(days=1),
            amount=self.service.price,
            status="PENDING",
            payment_method="CASH",
        )
        self.assertEqual(appointment.status, "PENDING")

        # Mock de respuesta de MercadoPago para obtener detalles de pago
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "status": "approved",
            "external_reference": str(appointment.id),
            "transaction_amount": 200.00,
        }
        mock_response.status_code = 200
        mock_get.return_value = mock_response

        # Llamar al webhook
        client = Client()
        webhook_url = reverse("mercadopago_webhook", args=[self.hairdresser.id])

        # Enviar payload mock (tipo webhook)
        payload = {
            "action": "payment.created",
            "type": "payment",
            "data": {"id": "12345678"},
        }
        response = client.post(
            webhook_url, json.dumps(payload), content_type="application/json"
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content.decode(), "OK")

        # Verificar que la cita fue CONFIRMED y se registró el monto
        appointment.refresh_from_db()
        self.assertEqual(appointment.status, "CONFIRMED")
        self.assertEqual(appointment.amount_paid, Decimal("200.00"))

    @patch("core.webhooks._verify_mp_signature", return_value=True)
    @patch("core.webhooks.requests.post")
    @patch("core.webhooks.requests.get")
    def test_webhook_payment_underpaid(self, mock_get, mock_post_refund, mock_verify_signature):
        # Crear cita PENDING (seña requerida = 200.00)
        import datetime
        from django.utils import timezone

        appointment = Appointment.objects.create(
            client=self.client_user,
            service=self.service,
            start_time=timezone.now() + datetime.timedelta(days=1),
            amount=self.service.price,
            status="PENDING",
            payment_method="CASH",
        )

        # Mock de respuesta de MercadoPago: pago de 150.00 (esperado: 200.00)
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "status": "approved",
            "external_reference": str(appointment.id),
            "transaction_amount": 150.00,
        }
        mock_response.status_code = 200
        mock_get.return_value = mock_response

        # Mock de reembolso exitoso
        mock_post_refund.return_value.status_code = 201
        mock_post_refund.return_value.json.return_value = {"id": "refund_id_underpaid"}

        # Llamar al webhook
        client = Client()
        webhook_url = reverse("mercadopago_webhook", args=[self.hairdresser.id])
        payload = {
            "action": "payment.created",
            "type": "payment",
            "data": {"id": "payment_underpaid_123"},
        }
        response = client.post(
            webhook_url, json.dumps(payload), content_type="application/json"
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content.decode(), "OK")

        # Verificar que la cita fue CANCELLED por pago insuficiente y se registró el monto menor
        appointment.refresh_from_db()
        self.assertEqual(appointment.status, "CANCELLED")
        self.assertEqual(appointment.amount_paid, Decimal("150.00"))

        # Verificar que se intentó reembolsar
        mock_post_refund.assert_called_once()
        # No debe haber reembolsos pendientes en BD
        from core.models import PendingRefund
        self.assertFalse(PendingRefund.objects.filter(appointment=appointment).exists())

    @patch("core.webhooks._verify_mp_signature", return_value=True)
    @patch("core.webhooks.requests.post", side_effect=Exception("API Error"))
    @patch("core.webhooks.requests.get")
    def test_webhook_payment_underpaid_refund_fails_enqueues(self, mock_get, mock_post_refund, mock_verify_signature):
        # Crear cita PENDING
        import datetime
        from django.utils import timezone

        appointment = Appointment.objects.create(
            client=self.client_user,
            service=self.service,
            start_time=timezone.now() + datetime.timedelta(days=1),
            amount=self.service.price,
            status="PENDING",
            payment_method="CASH",
        )

        mock_response = MagicMock()
        mock_response.json.return_value = {
            "status": "approved",
            "external_reference": str(appointment.id),
            "transaction_amount": 150.00,
        }
        mock_response.status_code = 200
        mock_get.return_value = mock_response

        client = Client()
        webhook_url = reverse("mercadopago_webhook", args=[self.hairdresser.id])
        payload = {
            "action": "payment.created",
            "type": "payment",
            "data": {"id": "payment_underpaid_fail_123"},
        }
        response = client.post(
            webhook_url, json.dumps(payload), content_type="application/json"
        )

        self.assertEqual(response.status_code, 200)

        # Cita cancelada
        appointment.refresh_from_db()
        self.assertEqual(appointment.status, "CANCELLED")
        self.assertEqual(appointment.amount_paid, Decimal("150.00"))

        # Debe haber encolado el reembolso fallido
        from core.models import PendingRefund
        self.assertTrue(PendingRefund.objects.filter(appointment=appointment, payment_id="payment_underpaid_fail_123", amount=Decimal("150.00")).exists())

    @patch("core.webhooks._verify_mp_signature", return_value=True)
    @patch("core.webhooks.requests.get")
    def test_webhook_idempotency_duplicate_calls(self, mock_get, mock_verify_signature):
        # Crear cita PENDING
        import datetime
        from django.utils import timezone

        appointment = Appointment.objects.create(
            client=self.client_user,
            service=self.service,
            start_time=timezone.now() + datetime.timedelta(days=1),
            amount=self.service.price,
            status="PENDING",
            payment_method="CASH",
        )

        mock_response = MagicMock()
        mock_response.json.return_value = {
            "status": "approved",
            "external_reference": str(appointment.id),
            "transaction_amount": 200.00,
        }
        mock_response.status_code = 200
        mock_get.return_value = mock_response

        client = Client()
        webhook_url = reverse("mercadopago_webhook", args=[self.hairdresser.id])
        payload = {
            "action": "payment.created",
            "type": "payment",
            "data": {"id": "payment_id_dup_123"},
        }

        # Primer llamado (debe procesar y confirmar)
        response_1 = client.post(
            webhook_url, json.dumps(payload), content_type="application/json"
        )
        self.assertEqual(response_1.status_code, 200)
        self.assertEqual(response_1.content.decode(), "OK")

        # Verificar que se creó y procesó el evento de webhook
        self.assertTrue(WebhookEvent.objects.filter(payment_id="payment_id_dup_123", processed=True).exists())

        # Resetear mocks para contar llamadas externas
        mock_get.reset_mock()

        # Segundo llamado (debe retornar OK de inmediato sin llamar a requests.get)
        response_2 = client.post(
            webhook_url, json.dumps(payload), content_type="application/json"
        )
        self.assertEqual(response_2.status_code, 200)
        self.assertEqual(response_2.content.decode(), "OK")

        # Verificar que NO se hizo la llamada de red de nuevo
        mock_get.assert_not_called()

    @patch("core.webhooks._verify_mp_signature", return_value=True)
    @patch("core.webhooks.requests.get")
    def test_webhook_idempotency_failure_allows_retry(self, mock_get, mock_verify_signature):
        # Crear cita PENDING
        import datetime
        from django.utils import timezone

        appointment = Appointment.objects.create(
            client=self.client_user,
            service=self.service,
            start_time=timezone.now() + datetime.timedelta(days=1),
            amount=self.service.price,
            status="PENDING",
            payment_method="CASH",
        )

        # Mock de MercadoPago API falla la primera vez
        mock_get.side_effect = Exception("Conexion perdida")

        client = Client()
        webhook_url = reverse("mercadopago_webhook", args=[self.hairdresser.id])
        payload = {
            "action": "payment.created",
            "type": "payment",
            "data": {"id": "payment_id_fail_retry"},
        }

        # Primer llamado (falla por la excepción del mock)
        response_1 = client.post(
            webhook_url, json.dumps(payload), content_type="application/json"
        )
        self.assertEqual(response_1.status_code, 500)

        # Verificar que el WebhookEvent existe pero procesado=False
        event = WebhookEvent.objects.get(payment_id="payment_id_fail_retry")
        self.assertFalse(event.processed)

        # Segundo llamado (el mock ahora funciona)
        mock_get.side_effect = None
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "status": "approved",
            "external_reference": str(appointment.id),
            "transaction_amount": 200.00,
        }
        mock_response.status_code = 200
        mock_get.return_value = mock_response

        response_2 = client.post(
            webhook_url, json.dumps(payload), content_type="application/json"
        )
        self.assertEqual(response_2.status_code, 200)

        # Verificar que ahora se procesó con éxito
        event.refresh_from_db()
        self.assertTrue(event.processed)
        appointment.refresh_from_db()
        self.assertEqual(appointment.status, "CONFIRMED")

    def test_mercadopago_inactive_override_behavior(self):
        # 1. Desactivar MercadoPago
        self.hairdresser.mercadopago_active = False
        self.hairdresser.save()

        # 2. Verificar que se calcula seña como 0.00
        # A pesar de que requires_deposit=True y default_deposit_value=20.00
        import datetime
        from django.utils import timezone

        app = Appointment.objects.create(
            client=self.client_user,
            service=self.service,
            start_time=timezone.now() + datetime.timedelta(days=1),
            amount=self.service.price,
        )
        self.assertEqual(app.get_required_deposit_amount(), Decimal("0.00"))
        self.assertEqual(self.service.get_required_deposit_amount(), Decimal("0.00"))

        # 3. Verificar que get_payment_modes() fuerza allow_prepayment=False y allow_on_site_payment=True
        modes = app.get_payment_modes()
        self.assertFalse(modes["allow_prepayment"])
        self.assertTrue(modes["allow_on_site_payment"])

        service_modes = self.service.get_payment_modes()
        self.assertFalse(service_modes["allow_prepayment"])
        self.assertTrue(service_modes["allow_on_site_payment"])

    @patch("core.views.requests.get")
    def test_appointments_list_fallback_approved(self, mock_get):
        # Crear cita PENDING
        import datetime
        from django.utils import timezone

        appointment = Appointment.objects.create(
            client=self.client_user,
            service=self.service,
            start_time=timezone.now() + datetime.timedelta(days=1),
            amount=self.service.price,
            status="PENDING",
            payment_method="CASH",
        )
        self.assertEqual(appointment.status, "PENDING")

        # Mock de la respuesta de la API de MercadoPago para obtener detalles de pago
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "status": "approved",
            "external_reference": str(appointment.id),
            "transaction_amount": 200.00,
        }
        mock_response.status_code = 200
        mock_get.return_value = mock_response

        # Loguearse como el cliente
        client = Client()
        client.login(username="client_mp", password="password123")

        # Consultar la lista de citas simulando el callback de retorno de MercadoPago
        url = reverse("my_appointments")
        response = client.get(
            url,
            {
                "payment_id": "87654321",
                "status": "approved",
                "external_reference": str(appointment.id),
            },
        )

        self.assertEqual(response.status_code, 200)

        # Verificar que la cita fue confirmada y se guardó el monto pagado
        appointment.refresh_from_db()
        self.assertEqual(appointment.status, "CONFIRMED")
        self.assertEqual(appointment.amount_paid, Decimal("200.00"))

    @patch("core.views.requests.post")
    @patch("core.views.requests.get")
    def test_appointments_list_fallback_underpaid(self, mock_get, mock_post_refund):
        # Crear cita PENDING (seña requerida = 200.00)
        import datetime
        from django.utils import timezone

        appointment = Appointment.objects.create(
            client=self.client_user,
            service=self.service,
            start_time=timezone.now() + datetime.timedelta(days=1),
            amount=self.service.price,
            status="PENDING",
            payment_method="CASH",
        )
        self.assertEqual(appointment.status, "PENDING")

        # Mock de respuesta de MercadoPago para obtener detalles de pago
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "status": "approved",
            "external_reference": str(appointment.id),
            "transaction_amount": 150.00,
        }
        mock_response.status_code = 200
        mock_get.return_value = mock_response

        # Mock del post de reembolso
        mock_post_refund.return_value.status_code = 201
        mock_post_refund.return_value.json.return_value = {"id": "refund_id_123"}

        # Loguearse como cliente
        client = Client()
        client.login(username="client_mp", password="password123")

        # Consultar la lista de citas simulando el callback
        url = reverse("my_appointments")
        response = client.get(
            url,
            {
                "payment_id": "87654321",
                "status": "approved",
                "external_reference": str(appointment.id),
            },
        )

        self.assertEqual(response.status_code, 200)

        # Cita cancelada por pago insuficiente
        appointment.refresh_from_db()
        self.assertEqual(appointment.status, "CANCELLED")
        self.assertEqual(appointment.amount_paid, Decimal("150.00"))

        # Reembolso llamado
        mock_post_refund.assert_called_once()

    @patch("core.views.requests.post")
    def test_create_appointment_with_marketplace_fee(self, mock_post):
        import datetime
        from django.utils import timezone
        from core.models import WorkingHours

        # 1. Configurar tokens y habilitar MercadoPago con token OAuth
        self.hairdresser.mercadopago_active = True
        self.hairdresser.mercadopago_access_token = "TEST-OWNER-OAUTH-TOKEN"
        self.hairdresser.save()

        # 2. Configurar horario de atención para el día del turno
        start_time = timezone.now() + datetime.timedelta(days=1)
        target_start = start_time.replace(hour=14, minute=0, second=0, microsecond=0)

        WorkingHours.objects.create(
            hairdresser=self.hairdresser,
            day_of_week=target_start.weekday(),
            start_time=datetime.time(9, 0),
            end_time=datetime.time(18, 0),
        )

        # 3. Mock de la respuesta de creación de preferencia en MercadoPago
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "id": "pref_123456",
            "init_point": "https://www.mercadopago.com.ar/checkout/v1/redirect?pref_id=123",
            "sandbox_init_point": "https://sandbox.mercadopago.com.ar/checkout/v1/redirect?pref_id=123",
        }
        mock_response.status_code = 201
        mock_post.return_value = mock_response

        # 4. Loguearse como cliente
        client = Client()
        client.login(username="client_mp", password="password123")

        # 5. Enviar POST para reservar el turno
        url = reverse("hairdresser_detail", args=[self.hairdresser.id])
        post_data = {
            "service": self.service.id,
            "start_time": target_start.strftime("%Y-%m-%d %H:%M:%S"),
            "payment_method": "FULL",
        }
        with self.settings(
            DEBUG=True,
            MERCADOPAGO_SANDBOX=True,
            MERCADOPAGO_TEST_ACCESS_TOKEN="",
            MERCADOPAGO_COMMISSION_PERCENTAGE="3.0",
        ):
            response = client.post(url, post_data)

        self.assertEqual(response.status_code, 200)
        resp_json = response.json()
        self.assertTrue(resp_json["success"])
        self.assertEqual(
            resp_json["redirect_url"],
            "https://sandbox.mercadopago.com.ar/checkout/v1/redirect?pref_id=123",
        )

        # 6. Verificar que mock_post fue llamado con la comisión del 3%
        mock_post.assert_called_once()
        args, kwargs = mock_post.call_args

        # URL de preferencias
        self.assertEqual(args[0], "https://api.mercadopago.com/checkout/preferences")

        # Headers: Authorization Bearer del token OAuth
        self.assertEqual(
            kwargs["headers"]["Authorization"], "Bearer TEST-OWNER-OAUTH-TOKEN"
        )

        # Payload: debe incluir marketplace_fee
        payload = kwargs["json"]
        self.assertEqual(payload["marketplace_fee"], 30.0)  # 3% de 1000.00 = 30.0


class MercadoPagoOAuthTestCase(TestCase):
    def setUp(self):
        self.client = Client()
        self.owner = User.objects.create_user(
            username="owner_mp",
            password="password123",
            first_name="OwnerMP",
            last_name="Test",
            email="owner_mp@test.com",
            is_owner=True,
        )
        self.hairdresser = Hairdresser.objects.create(
            owner=self.owner, name="MP Hairdresser", address="Av. Siempre Viva 742"
        )

        # Iniciar sesión como el dueño
        self.client.login(username="owner_mp", password="password123")

    @patch("django.conf.settings.MERCADOPAGO_CLIENT_ID", "TEST_CLIENT_ID")
    def test_oauth_redirect_success(self):
        # La vista de redirección construye la URL a MercadoPago y devuelve redirect (302)
        url = reverse("mercadopago_auth_redirect")
        response = self.client.get(url)
        self.assertEqual(response.status_code, 302)

        expected_redirect_uri = self.client.get("/").wsgi_request.build_absolute_uri(
            reverse("mercadopago_callback")
        )
        self.assertIn("https://auth.mercadopago.com.ar/authorization", response.url)
        self.assertIn("client_id=TEST_CLIENT_ID", response.url)
        self.assertIn(f"state={self.hairdresser.id}", response.url)

    def test_oauth_redirect_no_client_id(self):
        # Si no está configurado MERCADOPAGO_CLIENT_ID, debe fallar amigablemente
        with patch("django.conf.settings.MERCADOPAGO_CLIENT_ID", None):
            url = reverse("mercadopago_auth_redirect")
            response = self.client.get(url)
            self.assertRedirects(response, reverse("my_hairdresser_info"))

            # Verificar mensaje de error
            messages = list(response.wsgi_request._messages)
            self.assertEqual(len(messages), 1)
            self.assertEqual(
                str(messages[0]), "MercadoPago Client ID no configurado en el servidor."
            )

    @patch("django.conf.settings.MERCADOPAGO_CLIENT_ID", "TEST_CLIENT_ID")
    @patch("django.conf.settings.MERCADOPAGO_CLIENT_SECRET", "TEST_CLIENT_SECRET")
    @patch("requests.post")
    def test_oauth_callback_success(self, mock_post):
        # Mockear la respuesta exitosa de intercambio de token de MercadoPago
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "access_token": "TEST_ACCESS_TOKEN",
            "refresh_token": "TEST_REFRESH_TOKEN",
            "user_id": 987654321,
        }
        mock_post.return_value = mock_response

        # Parámetros del callback
        callback_url = reverse("mercadopago_callback")
        response = self.client.get(
            callback_url, {"code": "TEST_AUTH_CODE", "state": str(self.hairdresser.id)}
        )

        # Debe redirigir a my_hairdresser_info
        self.assertRedirects(response, reverse("my_hairdresser_info"))

        # Refrescar peluquería de la base de datos
        self.hairdresser.refresh_from_db()
        self.assertEqual(self.hairdresser.mercadopago_access_token, "TEST_ACCESS_TOKEN")
        self.assertEqual(
            self.hairdresser.mercadopago_refresh_token, "TEST_REFRESH_TOKEN"
        )
        self.assertEqual(self.hairdresser.mercadopago_user_id, "987654321")
        self.assertTrue(self.hairdresser.mercadopago_active)

        # Verificar parámetros enviados al API de MercadoPago
        mock_post.assert_called_once()
        args, kwargs = mock_post.call_args
        self.assertEqual(args[0], "https://api.mercadopago.com/oauth/token")
        self.assertEqual(kwargs["data"]["code"], "TEST_AUTH_CODE")
        self.assertEqual(kwargs["data"]["client_id"], "TEST_CLIENT_ID")
        self.assertEqual(kwargs["data"]["client_secret"], "TEST_CLIENT_SECRET")

    def test_oauth_callback_missing_params(self):
        # Si faltan params, debe redirigir a my_hairdresser_info con error
        callback_url = reverse("mercadopago_callback")
        response = self.client.get(callback_url, {"code": "", "state": ""})
        self.assertRedirects(response, reverse("my_hairdresser_info"))

        messages = list(response.wsgi_request._messages)
        self.assertEqual(len(messages), 1)
        self.assertEqual(
            str(messages[0]), "Faltan parámetros en la respuesta de MercadoPago."
        )

    def test_oauth_callback_invalid_hairdresser_id(self):
        # Si el state (id de peluquería) no existe o no corresponde al dueño actual
        callback_url = reverse("mercadopago_callback")
        response = self.client.get(
            callback_url, {"code": "TEST_CODE", "state": "999999"}
        )
        self.assertRedirects(response, reverse("home"))

        messages = list(response.wsgi_request._messages)
        self.assertEqual(len(messages), 1)
        self.assertEqual(
            str(messages[0]), "Peluquería no encontrada o no te pertenece."
        )

    @patch("django.conf.settings.MERCADOPAGO_CLIENT_ID", "TEST_CLIENT_ID")
    @patch("django.conf.settings.MERCADOPAGO_CLIENT_SECRET", "TEST_CLIENT_SECRET")
    @patch("requests.post")
    def test_oauth_callback_api_error(self, mock_post):
        # Simular que MercadoPago responde con error 400 Bad Request
        import requests

        mock_response = MagicMock()
        mock_response.status_code = 400
        # Levantamos HTTPError al llamar a raise_for_status()
        mock_response.raise_for_status.side_effect = requests.HTTPError("Bad Request")
        mock_post.return_value = mock_response

        callback_url = reverse("mercadopago_callback")
        response = self.client.get(
            callback_url, {"code": "TEST_AUTH_CODE", "state": str(self.hairdresser.id)}
        )

        self.assertRedirects(response, reverse("my_hairdresser_info"))

        # Los tokens no deben haberse guardado y mercadopago_active debe seguir False
        self.hairdresser.refresh_from_db()
        self.assertEqual(self.hairdresser.mercadopago_access_token, "")
        self.assertFalse(self.hairdresser.mercadopago_active)

        messages = list(response.wsgi_request._messages)
        self.assertEqual(len(messages), 1)
        self.assertIn("Error al vincular con MercadoPago", str(messages[0]))

    def test_oauth_unlink_success(self):
        # Configurar tokens iniciales en la peluquería
        self.hairdresser.mercadopago_access_token = "EXISTING_TOKEN"
        self.hairdresser.mercadopago_refresh_token = "EXISTING_REFRESH"
        self.hairdresser.mercadopago_user_id = "12345"
        self.hairdresser.mercadopago_active = True
        self.hairdresser.save()

        # Llamar a desvincular
        unlink_url = reverse("mercadopago_unlink")
        response = self.client.get(unlink_url)

        self.assertRedirects(response, reverse("my_hairdresser_info"))

        # Verificar que se vaciaron los tokens y se desactivó MercadoPago
        self.hairdresser.refresh_from_db()
        self.assertEqual(self.hairdresser.mercadopago_access_token, "")
        self.assertEqual(self.hairdresser.mercadopago_refresh_token, "")
        self.assertEqual(self.hairdresser.mercadopago_user_id, "")
        self.assertFalse(self.hairdresser.mercadopago_active)


class CancelExpiredAppointmentsTestCase(TestCase):
    def setUp(self):
        self.client = Client()
        self.owner = User.objects.create_user(
            username="owner_cron",
            password="password123",
            first_name="Owner",
            last_name="Cron",
            email="owner_cron@test.com",
            is_owner=True,
        )
        self.hairdresser = Hairdresser.objects.create(
            owner=self.owner,
            name="Cron Salon",
            address="Av. Siempre Viva 321",
        )
        self.client_user = User.objects.create_user(
            username="client_cron",
            password="password123",
            first_name="Client",
            last_name="Cron",
            email="client_cron@test.com",
            is_owner=False,
        )
        self.service = Service.objects.create(
            hairdresser=self.hairdresser,
            name="Corte Express",
            price=Decimal("500.00"),
            duration_minutes=20,
        )

    def test_endpoint_unauthorized(self):
        # Sin token
        response = self.client.get(reverse("cancel_expired_appointments_endpoint"))
        self.assertEqual(response.status_code, 403)

        # Con token inválido
        response = self.client.get(
            reverse("cancel_expired_appointments_endpoint") + "?token=wrong"
        )
        self.assertEqual(response.status_code, 403)

    def test_endpoint_success(self):
        from django.utils import timezone
        import datetime

        # Cita 1: PENDING y expirada (expires_at en el pasado)
        expired_app = Appointment.objects.create(
            client=self.client_user,
            service=self.service,
            start_time=timezone.now() + datetime.timedelta(days=1),
            amount=self.service.price,
            status="PENDING",
            expires_at=timezone.now() - datetime.timedelta(minutes=5),
        )

        # Cita 2: PENDING pero no expirada (expires_at en el futuro)
        valid_app = Appointment.objects.create(
            client=self.client_user,
            service=self.service,
            start_time=timezone.now() + datetime.timedelta(days=1),
            amount=self.service.price,
            status="PENDING",
            expires_at=timezone.now() + datetime.timedelta(minutes=25),
        )

        # Cita 3: CONFIRMED (no debe cancelarse aunque expires_at esté en el pasado)
        confirmed_app = Appointment.objects.create(
            client=self.client_user,
            service=self.service,
            start_time=timezone.now() + datetime.timedelta(days=1),
            amount=self.service.price,
            status="CONFIRMED",
            expires_at=timezone.now() - datetime.timedelta(minutes=5),
        )

        url = (
            reverse("cancel_expired_appointments_endpoint")
            + f"?token={settings.CRON_SECRET}"
        )
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)

        data = response.json()
        self.assertEqual(data["status"], "success")
        self.assertEqual(data["processed"], 1)
        self.assertEqual(data["cancelled"], 1)

        # Verificar estados finales
        expired_app.refresh_from_db()
        valid_app.refresh_from_db()
        confirmed_app.refresh_from_db()

        self.assertEqual(expired_app.status, "CANCELLED")
        self.assertEqual(valid_app.status, "PENDING")
        self.assertEqual(confirmed_app.status, "CONFIRMED")


class AppointmentConcurrencyAndOverbookingTestCase(TestCase):
    def setUp(self):
        self.client = Client()
        self.owner = User.objects.create_user(
            username="owner_concur",
            password="password123",
            first_name="Owner",
            last_name="Concur",
            email="owner_concur@test.com",
            is_owner=True,
        )
        self.hairdresser = Hairdresser.objects.create(
            owner=self.owner,
            name="Concur Salon",
            address="Av. Siempre Viva 123",
            mercadopago_active=True,
            mercadopago_access_token="APP_USR-test-token",
            requires_deposit=True,
            default_deposit_type="PERCENTAGE",
            default_deposit_value=Decimal("20.00"),
            default_allow_prepayment=True,
            default_allow_on_site_payment=True,
        )
        self.client_user_1 = User.objects.create_user(
            username="client_1",
            password="password123",
            first_name="Client1",
            last_name="Test",
            email="client1@test.com",
            is_owner=False,
        )
        self.client_user_2 = User.objects.create_user(
            username="client_2",
            password="password123",
            first_name="Client2",
            last_name="Test",
            email="client2@test.com",
            is_owner=False,
        )
        self.service = Service.objects.create(
            hairdresser=self.hairdresser,
            name="Corte Premium",
            price=Decimal("1000.00"),
            duration_minutes=45,
        )

    def test_overlap_includes_active_pending_checkout(self):
        import datetime
        from django.utils import timezone
        from core.forms import AppointmentForm
        from core.models import WorkingHours

        start_time = timezone.localtime(timezone.now() + datetime.timedelta(days=1))
        start_time = start_time.replace(hour=14, minute=0, second=0, microsecond=0)

        WorkingHours.objects.create(
            hairdresser=self.hairdresser,
            day_of_week=start_time.weekday(),
            start_time=datetime.time(9, 0),
            end_time=datetime.time(18, 0),
        )

        # 1. Crear un turno PENDING con expires_at en el futuro (Client 1)
        app_1 = Appointment.objects.create(
            client=self.client_user_1,
            service=self.service,
            start_time=start_time,
            amount=self.service.price,
            status="PENDING",
            expires_at=timezone.now() + datetime.timedelta(minutes=10),
        )

        # 2. Intentar validar el mismo slot con AppointmentForm (Client 2)
        form_data = {
            "service": self.service.id,
            "start_time": start_time.strftime("%Y-%m-%d %H:%M:%S"),
            "payment_method": "FULL",
        }
        form = AppointmentForm(data=form_data, hairdresser=self.hairdresser)

        self.assertFalse(form.is_valid())
        self.assertIn("__all__", form.errors)
        self.assertEqual(
            form.errors["__all__"][0],
            "El horario seleccionado ya no está disponible. Por favor, elija otro.",
        )

    @patch("core.webhooks._verify_mp_signature", return_value=True)
    @patch("core.webhooks.requests.post")
    @patch("core.webhooks.requests.get")
    def test_webhook_resolves_concurrency_with_refund(
        self, mock_get, mock_post_refund, mock_verify_signature
    ):
        import datetime
        from django.utils import timezone

        start_time = timezone.now() + datetime.timedelta(days=1)
        start_time = start_time.replace(hour=14, minute=0, second=0, microsecond=0)

        # Crear dos turnos PENDING concurrentes para el mismo slot
        app_confirmed = Appointment.objects.create(
            client=self.client_user_1,
            service=self.service,
            start_time=start_time,
            amount=self.service.price,
            status="PENDING",
            expires_at=timezone.now() + datetime.timedelta(minutes=10),
        )

        app_refunded = Appointment.objects.create(
            client=self.client_user_2,
            service=self.service,
            start_time=start_time,
            amount=self.service.price,
            status="PENDING",
            expires_at=timezone.now() + datetime.timedelta(minutes=10),
        )

        # 1. Simular la confirmación del primer turno
        mock_get.return_value.status_code = 200
        mock_get.return_value.json.return_value = {
            "status": "approved",
            "external_reference": str(app_confirmed.id),
            "transaction_amount": 200.00,
        }

        client = Client()
        webhook_url = reverse("mercadopago_webhook", args=[self.hairdresser.id])
        payload_1 = {
            "action": "payment.created",
            "type": "payment",
            "data": {"id": "payment_approved_1"},
        }

        response = client.post(
            webhook_url, json.dumps(payload_1), content_type="application/json"
        )
        self.assertEqual(response.status_code, 200)

        app_confirmed.refresh_from_db()
        self.assertEqual(app_confirmed.status, "CONFIRMED")
        self.assertEqual(app_confirmed.amount_paid, Decimal("200.00"))

        # 2. Simular la confirmación del segundo turno
        mock_get.return_value.json.return_value = {
            "status": "approved",
            "external_reference": str(app_refunded.id),
            "transaction_amount": 200.00,
        }
        mock_post_refund.return_value.status_code = 201
        mock_post_refund.return_value.json.return_value = {"id": "refund_id_123"}

        payload_2 = {
            "action": "payment.created",
            "type": "payment",
            "data": {"id": "payment_approved_2"},
        }

        response = client.post(
            webhook_url, json.dumps(payload_2), content_type="application/json"
        )
        self.assertEqual(response.status_code, 200)

        app_refunded.refresh_from_db()
        self.assertEqual(app_refunded.status, "CANCELLED")
        self.assertEqual(app_refunded.amount_paid, Decimal("200.00"))

        mock_post_refund.assert_called_once()
        args, kwargs = mock_post_refund.call_args
        self.assertEqual(
            args[0],
            "https://api.mercadopago.com/v1/payments/payment_approved_2/refunds",
        )


class OwnerCancellationRefundTestCase(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user(
            username="owner_cancel",
            password="password123",
            first_name="Owner",
            last_name="Cancel",
            email="owner_cancel@test.com",
            is_owner=True,
        )
        self.hairdresser = Hairdresser.objects.create(
            owner=self.owner,
            name="Cancel Salon",
            address="Av. Siempre Viva 123",
            mercadopago_active=True,
            mercadopago_access_token="APP_USR-test-token",
            requires_deposit=True,
            default_deposit_type="PERCENTAGE",
            default_deposit_value=Decimal("20.00"),
            default_allow_prepayment=True,
            default_allow_on_site_payment=True,
        )
        self.client_user = User.objects.create_user(
            username="client_cancel",
            password="password123",
            first_name="Client",
            last_name="Cancel",
            email="client_cancel@test.com",
            is_owner=False,
        )
        self.service = Service.objects.create(
            hairdresser=self.hairdresser,
            name="Corte Express",
            price=Decimal("1000.00"),
            duration_minutes=30,
        )
        # Login as owner
        self.client = Client()
        self.client.login(username="owner_cancel", password="password123")

    def test_cancel_confirmed_no_payment(self):
        import datetime
        from django.utils import timezone

        # Turno confirmado con amount_paid = 0
        app = Appointment.objects.create(
            client=self.client_user,
            service=self.service,
            start_time=timezone.now() + datetime.timedelta(days=1),
            amount=self.service.price,
            status="CONFIRMED",
            amount_paid=Decimal("0.00"),
        )
        url = reverse("update_appointment_status", args=[app.pk])
        response = self.client.post(url, {"status": "CANCELLED"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "success")
        app.refresh_from_db()
        self.assertEqual(app.status, "CANCELLED")

    def test_complete_pending_appointment(self):
        import datetime
        from django.utils import timezone

        # Turno pendiente con amount_paid = 0
        app = Appointment.objects.create(
            client=self.client_user,
            service=self.service,
            start_time=timezone.now() + datetime.timedelta(days=1),
            amount=self.service.price,
            status="PENDING",
            amount_paid=Decimal("0.00"),
        )
        url = reverse("update_appointment_status", args=[app.pk])
        response = self.client.post(url, {"status": "COMPLETED"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "success")
        app.refresh_from_db()
        self.assertEqual(app.status, "COMPLETED")

    @patch("core.utils.process_mercadopago_refund")
    def test_cancel_confirmed_with_payment_success(self, mock_refund):
        import datetime
        from django.utils import timezone

        # Turno confirmado con amount_paid > 0
        app = Appointment.objects.create(
            client=self.client_user,
            service=self.service,
            start_time=timezone.now() + datetime.timedelta(days=1),
            amount=self.service.price,
            status="CONFIRMED",
            amount_paid=Decimal("200.00"),
            mercadopago_payment_id="123456",
        )
        mock_refund.return_value = {
            "success": True,
            "refund_id": "refund_999",
            "error": None,
        }
        url = reverse("update_appointment_status", args=[app.pk])
        response = self.client.post(url, {"status": "CANCELLED"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "success")
        app.refresh_from_db()
        self.assertEqual(app.status, "CANCELLED")
        mock_refund.assert_called_once_with(
            hairdresser=self.hairdresser, payment_id="123456", amount=Decimal("200.00")
        )

    @patch("core.utils.process_mercadopago_refund")
    def test_cancel_confirmed_with_payment_failed(self, mock_refund):
        import datetime
        from django.utils import timezone
        from core.models import PendingRefund

        # Turno confirmado con amount_paid > 0
        app = Appointment.objects.create(
            client=self.client_user,
            service=self.service,
            start_time=timezone.now() + datetime.timedelta(days=1),
            amount=self.service.price,
            status="CONFIRMED",
            amount_paid=Decimal("200.00"),
            mercadopago_payment_id="123456",
        )
        mock_refund.return_value = {
            "success": False,
            "refund_id": None,
            "error": "Insufficient seller balance",
        }
        url = reverse("update_appointment_status", args=[app.pk])
        response = self.client.post(url, {"status": "CANCELLED"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "success")
        self.assertIn("falló y se reintentará", response.json()["message"])
        app.refresh_from_db()
        self.assertEqual(app.status, "CANCELLED")  # Ahora sí se cancela

        # Verificar que se creó el reembolso pendiente
        pending = PendingRefund.objects.filter(appointment=app)
        self.assertTrue(pending.exists())
        self.assertEqual(pending.first().payment_id, "123456")
        self.assertEqual(pending.first().amount, Decimal("200.00"))
        self.assertEqual(pending.first().last_error, "Insufficient seller balance")

    @patch("core.utils.process_mercadopago_refund")
    @patch("core.utils.get_mercadopago_payment_id_from_api")
    def test_cancel_confirmed_payment_fallback_success(
        self, mock_get_payment, mock_refund
    ):
        import datetime
        from django.utils import timezone

        # Turno confirmado con amount_paid > 0 pero sin payment_id
        app = Appointment.objects.create(
            client=self.client_user,
            service=self.service,
            start_time=timezone.now() + datetime.timedelta(days=1),
            amount=self.service.price,
            status="CONFIRMED",
            amount_paid=Decimal("200.00"),
            mercadopago_payment_id=None,
        )
        mock_get_payment.return_value = "777888"
        mock_refund.return_value = {
            "success": True,
            "refund_id": "refund_888",
            "error": None,
        }
        url = reverse("update_appointment_status", args=[app.pk])
        response = self.client.post(url, {"status": "CANCELLED"})
        self.assertEqual(response.status_code, 200)
        app.refresh_from_db()
        self.assertEqual(app.status, "CANCELLED")
        self.assertEqual(app.mercadopago_payment_id, "777888")
        mock_get_payment.assert_called_once_with(
            hairdresser=self.hairdresser, appointment_id=app.id
        )
        mock_refund.assert_called_once_with(
            hairdresser=self.hairdresser, payment_id="777888", amount=Decimal("200.00")
        )

    def test_cancel_completed_fails(self):
        import datetime
        from django.utils import timezone

        app = Appointment.objects.create(
            client=self.client_user,
            service=self.service,
            start_time=timezone.now() + datetime.timedelta(days=1),
            amount=self.service.price,
            status="COMPLETED",
        )
        url = reverse("update_appointment_status", args=[app.pk])
        response = self.client.post(url, {"status": "CANCELLED"})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["status"], "error")
        app.refresh_from_db()
        self.assertEqual(app.status, "COMPLETED")


class ClientCancellationRefundTestCase(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user(
            username="owner_cancel",
            password="password123",
            first_name="Owner",
            last_name="Cancel",
            email="owner_cancel@test.com",
            is_owner=True,
        )
        self.hairdresser = Hairdresser.objects.create(
            owner=self.owner,
            name="Cancel Salon",
            address="Av. Siempre Viva 123",
            mercadopago_active=True,
            mercadopago_access_token="APP_USR-test-token",
            requires_deposit=True,
            default_deposit_type="PERCENTAGE",
            default_deposit_value=Decimal("20.00"),
            default_allow_prepayment=True,
            default_allow_on_site_payment=True,
        )
        self.client_user = User.objects.create_user(
            username="client_cancel",
            password="password123",
            first_name="Client",
            last_name="Cancel",
            email="client_cancel@test.com",
            is_owner=False,
        )
        self.service = Service.objects.create(
            hairdresser=self.hairdresser,
            name="Corte Express",
            price=Decimal("1000.00"),
            duration_minutes=30,
        )
        self.client = Client()
        self.client.login(username="client_cancel", password="password123")

    def test_client_cancel_success_no_payment(self):
        import datetime
        from django.utils import timezone

        app = Appointment.objects.create(
            client=self.client_user,
            service=self.service,
            start_time=timezone.now() + datetime.timedelta(days=1),
            amount=self.service.price,
            status="CONFIRMED",
            amount_paid=Decimal("0.00"),
        )
        url = reverse("cancel_appointment_client", args=[app.pk])
        response = self.client.post(url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "success")
        app.refresh_from_db()
        self.assertEqual(app.status, "CANCELLED")

    @patch("core.utils.process_mercadopago_refund")
    def test_client_cancel_success_with_refund(self, mock_refund):
        import datetime
        from django.utils import timezone

        app = Appointment.objects.create(
            client=self.client_user,
            service=self.service,
            start_time=timezone.now() + datetime.timedelta(days=1),
            amount=self.service.price,
            status="CONFIRMED",
            amount_paid=Decimal("200.00"),
            mercadopago_payment_id="123456",
        )
        mock_refund.return_value = {
            "success": True,
            "refund_id": "refund_999",
            "error": None,
        }
        url = reverse("cancel_appointment_client", args=[app.pk])
        response = self.client.post(url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "success")
        app.refresh_from_db()
        self.assertEqual(app.status, "CANCELLED")
        mock_refund.assert_called_once_with(
            hairdresser=self.hairdresser, payment_id="123456", amount=Decimal("200.00")
        )

    @patch("core.utils.process_mercadopago_refund")
    def test_client_cancel_success_with_refund_failed(self, mock_refund):
        import datetime
        from django.utils import timezone
        from core.models import PendingRefund

        app = Appointment.objects.create(
            client=self.client_user,
            service=self.service,
            start_time=timezone.now() + datetime.timedelta(days=1),
            amount=self.service.price,
            status="CONFIRMED",
            amount_paid=Decimal("200.00"),
            mercadopago_payment_id="123456",
        )
        mock_refund.return_value = {
            "success": False,
            "refund_id": None,
            "error": "Insufficient balance",
        }
        url = reverse("cancel_appointment_client", args=[app.pk])
        response = self.client.post(url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "success")
        self.assertIn("falló y se reintentará", response.json()["message"])
        app.refresh_from_db()
        self.assertEqual(app.status, "CANCELLED")

        pending = PendingRefund.objects.filter(appointment=app)
        self.assertTrue(pending.exists())
        self.assertEqual(pending.first().payment_id, "123456")
        self.assertEqual(pending.first().amount, Decimal("200.00"))
        self.assertEqual(pending.first().last_error, "Insufficient balance")

    def test_client_cancel_time_limit_fails(self):
        import datetime
        from django.utils import timezone

        app = Appointment.objects.create(
            client=self.client_user,
            service=self.service,
            start_time=timezone.now() + datetime.timedelta(hours=1),
            amount=self.service.price,
            status="PENDING",
            amount_paid=Decimal("0.00"),
        )
        url = reverse("cancel_appointment_client", args=[app.pk])
        response = self.client.post(url)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["status"], "error")
        self.assertIn("hasta 2 horas antes", response.json()["message"])
        app.refresh_from_db()
        self.assertEqual(app.status, "PENDING")

    def test_client_cancel_invalid_status_fails(self):
        import datetime
        from django.utils import timezone

        app = Appointment.objects.create(
            client=self.client_user,
            service=self.service,
            start_time=timezone.now() + datetime.timedelta(days=1),
            amount=self.service.price,
            status="COMPLETED",
            amount_paid=Decimal("0.00"),
        )
        url = reverse("cancel_appointment_client", args=[app.pk])
        response = self.client.post(url)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["status"], "error")
        app.refresh_from_db()
        self.assertEqual(app.status, "COMPLETED")

    def test_client_cancel_unauthorized_fails(self):
        import datetime
        from django.utils import timezone

        other_user = User.objects.create_user(
            username="other_client",
            password="password123",
            first_name="Other",
            last_name="Client",
            email="other@test.com",
            is_owner=False,
        )
        app = Appointment.objects.create(
            client=other_user,
            service=self.service,
            start_time=timezone.now() + datetime.timedelta(days=1),
            amount=self.service.price,
            status="PENDING",
            amount_paid=Decimal("0.00"),
        )
        url = reverse("cancel_appointment_client", args=[app.pk])
        response = self.client.post(url)
        self.assertEqual(response.status_code, 404)
        app.refresh_from_db()
        self.assertEqual(app.status, "PENDING")


from django.test import RequestFactory, override_settings
from core.webhooks import _verify_mp_signature
import hmac
import hashlib

class WebhookSignatureTestCase(TestCase):
    def setUp(self):
        self.factory = RequestFactory()

    @override_settings(DEBUG=True, MERCADOPAGO_WEBHOOK_SECRET="")
    def test_debug_true_no_secret_bypasses(self):
        # Cuando DEBUG es True y el secreto no está configurado, debe retornar True (bypass)
        request = self.factory.post("/webhook/mp/1/?id=123456&topic=payment")
        result = _verify_mp_signature(request)
        self.assertTrue(result)

    @override_settings(DEBUG=False, MERCADOPAGO_WEBHOOK_SECRET="")
    def test_debug_false_no_secret_fails(self):
        # Cuando DEBUG es False y el secreto no está configurado, debe retornar False
        request = self.factory.post("/webhook/mp/1/?id=123456&topic=payment")
        result = _verify_mp_signature(request)
        self.assertFalse(result)

    @override_settings(DEBUG=False, MERCADOPAGO_WEBHOOK_SECRET="mi_secreto")
    def test_signature_valid(self):
        # Firma válida con secreto configurado
        secret = "mi_secreto"
        ts = "1620000000"
        x_request_id = "req_id_123"
        data_id = "123456"
        manifest = f"id:{data_id};request-id:{x_request_id};ts:{ts};"
        v1 = hmac.new(
            secret.encode("utf-8"),
            manifest.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        
        signature_header = f"ts={ts},v1={v1}"
        request = self.factory.post(
            f"/webhook/mp/1/?data.id={data_id}",
            HTTP_X_SIGNATURE=signature_header,
            HTTP_X_REQUEST_ID=x_request_id
        )
        result = _verify_mp_signature(request)
        self.assertTrue(result)

    @override_settings(DEBUG=False, MERCADOPAGO_WEBHOOK_SECRET="mi_secreto")
    def test_signature_invalid(self):
        # Firma inválida con secreto configurado
        secret = "mi_secreto"
        ts = "1620000000"
        x_request_id = "req_id_123"
        data_id = "123456"
        v1 = "firma_falsa_123456"
        
        signature_header = f"ts={ts},v1={v1}"
        request = self.factory.post(
            f"/webhook/mp/1/?data.id={data_id}",
            HTTP_X_SIGNATURE=signature_header,
            HTTP_X_REQUEST_ID=x_request_id
        )
        result = _verify_mp_signature(request)
        self.assertFalse(result)

    @override_settings(DEBUG=False, MERCADOPAGO_WEBHOOK_SECRET="mi_secreto")
    def test_signature_missing_header(self):
        # Sin cabecera x-signature
        request = self.factory.post(
            "/webhook/mp/1/?data.id=123456",
            HTTP_X_REQUEST_ID="req_id_123"
        )
        result = _verify_mp_signature(request)
        self.assertFalse(result)


class PendingRefundTestCase(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user(
            username="owner_refund_test",
            password="password123",
            first_name="Owner",
            last_name="Refund",
            email="owner_refund_test@test.com",
            is_owner=True,
        )
        self.hairdresser = Hairdresser.objects.create(
            owner=self.owner,
            name="Refund Salon",
            address="Av. Siempre Viva 123",
            mercadopago_active=True,
            mercadopago_access_token="APP_USR-test-token",
        )
        self.client_user = User.objects.create_user(
            username="client_refund_test",
            password="password123",
            first_name="Client",
            last_name="Refund",
            email="client_refund_test@test.com",
            is_owner=False,
        )
        self.service = Service.objects.create(
            hairdresser=self.hairdresser,
            name="Corte Express",
            price=Decimal("1000.00"),
            duration_minutes=30,
        )
        # Crear un turno cancelado
        import datetime
        from django.utils import timezone
        self.app = Appointment.objects.create(
            client=self.client_user,
            service=self.service,
            start_time=timezone.now() + datetime.timedelta(days=1),
            amount=self.service.price,
            status="CANCELLED",
            amount_paid=Decimal("200.00"),
            mercadopago_payment_id="pay_12345",
        )
        # Cliente para llamadas HTTP
        self.client = Client()

    def test_retry_refunds_cron_unauthorized(self):
        url = reverse("retry_refunds_cron_endpoint")
        response = self.client.get(url)
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json(), {"error": "No autorizado"})

        response = self.client.get(url, {"token": "wrong_token"})
        self.assertEqual(response.status_code, 403)

    @override_settings(CRON_SECRET="secret_token_123")
    @patch("core.utils.process_mercadopago_refund")
    def test_retry_refunds_cron_success(self, mock_refund):
        from core.models import PendingRefund
        # Crear refund pendiente
        pr = PendingRefund.objects.create(
            appointment=self.app,
            payment_id="pay_12345",
            amount=Decimal("200.00"),
            last_error="Initial failure"
        )
        # Configurar mock
        mock_refund.return_value = {
            "success": True,
            "refund_id": "ref_888",
            "error": None
        }

        url = reverse("retry_refunds_cron_endpoint")
        response = self.client.get(url, {"token": "secret_token_123"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "success")
        self.assertEqual(response.json()["processed"], 1)
        self.assertEqual(response.json()["succeeded"], 1)
        self.assertEqual(response.json()["failed"], 0)

        # Verificar que se eliminó de la cola
        self.assertFalse(PendingRefund.objects.filter(pk=pr.pk).exists())
        mock_refund.assert_called_once_with(
            hairdresser=self.hairdresser,
            payment_id="pay_12345",
            amount=Decimal("200.00")
        )

    @override_settings(CRON_SECRET="secret_token_123")
    @patch("core.utils.process_mercadopago_refund")
    def test_retry_refunds_cron_failure(self, mock_refund):
        from core.models import PendingRefund
        # Crear refund pendiente
        pr = PendingRefund.objects.create(
            appointment=self.app,
            payment_id="pay_12345",
            amount=Decimal("200.00"),
            last_error="Initial failure"
        )
        # Configurar mock para que falle
        mock_refund.return_value = {
            "success": False,
            "refund_id": None,
            "error": "API Error"
        }

        url = reverse("retry_refunds_cron_endpoint")
        response = self.client.get(url, {"token": "secret_token_123"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "success")
        self.assertEqual(response.json()["processed"], 1)
        self.assertEqual(response.json()["succeeded"], 0)
        self.assertEqual(response.json()["failed"], 1)

        # Verificar que sigue en la cola con intentos incrementados
        pr.refresh_from_db()
        self.assertEqual(pr.attempts, 1)
        self.assertEqual(pr.last_error, "API Error")


class FieldEncryptionTestCase(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user(
            username="encrypt_owner",
            password="password123",
            first_name="Encrypt",
            last_name="Owner",
            email="encrypt@test.com",
            is_owner=True,
        )

    def test_field_encryption_and_decryption(self):
        from django.db import connection
        from cryptography.fernet import Fernet
        import base64
        import hashlib
        from django.conf import settings

        access_token_plain = "APP_USR-TEST-ACCESS-TOKEN-123456"
        refresh_token_plain = "TG-TEST-REFRESH-TOKEN-987654"

        hairdresser = Hairdresser.objects.create(
            owner=self.owner,
            name="Encryption Salon",
            address="Av. Las Criptas 777",
            mercadopago_access_token=access_token_plain,
            mercadopago_refresh_token=refresh_token_plain,
        )

        # 1. Verificación en el modelo Django (transparente)
        hairdresser.refresh_from_db()
        self.assertEqual(hairdresser.mercadopago_access_token, access_token_plain)
        self.assertEqual(hairdresser.mercadopago_refresh_token, refresh_token_plain)

        # 2. Verificación directa en base de datos (cifrada)
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT mercadopago_access_token, mercadopago_refresh_token FROM core_hairdresser WHERE id = %s",
                [hairdresser.id]
            )
            row = cursor.fetchone()
            db_access_token = row[0]
            db_refresh_token = row[1]

        # No deben ser iguales a los textos planos originales
        self.assertNotEqual(db_access_token, access_token_plain)
        self.assertNotEqual(db_refresh_token, refresh_token_plain)

        # 3. Comprobar que podemos descifrar el valor de la base de datos manualmente usando Fernet
        key = getattr(settings, "FIELD_ENCRYPTION_KEY", None) or settings.SECRET_KEY
        hashed = hashlib.sha256(key.encode("utf-8")).digest()
        fernet_key = base64.urlsafe_b64encode(hashed)
        fernet = Fernet(fernet_key)
        decrypted_access = fernet.decrypt(db_access_token.encode("utf-8")).decode("utf-8")
        decrypted_refresh = fernet.decrypt(db_refresh_token.encode("utf-8")).decode("utf-8")

        self.assertEqual(decrypted_access, access_token_plain)
        self.assertEqual(decrypted_refresh, refresh_token_plain)


from unittest.mock import patch, MagicMock
from django.utils import timezone
from datetime import timedelta
import requests

class MercadoPagoOAuthRenewalTests(TestCase):
    def setUp(self):
        # Crear usuarios y peluquerías
        self.owner = User.objects.create_user(
            username="owner_oauth_test",
            password="testpassword",
            is_owner=True
        )
        self.hairdresser = Hairdresser.objects.create(
            owner=self.owner,
            name="OAuth Salon",
            address="Av. Oauth 123",
            mercadopago_active=True,
            mercadopago_access_token="OLD_ACCESS_TOKEN",
            mercadopago_refresh_token="OLD_REFRESH_TOKEN",
            mercadopago_token_expires_at=timezone.now() + timedelta(days=10) # Expira en 10 días (debe renovarse)
        )

    def test_refresh_tokens_cron_unauthorized(self):
        url = reverse("refresh_mercadopago_tokens_cron_endpoint")
        
        # Petición sin token
        response = self.client.get(url)
        self.assertEqual(response.status_code, 403)
        
        # Petición con token incorrecto
        response = self.client.get(url, {"token": "WRONG_TOKEN"})
        self.assertEqual(response.status_code, 403)

    @patch("requests.post")
    @patch("django.conf.settings.MERCADOPAGO_CLIENT_ID", "TEST_CLIENT_ID")
    @patch("django.conf.settings.MERCADOPAGO_CLIENT_SECRET", "TEST_CLIENT_SECRET")
    @patch("django.conf.settings.CRON_SECRET", "CRON_TOKEN")
    def test_refresh_tokens_cron_success(self, mock_post):
        # Mock de la API de MercadoPago
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "access_token": "NEW_ACCESS_TOKEN",
            "refresh_token": "NEW_REFRESH_TOKEN",
            "expires_in": 15552000,
            "user_id": 987654321,
        }
        mock_post.return_value = mock_response

        url = reverse("refresh_mercadopago_tokens_cron_endpoint")
        response = self.client.get(url, {"token": "CRON_TOKEN"})
        
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["status"], "success")
        self.assertEqual(data["processed"], 1)
        self.assertEqual(data["succeeded"], 1)
        self.assertEqual(data["failed"], 0)

        # Refrescar de la BD
        self.hairdresser.refresh_from_db()
        self.assertEqual(self.hairdresser.mercadopago_access_token, "NEW_ACCESS_TOKEN")
        self.assertEqual(self.hairdresser.mercadopago_refresh_token, "NEW_REFRESH_TOKEN")
        self.assertGreater(self.hairdresser.mercadopago_token_expires_at, timezone.now() + timedelta(days=170))

    @patch("requests.post")
    @patch("django.conf.settings.MERCADOPAGO_CLIENT_ID", "TEST_CLIENT_ID")
    @patch("django.conf.settings.MERCADOPAGO_CLIENT_SECRET", "TEST_CLIENT_SECRET")
    @patch("django.conf.settings.CRON_SECRET", "CRON_TOKEN")
    def test_refresh_tokens_cron_failure(self, mock_post):
        # Simular fallo en requests
        mock_post.side_effect = requests.exceptions.HTTPError("Error 400 Bad Request")

        url = reverse("refresh_mercadopago_tokens_cron_endpoint")
        response = self.client.get(url, {"token": "CRON_TOKEN"})

        self.assertEqual(response.status_code, 200) # Cron no debe explotar (200 OK con info de fallo)
        data = response.json()
        self.assertEqual(data["status"], "success")
        self.assertEqual(data["processed"], 1)
        self.assertEqual(data["succeeded"], 0)
        self.assertEqual(data["failed"], 1)
        self.assertEqual(len(data["errors"]), 1)
        self.assertIn("Error al renovar token", data["errors"][0])

        # Los tokens no deben haber cambiado
        self.hairdresser.refresh_from_db()
        self.assertEqual(self.hairdresser.mercadopago_access_token, "OLD_ACCESS_TOKEN")
        self.assertEqual(self.hairdresser.mercadopago_refresh_token, "OLD_REFRESH_TOKEN")

    @patch("requests.post")
    @patch("django.conf.settings.CRON_SECRET", "CRON_TOKEN")
    def test_refresh_tokens_cron_no_refresh_needed(self, mock_post):
        # Cambiar fecha de expiración a 40 días en el futuro (no requiere refresco porque es > 30 días)
        self.hairdresser.mercadopago_token_expires_at = timezone.now() + timedelta(days=40)
        self.hairdresser.save()

        url = reverse("refresh_mercadopago_tokens_cron_endpoint")
        response = self.client.get(url, {"token": "CRON_TOKEN"})

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["status"], "success")
        self.assertEqual(data["processed"], 0)
        self.assertEqual(data["succeeded"], 0)

        # No debe haber llamado a la API
        mock_post.assert_not_called()


class PaymentTransactionTestCase(TestCase):
    def setUp(self):
        from decimal import Decimal
        from datetime import timedelta
        from django.utils import timezone
        
        # Creamos usuario dueño
        self.owner = User.objects.create_user(
            username="owner_audit",
            password="password123",
            first_name="Owner",
            last_name="Test",
            email="owner_audit@test.com",
            is_owner=True,
        )
        # Creamos perfil de peluquería
        self.hairdresser = Hairdresser.objects.create(
            owner=self.owner,
            name="Audit Hairdresser",
            address="Audit Address",
            mercadopago_access_token="TEST_TOKEN",
            mercadopago_active=True,
        )
        # Cliente
        self.client_user = User.objects.create_user(
            username="client_audit",
            password="password123",
            first_name="Client",
            last_name="Test",
            email="client_audit@test.com",
            is_owner=False,
        )
        # Servicio
        from core.models import Service
        self.service = Service.objects.create(
            hairdresser=self.hairdresser,
            name="Audit Service",
            price=Decimal("1500.00"),
            duration_minutes=30,
        )
        # Appointment
        from core.models import Appointment
        self.appointment = Appointment.objects.create(
            client=self.client_user,
            service=self.service,
            start_time=timezone.now() + timedelta(days=1),
            amount=Decimal("1500.00"),
            status="PENDING",
            payment_method="FULL",
        )

    def test_payment_transaction_immutability(self):
        from decimal import Decimal
        from core.models import PaymentTransaction
        from django.core.exceptions import ValidationError
        
        # Crear transacción
        tx = PaymentTransaction.objects.create(
            appointment=self.appointment,
            payment_id="tx_123456",
            amount=Decimal("1500.00"),
            status="approved",
        )
        self.assertEqual(tx.payment_id, "tx_123456")
        
        # Intentar eliminarla debe fallar
        with self.assertRaises(ValidationError):
            tx.delete()
            
        # Verificar que sigue existiendo
        self.assertTrue(PaymentTransaction.objects.filter(pk=tx.pk).exists())

    @patch("requests.get")
    def test_webhook_creates_payment_transaction(self, mock_get):
        from decimal import Decimal
        from core.models import PaymentTransaction
        
        # Simular respuesta de MercadoPago
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "status": "approved",
            "transaction_amount": 1500.00,
            "external_reference": str(self.appointment.id),
        }
        mock_get.return_value = mock_response

        # Configurar webhook_secret para el test
        with patch("django.conf.settings.MERCADOPAGO_WEBHOOK_SECRET", "test_secret"), \
             patch("core.webhooks._verify_mp_signature", return_value=True):
            
            # Llamar al webhook
            url = reverse("mercadopago_webhook", args=[self.hairdresser.id])
            response = self.client.post(
                url + "?topic=payment&id=mp_payment_999",
                content_type="application/json",
            )
            self.assertEqual(response.status_code, 200)

        # Verificar que se creó la transacción de auditoría
        tx = PaymentTransaction.objects.filter(payment_id="mp_payment_999").first()
        self.assertIsNotNone(tx)
        self.assertEqual(tx.appointment, self.appointment)
        self.assertEqual(tx.amount, Decimal("1500.00"))
        self.assertEqual(tx.status, "approved")

    @patch("requests.get")
    def test_fallback_view_creates_payment_transaction(self, mock_get):
        from decimal import Decimal
        from core.models import PaymentTransaction
        
        # Login
        self.client.login(username="client_audit", password="password123")
        
        # Simular respuesta de MercadoPago
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "status": "approved",
            "transaction_amount": 1500.00,
            "external_reference": str(self.appointment.id),
        }
        mock_get.return_value = mock_response

        # Llamar a la vista de mis turnos con parámetros de retorno de MP
        url = reverse("my_appointments")
        response = self.client.get(
            url,
            {
                "payment_id": "mp_fallback_888",
                "status": "approved",
                "external_reference": str(self.appointment.id),
            },
        )
        self.assertEqual(response.status_code, 200)

        # Verificar que se creó la transacción de auditoría
        tx = PaymentTransaction.objects.filter(payment_id="mp_fallback_888").first()
        self.assertIsNotNone(tx)
        self.assertEqual(tx.appointment, self.appointment)
        self.assertEqual(tx.amount, Decimal("1500.00"))
        self.assertEqual(tx.status, "approved")


class BrevoEmailBackendTestCase(TestCase):
    def setUp(self):
        from django.core.mail import EmailMessage, EmailMultiAlternatives
        from core.email_backend import BrevoEmailBackend

        self.backend = BrevoEmailBackend(fail_silently=False)
        # Seteamos manualmente la API key para los tests
        self.backend.api_key = "test_key_abc_123"

        self.message = EmailMessage(
            subject="Test Subject",
            body="Test plain text body",
            from_email="Sender <sender@example.com>",
            to=["recipient@example.com", "Name <recipient2@example.com>"],
        )

        self.html_message = EmailMultiAlternatives(
            subject="Test HTML Subject",
            body="Test plain text body",
            from_email="sender@example.com",
            to=["recipient@example.com"],
        )
        self.html_message.attach_alternative("<p>Test html body</p>", "text/html")

    @patch("requests.post")
    def test_send_message_success(self, mock_post):
        mock_response = MagicMock()
        mock_response.status_code = 201
        mock_response.json.return_value = {"messageId": "123456"}
        mock_post.return_value = mock_response

        count = self.backend.send_messages([self.message])
        self.assertEqual(count, 1)

        mock_post.assert_called_once()
        args, kwargs = mock_post.call_args
        self.assertEqual(args[0], "https://api.brevo.com/v3/smtp/email")
        self.assertEqual(kwargs["headers"]["api-key"], "test_key_abc_123")
        self.assertEqual(kwargs["headers"]["content-type"], "application/json")

        payload = kwargs["json"]
        self.assertEqual(payload["subject"], "Test Subject")
        self.assertEqual(payload["sender"], {"email": "sender@example.com", "name": "Sender"})
        self.assertEqual(payload["to"], [
            {"email": "recipient@example.com", "name": "recipient@example.com"},
            {"email": "recipient2@example.com", "name": "Name"},
        ])
        self.assertEqual(payload["textContent"], "Test plain text body")
        self.assertNotIn("htmlContent", payload)

    @patch("requests.post")
    def test_send_html_message_success(self, mock_post):
        mock_response = MagicMock()
        mock_response.status_code = 201
        mock_post.return_value = mock_response

        count = self.backend.send_messages([self.html_message])
        self.assertEqual(count, 1)

        mock_post.assert_called_once()
        kwargs = mock_post.call_args[1]
        payload = kwargs["json"]
        self.assertEqual(payload["htmlContent"], "<p>Test html body</p>")
        self.assertEqual(payload["textContent"], "Test plain text body")

    @patch("requests.post")
    def test_send_messages_empty_list(self, mock_post):
        count = self.backend.send_messages([])
        self.assertEqual(count, 0)
        mock_post.assert_not_called()

    def test_missing_api_key_raises_error(self):
        from core.email_backend import BrevoEmailBackend
        backend = BrevoEmailBackend(fail_silently=False)
        backend.api_key = ""
        with self.assertRaises(ValueError):
            backend.send_messages([self.message])

    def test_missing_api_key_fail_silently(self):
        from core.email_backend import BrevoEmailBackend
        backend = BrevoEmailBackend(fail_silently=True)
        backend.api_key = ""
        count = backend.send_messages([self.message])
        self.assertEqual(count, 0)

    @patch("requests.post")
    def test_api_error_fail_silently_true(self, mock_post):
        mock_response = MagicMock()
        mock_response.status_code = 400
        mock_response.text = "Bad Request"
        mock_post.return_value = mock_response

        self.backend.fail_silently = True
        count = self.backend.send_messages([self.message])
        self.assertEqual(count, 0)

    @patch("requests.post")
    def test_api_error_fail_silently_false(self, mock_post):
        import requests
        mock_response = MagicMock()
        mock_response.status_code = 400
        mock_response.text = "Bad Request"
        mock_response.raise_for_status.side_effect = requests.HTTPError("Bad Request")
        mock_post.return_value = mock_response

        self.backend.fail_silently = False
        with self.assertRaises(requests.HTTPError):
            self.backend.send_messages([self.message])


class ServiceViewsTestCase(TestCase):
    def setUp(self):
        self.client = Client()
        # Creamos usuario dueño
        self.owner = User.objects.create_user(
            username="owner_service_test",
            password="password123",
            first_name="Owner",
            last_name="Test",
            email="owner_service_test@test.com",
            is_owner=True,
        )
        self.hairdresser = Hairdresser.objects.create(
            owner=self.owner, name="Owner's Hairdresser", address="Test Address"
        )
        # Creamos otro usuario cliente (no dueño)
        self.client_user = User.objects.create_user(
            username="client_service_test",
            password="password123",
            first_name="Client",
            last_name="Test",
            email="client_service_test@test.com",
            is_owner=False,
        )

    def test_service_create_success_ajax(self):
        self.client.login(username="owner_service_test", password="password123")
        response = self.client.post(
            reverse("service_create"),
            {
                "name": "Corte de pelo",
                "description": "Un corte clásico",
                "price": "1200.00",
                "duration_minutes": 30,
                "override_deposit": "False",
                "deposit_type": "FIXED",
                "deposit_value": "0.00",
                "override_payment_modes": "False",
                "allow_prepayment": "True",
                "allow_on_site_payment": "True",
            },
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"success": True})
        
        # Verificar que el servicio se guardó en la DB
        from core.models import Service
        service = Service.objects.get(name="Corte de pelo")
        self.assertEqual(service.hairdresser, self.hairdresser)
        self.assertEqual(service.price, 1200.00)
        self.assertEqual(service.duration_minutes, 30)

    def test_service_create_invalid_negative_price(self):
        self.client.login(username="owner_service_test", password="password123")
        response = self.client.post(
            reverse("service_create"),
            {
                "name": "Corte de pelo",
                "description": "Un corte clásico",
                "price": "-50.00",  # Precio negativo
                "duration_minutes": 30,
                "override_deposit": "False",
                "deposit_type": "FIXED",
                "deposit_value": "0.00",
                "override_payment_modes": "False",
                "allow_prepayment": "True",
                "allow_on_site_payment": "True",
            },
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(response.status_code, 400)
        data = response.json()
        self.assertFalse(data["success"])
        self.assertIn("price", data["errors"])

    def test_service_create_invalid_negative_duration(self):
        self.client.login(username="owner_service_test", password="password123")
        response = self.client.post(
            reverse("service_create"),
            {
                "name": "Corte de pelo",
                "description": "Un corte clásico",
                "price": "1200.00",
                "duration_minutes": -5,  # Duración negativa
                "override_deposit": "False",
                "deposit_type": "FIXED",
                "deposit_value": "0.00",
                "override_payment_modes": "False",
                "allow_prepayment": "True",
                "allow_on_site_payment": "True",
            },
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(response.status_code, 400)
        data = response.json()
        self.assertFalse(data["success"])
        self.assertIn("duration_minutes", data["errors"])

    def test_service_update_success_ajax(self):
        from core.models import Service
        service = Service.objects.create(
            hairdresser=self.hairdresser,
            name="Corte viejo",
            price=1000.00,
            duration_minutes=25,
        )
        self.client.login(username="owner_service_test", password="password123")
        response = self.client.post(
            reverse("service_update", kwargs={"pk": service.pk}),
            {
                "name": "Corte nuevo",
                "price": "1500.00",
                "duration_minutes": 35,
                "override_deposit": "False",
                "deposit_type": "FIXED",
                "deposit_value": "0.00",
                "override_payment_modes": "False",
                "allow_prepayment": "True",
                "allow_on_site_payment": "True",
            },
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"success": True})
        
        service.refresh_from_db()
        self.assertEqual(service.name, "Corte nuevo")
        self.assertEqual(service.price, 1500.00)
        self.assertEqual(service.duration_minutes, 35)

    def test_service_create_unauthorized(self):
        # Intentar crear servicio sin loguearse
        response = self.client.post(
            reverse("service_create"),
            {
                "name": "Corte de pelo",
                "price": "1200.00",
                "duration_minutes": 30,
            },
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        # OwnerRequiredMixin redirecciona al login si no está logueado
        self.assertEqual(response.status_code, 302)

        # Logueado como cliente normal (no dueño)
        self.client.login(username="client_service_test", password="password123")
        response = self.client.post(
            reverse("service_create"),
            {
                "name": "Corte de pelo",
                "price": "1200.00",
                "duration_minutes": 30,
            },
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        # Redirecciona a home si es cliente y no dueño
        self.assertEqual(response.status_code, 302)


class HomeSearchFilterTestCase(TestCase):
    def setUp(self):
        self.client = Client()
        
        # Creamos dueños
        self.owner1 = User.objects.create_user(
            username="owner1",
            password="password123",
            first_name="Owner1",
            last_name="Test",
            is_owner=True,
        )
        self.owner2 = User.objects.create_user(
            username="owner2",
            password="password123",
            first_name="Owner2",
            last_name="Test",
            is_owner=True,
        )

        # Peluquería 1: "Barbería Premium"
        # Dirección: "Calle Falsa 123"
        # Descripción: "Los mejores cortes de barba"
        self.hairdresser1 = Hairdresser.objects.create(
            owner=self.owner1,
            name="Barbería Premium",
            address="Calle Falsa 123",
            description="Los mejores cortes de barba",
            latitude=-24.7821,
            longitude=-65.4232,
        )
        # Horarios para que esté completa
        from core.models import WorkingHours
        WorkingHours.objects.create(
            hairdresser=self.hairdresser1,
            day_of_week=1,
            start_time="09:00",
            end_time="18:00",
        )
        # Servicio 1: "Corte y Barba"
        from core.models import Service
        self.service1 = Service.objects.create(
            hairdresser=self.hairdresser1,
            name="Corte y Barba",
            price=1500.00,
            duration_minutes=45,
        )

        # Peluquería 2: "Estilo & Color"
        # Dirección: "Av. Siempre Viva 742"
        # Descripción: "Especialistas en tintura y peinado"
        self.hairdresser2 = Hairdresser.objects.create(
            owner=self.owner2,
            name="Estilo & Color",
            address="Av. Siempre Viva 742",
            description="Especialistas en tintura y peinado",
            latitude=-24.7899,
            longitude=-65.4111,
        )
        # Horarios para que esté completa
        WorkingHours.objects.create(
            hairdresser=self.hairdresser2,
            day_of_week=2,
            start_time="10:00",
            end_time="19:00",
        )
        # Servicio 2: "Tinte Completo"
        self.service2 = Service.objects.create(
            hairdresser=self.hairdresser2,
            name="Tinte Completo",
            price=3000.00,
            duration_minutes=90,
        )

        # Crear imágenes para que puedan ser consideradas destacadas (featured)
        from django.core.files.uploadedfile import SimpleUploadedFile
        from core.models import HairdresserImage
        
        dummy_image = SimpleUploadedFile(
            name='test_image.jpg',
            content=b'\x47\x49\x46\x38\x39\x61\x01\x00\x01\x00\x80\x00\x00\x00\x00\x00\xff\xff\xff\x21\xf9\x04\x01\x00\x00\x00\x00\x2c\x00\x00\x00\x00\x01\x00\x01\x00\x00\x02\x02\x44\x01\x00\x3b',
            content_type='image/jpeg'
        )
        
        img1 = HairdresserImage.objects.create(
            hairdresser=self.hairdresser1,
            image=dummy_image,
            caption="Test cover 1"
        )
        self.hairdresser1.cover_image = img1
        self.hairdresser1.save()

        img2 = HairdresserImage.objects.create(
            hairdresser=self.hairdresser2,
            image=dummy_image,
            caption="Test cover 2"
        )
        self.hairdresser2.cover_image = img2
        self.hairdresser2.save()

    def test_home_view_no_filters(self):
        response = self.client.get(reverse("home"))
        self.assertEqual(response.status_code, 200)
        hairdressers = response.context["hairdressers"]
        self.assertEqual(len(hairdressers), 2)
        # Al no haber filtros, destacados debería tener elementos
        self.assertTrue(len(response.context["featured_hairdressers"]) > 0)

    def test_home_view_filter_by_text(self):
        # Buscar "Barbería"
        response = self.client.get(reverse("home"), {"q": "Barbería"})
        self.assertEqual(response.status_code, 200)
        hairdressers = response.context["hairdressers"]
        self.assertEqual(len(hairdressers), 1)
        self.assertEqual(hairdressers[0].name, "Barbería Premium")
        # El carrusel de destacados debe estar vacío si hay filtros activos
        self.assertEqual(len(response.context["featured_hairdressers"]), 0)

        # Buscar "Siempre Viva"
        response = self.client.get(reverse("home"), {"q": "Siempre Viva"})
        self.assertEqual(response.status_code, 200)
        hairdressers = response.context["hairdressers"]
        self.assertEqual(len(hairdressers), 1)
        self.assertEqual(hairdressers[0].name, "Estilo & Color")

        # Buscar término que no existe
        response = self.client.get(reverse("home"), {"q": "Inexistente"})
        self.assertEqual(response.status_code, 200)
        hairdressers = response.context["hairdressers"]
        self.assertEqual(len(hairdressers), 0)

    def test_home_view_filter_by_service(self):
        # Filtrar por "corte"
        response = self.client.get(reverse("home"), {"service": "corte"})
        self.assertEqual(response.status_code, 200)
        hairdressers = response.context["hairdressers"]
        self.assertEqual(len(hairdressers), 1)
        self.assertEqual(hairdressers[0].name, "Barbería Premium")

        # Filtrar por "color"
        response = self.client.get(reverse("home"), {"service": "color"})
        self.assertEqual(response.status_code, 200)
        hairdressers = response.context["hairdressers"]
        self.assertEqual(len(hairdressers), 1)
        self.assertEqual(hairdressers[0].name, "Estilo & Color")

    def test_map_data_filtered(self):
        # Sin filtros
        response = self.client.get(reverse("map_data"))
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(len(data), 2)

        # Filtrar por "barberia"
        response = self.client.get(reverse("map_data"), {"service": "barberia"})
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]["name"], "Barbería Premium")

        # Buscar "Estilo"
        response = self.client.get(reverse("map_data"), {"q": "Estilo"})
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]["name"], "Estilo & Color")


class AppointmentTimeAdjustmentTestCase(TestCase):
    def setUp(self):
        from core.models import User, Hairdresser, Service, Appointment
        from decimal import Decimal
        import datetime
        from django.utils import timezone

        # Crear dueño
        self.owner = User.objects.create_user(
            username="owner_adj",
            password="password123",
            first_name="Owner",
            last_name="Test",
            email="owneradj@test.com",
            is_owner=True,
        )
        # Peluquería
        self.hairdresser = Hairdresser.objects.create(
            owner=self.owner, name="Peluquería Test", address="Calle Falsa 123"
        )
        # Servicio
        self.service = Service.objects.create(
            hairdresser=self.hairdresser,
            name="Corte",
            price=Decimal("1500.00"),
            duration_minutes=30,
        )
        # Cliente
        self.client_user = User.objects.create_user(
            username="client_adj",
            password="password123",
            first_name="Client",
            last_name="Test",
            email="clientadj@test.com",
            is_owner=False,
        )

        # Login para el cliente HTTP
        self.client = Client()
        self.client.login(username="owner_adj", password="password123")

    def test_extra_minutes_affects_end_time(self):
        import datetime
        from django.utils import timezone
        from core.models import Appointment

        now = timezone.now().replace(microsecond=0)
        app = Appointment.objects.create(
            client=self.client_user,
            service=self.service,
            start_time=now,
            amount=self.service.price,
            status="CONFIRMED",
            extra_minutes=10,
        )
        # end_time should be start_time + 30m (service) + 10m (extra) = 40m
        self.assertEqual(app.end_time, now + datetime.timedelta(minutes=40))

        # Modifying extra_minutes and saving should update end_time
        app.extra_minutes = -10
        app.save()
        self.assertEqual(app.end_time, now + datetime.timedelta(minutes=20))

    def test_reschedule_cascade_and_escalated_notifications(self):
        import datetime
        from django.utils import timezone
        from core.models import Appointment
        from core.utils import reschedule_subsequent_appointments

        now = timezone.now().replace(microsecond=0)
        # Turno 1: empieza en now, dura 30m (original)
        app1 = Appointment.objects.create(
            client=self.client_user,
            service=self.service,
            start_time=now,
            amount=self.service.price,
            status="CONFIRMED"
        )

        # Turno 2: empieza en 130m del futuro (más de 2 horas)
        app2 = Appointment.objects.create(
            client=self.client_user,
            service=self.service,
            start_time=now + datetime.timedelta(minutes=130),
            amount=self.service.price,
            status="CONFIRMED"
        )

        # Turno 3: empieza en now + 45 min (entre 30 y 60 min)
        app3 = Appointment.objects.create(
            client=self.client_user,
            service=self.service,
            start_time=now + datetime.timedelta(minutes=45),
            amount=self.service.price,
            status="CONFIRMED"
        )

        # Turno 4: empieza en now + 115 min (menos de 2 horas)
        app4 = Appointment.objects.create(
            client=self.client_user,
            service=self.service,
            start_time=now + datetime.timedelta(minutes=115),
            amount=self.service.price,
            status="CONFIRMED"
        )

        # Desplazamos Turno 1 en +10 min
        # Esto debería reprogramar:
        # - Turno 2: 130 -> 140 min (> 120 min, no cruza, no se notifica)
        # - Turno 3: 45 -> 55 min (30-60 min, no cruza, no se notifica)
        # - Turno 4: 115 -> 125 min (cruza el umbral de 120m hacia arriba, SE NOTIFICA)
        affected = reschedule_subsequent_appointments(app1, 10)

        app2.refresh_from_db()
        app3.refresh_from_db()
        app4.refresh_from_db()

        self.assertEqual(app2.start_time, now + datetime.timedelta(minutes=140))
        self.assertEqual(app3.start_time, now + datetime.timedelta(minutes=55))
        self.assertEqual(app4.start_time, now + datetime.timedelta(minutes=125))

        self.assertIn(app4, affected)
        self.assertNotIn(app2, affected)
        self.assertNotIn(app3, affected)

    @patch("core.utils.send_push_notification")
    @patch("core.utils.send_html_email")
    def test_adjust_appointment_time_endpoint(self, mock_email, mock_push):
        import datetime
        from django.utils import timezone
        from core.models import Appointment

        mock_email.return_value = True

        now = timezone.now().replace(microsecond=0)
        app = Appointment.objects.create(
            client=self.client_user,
            service=self.service,
            start_time=now,
            amount=self.service.price,
            status="CONFIRMED"
        )

        url = reverse("adjust_appointment_time", args=[app.pk])
        response = self.client.post(url, {"delta": "5"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "success")

        app.refresh_from_db()
        self.assertEqual(app.extra_minutes, 5)
        self.assertEqual(app.end_time, now + datetime.timedelta(minutes=35))

    @patch("core.utils.send_push_notification")
    @patch("core.utils.send_html_email")
    def test_early_finish_creates_offer(self, mock_email, mock_push):
        import datetime
        from django.utils import timezone
        from core.models import Appointment, EarlyStartOffer

        mock_email.return_value = True

        now = timezone.now().replace(microsecond=0)
        # Turno 1: en curso, finaliza en now + 20 min
        app1 = Appointment.objects.create(
            client=self.client_user,
            service=self.service,
            start_time=now - datetime.timedelta(minutes=10),
            amount=self.service.price,
            status="CONFIRMED"
        )

        # Turno 2: en el futuro, hoy mismo
        app2 = Appointment.objects.create(
            client=self.client_user,
            service=self.service,
            start_time=now + datetime.timedelta(minutes=40),
            amount=self.service.price,
            status="CONFIRMED"
        )

        # Completar Turno 1 ahora (20 min antes)
        url = reverse("update_appointment_status", args=[app1.pk])
        response = self.client.post(url, {"status": "COMPLETED"})
        self.assertEqual(response.status_code, 200)
        self.assertIn("ofreció", response.json()["message"])

        # Debería haberse creado un EarlyStartOffer para el Turno 2
        offer = EarlyStartOffer.objects.filter(appointment=app2).first()
        self.assertIsNotNone(offer)
        self.assertFalse(offer.accepted)
        self.assertEqual(offer.minutes_available, 20)

    @patch("core.utils.send_push_notification")
    @patch("core.utils.send_html_email")
    def test_accept_early_start_offer(self, mock_email, mock_push):
        import datetime
        from django.utils import timezone
        from core.models import Appointment, EarlyStartOffer

        mock_email.return_value = True

        now = timezone.now().replace(microsecond=0)
        app = Appointment.objects.create(
            client=self.client_user,
            service=self.service,
            start_time=now + datetime.timedelta(minutes=40),
            amount=self.service.price,
            status="CONFIRMED"
        )

        offer = EarlyStartOffer.objects.create(
            appointment=app,
            token="test-token-123",
            minutes_available=20,
            new_start_time=now,
            expires_at=now + datetime.timedelta(minutes=2)
        )

        url = reverse("accept_early_start", args=[offer.token])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "¡Excelente!")

        app.refresh_from_db()
        self.assertEqual(app.start_time, now)
        offer.refresh_from_db()
        self.assertTrue(offer.accepted)

    def test_expired_early_start_offer(self):
        import datetime
        from django.utils import timezone
        from core.models import Appointment, EarlyStartOffer

        now = timezone.now().replace(microsecond=0)
        app = Appointment.objects.create(
            client=self.client_user,
            service=self.service,
            start_time=now + datetime.timedelta(minutes=40),
            amount=self.service.price,
            status="CONFIRMED"
        )

        # Oferta expirada hace 1 min
        offer = EarlyStartOffer.objects.create(
            appointment=app,
            token="test-token-expired",
            minutes_available=20,
            new_start_time=now,
            expires_at=now - datetime.timedelta(minutes=1)
        )

        url = reverse("accept_early_start", args=[offer.token])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "ha expirado")

        app.refresh_from_db()
        # El horario original se debe mantener
        self.assertEqual(app.start_time, now + datetime.timedelta(minutes=40))
        offer.refresh_from_db()
        self.assertFalse(offer.accepted)


