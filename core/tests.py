from unittest.mock import patch, MagicMock
from django.test import TestCase, Client
from django.urls import reverse
from django.contrib.auth import get_user_model
from core.utils import geocode_address
from core.models import Hairdresser

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
            is_owner=True
        )
        # Creamos perfil de peluquería
        self.hairdresser = Hairdresser.objects.create(
            owner=self.owner,
            name="Test Hairdresser",
            address="Initial Address"
        )
        
        # Creamos cliente normal (no dueño)
        self.client_user = User.objects.create_user(
            username="client",
            password="password123",
            first_name="Client",
            last_name="Test",
            email="client@test.com",
            is_owner=False
        )

        # Creamos un dueño sin peluquería para probar edge case
        self.owner_no_profile = User.objects.create_user(
            username="owner_no_profile",
            password="password123",
            first_name="OwnerNoProfile",
            last_name="Test",
            email="ownernoprofile@test.com",
            is_owner=True
        )

    @patch('core.utils.requests.get')
    def test_geocode_address_success(self, mock_get):
        # Configurar mock de respuesta exitosa de Nominatim
        mock_response = MagicMock()
        mock_response.json.return_value = [
            {'lat': '-24.789123', 'lon': '-65.412345'}
        ]
        mock_response.status_code = 200
        mock_get.return_value = mock_response

        result = geocode_address("Av. Bolivia 5150, Salta")
        self.assertIsNotNone(result)
        self.assertEqual(result['latitude'], -24.789123)
        self.assertEqual(result['longitude'], -65.412345)

        # Verificar parámetros de llamada
        mock_get.assert_called_once()
        args, kwargs = mock_get.call_args
        self.assertEqual(kwargs['params']['q'], "Av. Bolivia 5150, Salta")
        self.assertEqual(kwargs['params']['format'], "json")
        self.assertIn("User-Agent", kwargs['headers'])

    @patch('core.utils.requests.get')
    def test_geocode_address_no_results(self, mock_get):
        # Nominatim retorna lista vacía
        mock_response = MagicMock()
        mock_response.json.return_value = []
        mock_response.status_code = 200
        mock_get.return_value = mock_response

        result = geocode_address("Direccion Invalida 123456")
        self.assertIsNone(result)

    @patch('core.utils.requests.get')
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
        response = self.client.get(reverse('geocode_address_api') + "?address=Salta")
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json(), {"error": "No autorizado"})

    def test_api_client_access(self):
        # Usuario cliente (is_owner=False) debe recibir 403
        self.client.login(username="client", password="password123")
        response = self.client.get(reverse('geocode_address_api') + "?address=Salta")
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json(), {"error": "No autorizado"})

    def test_api_owner_no_profile_access(self):
        # Dueño sin peluquería debe recibir 403
        self.client.login(username="owner_no_profile", password="password123")
        response = self.client.get(reverse('geocode_address_api') + "?address=Salta")
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json(), {"error": "No autorizado"})

    @patch('core.views.geocode_address')
    def test_api_owner_success(self, mock_geocode):
        # Dueño autenticado consulta dirección válida
        mock_geocode.return_value = {'latitude': -24.789, 'longitude': -65.412}
        self.client.login(username="owner", password="password123")

        response = self.client.get(reverse('geocode_address_api') + "?address=Salta")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data['success'])
        self.assertEqual(data['latitude'], -24.789)
        self.assertEqual(data['longitude'], -65.412)
        mock_geocode.assert_called_once_with("Salta")

    @patch('core.views.geocode_address')
    def test_api_owner_not_found(self, mock_geocode):
        # Dirección no geocodificable
        mock_geocode.return_value = None
        self.client.login(username="owner", password="password123")

        response = self.client.get(reverse('geocode_address_api') + "?address=Invalida")
        self.assertEqual(response.status_code, 404)
        data = response.json()
        self.assertFalse(data['success'])
        self.assertEqual(data['error'], "No se pudo encontrar la dirección en el mapa.")

    def test_api_owner_missing_address(self):
        # Parámetro address ausente o vacío
        self.client.login(username="owner", password="password123")

        response = self.client.get(reverse('geocode_address_api'))
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json(), {"error": "La dirección es requerida."})

        response = self.client.get(reverse('geocode_address_api') + "?address=   ")
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
            is_owner=True
        )
        self.hairdresser = Hairdresser.objects.create(
            owner=self.owner,
            name="Salon Notify",
            address="Av. Siempre Viva 742"
        )
        self.client_user = User.objects.create_user(
            username="client_notify",
            password="password123",
            first_name="ClientName",
            last_name="ClientLastName",
            email="client_notify@test.com",
            is_owner=False
        )
        self.service = Service.objects.create(
            hairdresser=self.hairdresser,
            name="Corte Clasico",
            price=20.0,
            duration_minutes=30
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
            "is_owner": False
        }
        response = self.client.post(reverse("signup"), signup_data)
        self.assertEqual(response.status_code, 302) # Redirige al home
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
        self.assertEqual(response.status_code, 302) # Redirige al perfil
        self.assertEqual(len(mail.outbox), 1)
        email = mail.outbox[0]
        self.assertEqual(email.to, ["client_notify@test.com"])
        self.assertIn("Confirmación de seguridad: Cambio de contraseña - Stilo", email.subject)

    def test_appointment_creation_emails(self):
        mail.outbox = []
        start_time = timezone.now() + datetime.timedelta(days=2)
        appointment = Appointment.objects.create(
            client=self.client_user,
            service=self.service,
            start_time=start_time
        )
        self.assertEqual(len(mail.outbox), 2)
        recipients = [email.to[0] for email in mail.outbox]
        self.assertIn("client_notify@test.com", recipients)
        self.assertIn("owner_notify@test.com", recipients)
        
        subjects = [email.subject for email in mail.outbox]
        self.assertIn("Confirmación de Turno - Stilo", subjects)
        self.assertIn("Nueva Reserva Recibida - Stilo", subjects)

    def test_appointment_cancellation_emails(self):
        start_time = timezone.now() + datetime.timedelta(days=2)
        appointment = Appointment.objects.create(
            client=self.client_user,
            service=self.service,
            start_time=start_time
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
            status="CONFIRMED"
        )
        
        today = timezone.localtime(timezone.now())
        appointment_today = Appointment.objects.create(
            client=self.client_user,
            service=self.service,
            start_time=today,
            status="CONFIRMED"
        )
        
        appointment_cancelled = Appointment.objects.create(
            client=self.client_user,
            service=self.service,
            start_time=tomorrow,
            status="CANCELLED"
        )
        
        mail.outbox = []
        
        url = reverse("send_reminders") + f"?token={settings.REMINDER_TOKEN}"
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data["success"])
        self.assertEqual(data["sent_count"], 1)
        
        self.assertEqual(len(mail.outbox), 1)
        email = mail.outbox[0]
        self.assertEqual(email.to, ["client_notify@test.com"])
        self.assertIn("Recordatorio de Turno - Stilo", email.subject)

