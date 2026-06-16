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
