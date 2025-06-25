import random
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone
from django.db import transaction

from faker import Faker

from core.models import User, Hairdresser, Service, Appointment, Review, Offer

NUM_OWNERS = 5
NUM_CLIENTS = 20
NUM_APPOINTMENTS_PER_CLIENT = 2
SERVICES_LIST = [
    ("Corte de Caballero", 15.00, 30),
    ("Corte y Barba", 22.50, 45),
    ("Corte Femenino", 25.00, 60),
    ("Peinado y Secado", 18.00, 35),
    ("Tinte Completo", 50.00, 120),
    ("Mechas", 70.00, 180),
    ("Tratamiento de Keratina", 90.00, 150),
]


class Command(BaseCommand):
    help = "Genera datos de prueba para el proyecto Stilo"

    @transaction.atomic  # Asegura que todo o nada se ejecute
    def handle(self, *args, **kwargs):
        self.stdout.write(self.style.WARNING("Limpiando la base de datos..."))
        models_to_clear = [Appointment, Review, Offer, Service, Hairdresser, User]
        for m in models_to_clear:
            m.objects.all().delete()

        fake = Faker("es_ES")

        self.stdout.write(self.style.SUCCESS("Base de datos limpiada."))

        # 1. Crear Superusuario
        self.stdout.write("Creando superusuario...")
        User.objects.create_superuser("admin", "admin@admin.com", "admin")
        self.stdout.write(self.style.SUCCESS("Superusuario creado: admin / admin"))

        # 2. Crear Dueños de Peluquerías y sus Peluquerías
        self.stdout.write(f"Creando {NUM_OWNERS} dueños y sus peluquerías...")
        hairdressers = []
        for i in range(NUM_OWNERS):
            full_name = fake.name()
            owner = User.objects.create_user(
                username=f"owner{i+1}",
                email=fake.email(),
                password="password123",
                first_name=full_name.split()[0],
                last_name=" ".join(full_name.split()[1:]),
                is_owner=True,
            )

            hairdresser = Hairdresser.objects.create(
                owner=owner,
                name=f"Salón de {owner.first_name}",
                address=fake.address(),
                phone_number=fake.phone_number(),
                description=fake.paragraph(nb_sentences=5),
                latitude=float(fake.latitude()),
                longitude=float(fake.longitude()),
            )
            hairdressers.append(hairdresser)
        self.stdout.write(
            self.style.SUCCESS(f"{NUM_OWNERS} dueños y peluquerías creados.")
        )

        # 3. Crear Servicios para cada Peluquería
        self.stdout.write("Asignando servicios a las peluquerías...")
        all_services = []
        for hairdresser in hairdressers:
            # Asigna una selección aleatoria de servicios a cada peluquería
            num_services_to_add = random.randint(3, len(SERVICES_LIST))
            services_to_add = random.sample(SERVICES_LIST, num_services_to_add)

            for name, price, duration in services_to_add:
                service = Service.objects.create(
                    hairdresser=hairdresser,
                    name=name,
                    price=price,
                    duration_minutes=duration,
                    description=fake.sentence(nb_words=10),
                )
                all_services.append(service)
        self.stdout.write(self.style.SUCCESS("Servicios creados y asignados."))

        # 4. Crear Clientes
        self.stdout.write(f"Creando {NUM_CLIENTS} clientes...")
        clients = []
        for i in range(NUM_CLIENTS):
            full_name = fake.name()
            first_name = full_name.split()[0]
            last_name = (
                " ".join(full_name.split()[1:]) if len(full_name.split()) > 1 else ""
            )
            client = User.objects.create_user(
                username=f"client{i+1}",
                email=fake.email(),
                password="password123",
                first_name=first_name,
                last_name=last_name,
            )
            clients.append(client)
        self.stdout.write(self.style.SUCCESS(f"{NUM_CLIENTS} clientes creados."))

        # 5. Crear Turnos
        self.stdout.write("Creando turnos pasados y futuros...")
        for client in clients:
            for _ in range(NUM_APPOINTMENTS_PER_CLIENT):
                # Elige un servicio al azar de todos los disponibles
                random_service = random.choice(all_services)

                # Genera una fecha y hora aleatoria (pasado o futuro)
                random_days = random.randint(
                    -30, 30
                )  # Desde hace 30 días hasta en 30 días
                random_hour = random.randint(9, 18)  # Horario de 9 a 18
                start_time = timezone.now() + timedelta(
                    days=random_days, hours=random_hour
                )
                start_time = start_time.replace(minute=0, second=0, microsecond=0)

                # Define el estado basado en si el turno es pasado o futuro
                if start_time < timezone.now():
                    status = "COMPLETED"
                else:
                    status = random.choice(["PENDING", "CONFIRMED"])

                appointment = Appointment.objects.create(
                    client=client,
                    service=random_service,
                    start_time=start_time,
                    end_time=start_time
                    + timedelta(minutes=random_service.duration_minutes),
                    status=status,
                )

                # 6. Crear Reseñas para turnos completados
                if appointment.status == "COMPLETED":
                    Review.objects.create(
                        appointment=appointment,
                        rating=random.randint(3, 5),  # Clientes mayormente satisfechos
                        comment=fake.paragraph(nb_sentences=2),
                    )

        self.stdout.write(self.style.SUCCESS("Turnos y reseñas creados."))
        self.stdout.write(self.style.SUCCESS("¡Proceso de seeding completado!"))
