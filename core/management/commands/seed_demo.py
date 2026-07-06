import datetime
import random
from django.core.management.base import BaseCommand
from django.utils import timezone
from django.db import transaction
from core.models import User, Hairdresser, Service, Appointment, Review, WorkingHours

class Command(BaseCommand):
    help = "Genera datos específicos y abundantes para la demo del examen final (8 de Julio de 2026)"

    @transaction.atomic
    def handle(self, *args, **kwargs):
        self.stdout.write("Limpiando base de datos...")
        Appointment.objects.all().delete()
        Review.objects.all().delete()
        WorkingHours.objects.all().delete()
        Service.objects.all().delete()
        Hairdresser.objects.all().delete()
        User.objects.exclude(is_superuser=True).delete()

        # Fijar semilla aleatoria para que los datos generados sean siempre los mismos y predecibles en la demo
        random.seed(2026)

        # 1. Superusuario
        if not User.objects.filter(username="admin").exists():
            User.objects.create_superuser("admin", "admin@stilo.com", "admin")

        # 2. Clientes (Creamos 10 para llenar el Top 5 Clientes de las estadísticas)
        self.stdout.write("Creando clientes...")
        nombres = ["Juan", "María", "Lucas", "Sofía", "Martín", "Ana", "Diego", "Laura", "Carlos", "Valentina"]
        apellidos = ["Pérez", "Gómez", "Díaz", "López", "García", "Fernández", "Martínez", "Rodríguez", "Sánchez", "Romero"]
        
        clients = []
        for i in range(10):
            c = User.objects.create_user(
                username=f"cliente{i+1}", 
                password=f"cliente{i+1}", 
                first_name=nombres[i], 
                last_name=apellidos[i], 
                email=f"cliente{i+1}@email.com"
            )
            clients.append(c)

        # Referencias para los turnos de la demo en vivo
        c1, c2, c3 = clients[0], clients[1], clients[2]

        # 3. Dueños y Peluquerías
        self.stdout.write("Creando dueños y peluquerías...")
        shops_data = [
            {
                "owner": "dueño1", "name": "Barbería Castañares", "address": "Av. Fuerza Aérea 150, Barrio Castañares",
                "lat": -24.729110, "lon": -65.407519, "req_dep": True, "dep_val": 50.00, "allow_pre": True, "allow_site": True,
                "services": [("Corte Clásico", 6000, 30), ("Corte + Barba", 8000, 45), ("Perfilado de Cejas", 3000, 15)]
            },
            {
                "owner": "dueño2", "name": "Milagro Beauty Salón", "address": "Av. Batalla de Salta 450, Ciudad del Milagro",
                "lat": -24.716123, "lon": -65.407221, "req_dep": True, "dep_val": 100.00, "allow_pre": True, "allow_site": True,
                "services": [("Corte Femenino", 10000, 60), ("Tintura Completa", 25000, 120), ("Alisado Keratina", 30000, 150)]
            },
            {
                "owner": "dueño3", "name": "Tres Cerritos Studio", "address": "Las Araucarias 120, Tres Cerritos",
                "lat": -24.752312, "lon": -65.398210, "req_dep": False, "dep_val": 0, "allow_pre": True, "allow_site": False,
                "services": [("Corte Express Demo", 50, 15), ("Nutrición Capilar", 12000, 45), ("Mechas y Reflejos", 35000, 180)]
            },
            {
                "owner": "dueño4", "name": "Huaico Hair & Style", "address": "Av. Democracia 300, El Huaico",
                "lat": -24.721520, "lon": -65.418112, "req_dep": False, "dep_val": 0, "allow_pre": False, "allow_site": True,
                "services": [("Corte y Peinado", 7000, 45), ("Claritos", 18000, 90)]
            }
        ]

        hairdressers = {}
        for data in shops_data:
            owner = User.objects.create_user(
                username=data["owner"], password=data["owner"], 
                first_name=data["name"].split()[0], last_name="Owner", email=f"{data['owner']}@stilo.com", is_owner=True
            )
            h = Hairdresser.objects.create(
                owner=owner, name=data["name"], address=data["address"],
                latitude=data["lat"], longitude=data["lon"],
                mercadopago_active=False,  # DEBEN VINCULAR SUS CUENTAS MANUALMENTE
                requires_deposit=data["req_dep"], default_deposit_type="FIXED", default_deposit_value=data["dep_val"],
                default_allow_prepayment=data["allow_pre"], default_allow_on_site_payment=data["allow_site"],
                slot_duration=15
            )
            hairdressers[data["owner"]] = h

            # Horarios: Lunes a Sábado, de 09:00 a 20:00
            for day in range(6):
                WorkingHours.objects.create(hairdresser=h, day_of_week=day, start_time=datetime.time(9, 0), end_time=datetime.time(20, 0))

            # Servicios
            for s_name, s_price, s_dur in data["services"]:
                Service.objects.create(hairdresser=h, name=s_name, price=s_price, duration_minutes=s_dur)

        local_tz = timezone.get_current_timezone()
        def make_dt(month, day, hour, minute):
            return timezone.make_aware(datetime.datetime(2026, month, day, hour, minute), local_tz)

        self.stdout.write("Generando volumen de datos históricos para los gráficos...")
        
        # --- GENERACIÓN DE DATOS MASIVOS (Estadísticas) ---
        for owner_key, h_obj in hairdressers.items():
            h_services = list(h_obj.services.all())
            
            # 1. Histórico: Enero a Junio (Para el gráfico de líneas de evolución)
            # Aumentamos gradualmente la cantidad de turnos mes a mes para mostrar tendencia positiva
            for month in range(1, 7):
                num_apps = 15 + (month * 5)  # Enero: 20, Junio: 45
                for _ in range(num_apps):
                    day = random.randint(1, 28)
                    hour = random.randint(9, 19)
                    minute = random.choice([0, 15, 30, 45])
                    srv = random.choice(h_services)
                    cli = random.choice(clients)
                    dt = make_dt(month, day, hour, minute)
                    
                    Appointment.objects.create(
                        client=cli, service=srv, start_time=dt, status="COMPLETED",
                        amount=srv.price, payment_method="CASH", amount_paid=0
                    )

            # 2. Mes Actual: 1 al 7 de Julio (Para gráficos de torta, barras y top clientes)
            for day in range(1, 8):
                # Entre 4 y 8 turnos por día
                num_apps = random.randint(4, 8)
                for _ in range(num_apps):
                    hour = random.randint(9, 19)
                    minute = random.choice([0, 15, 30, 45])
                    srv = random.choice(h_services)
                    cli = random.choice(clients)
                    dt = make_dt(7, day, hour, minute)
                    
                    # Distribuir estados para darle realismo a la "Tasa de Ausentismo"
                    roll = random.random()
                    if roll < 0.75:
                        status = "COMPLETED"
                    elif roll < 0.85:
                        status = "NO_SHOW"
                    else:
                        status = "CANCELLED"

                    app = Appointment.objects.create(
                        client=cli, service=srv, start_time=dt, status=status,
                        amount=srv.price, payment_method="CASH", amount_paid=0
                    )
                    
                    # Generar reseñas solo para algunos completados
                    if status == "COMPLETED" and random.random() > 0.5:
                        Review.objects.create(
                            appointment=app, 
                            rating=random.choice([4, 5, 5]), # Mayores chances de 5
                            comment=random.choice([
                                "Excelente atención.", "Me encantó el resultado.", 
                                "Muy profesionales, lo recomiendo.", "El lugar es muy lindo.", "Todo perfecto."
                            ])
                        )


        self.stdout.write("Generando turnos específicos para la demostración en vivo...")
        
        # --- TURNOS ESPECÍFICOS PARA LA DEMO EN VIVO ---
        
        # Día de la Demo (8 de Julio 2026)
        Appointment.objects.create(
            client=c1, service=hairdressers["dueño1"].services.first(),
            start_time=make_dt(7, 8, 17, 0), status="CONFIRMED", amount=6000, payment_method="CASH", amount_paid=50
        )
        Appointment.objects.create(
            client=c2, service=hairdressers["dueño1"].services.get(name="Corte + Barba"),
            start_time=make_dt(7, 8, 18, 15), status="CONFIRMED", amount=8000, payment_method="FULL", amount_paid=8000
        )
        
        # Futuros pendientes (9 de Julio 2026)
        Appointment.objects.create(
            client=c3, service=hairdressers["dueño4"].services.first(),
            start_time=make_dt(7, 9, 10, 0), status="PENDING", amount=7000, payment_method="CASH", amount_paid=0
        )

        self.stdout.write(self.style.SUCCESS("Base de datos de demostración generada con éxito."))
