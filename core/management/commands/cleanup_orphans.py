import os
from django.core.management.base import BaseCommand
from django.conf import settings
from core.models import HairdresserImage

class Command(BaseCommand):
    help = "Busca y elimina imágenes huérfanas en el servidor que ya no existen en la base de datos."

    def add_arguments(self, parser):
        # Permite hacer una simulación segura sin borrar nada
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Muestra qué archivos se eliminarían sin borrarlos físicamente.',
        )

    def handle(self, *args, **options):
        dry_run = options['dry_run']
        
        # 1. Obtener todas las rutas de imágenes registradas en la base de datos
        # image.name almacena la ruta relativa desde MEDIA_ROOT (ej: 'hairdressers/foto.jpg')
        db_images = set(
            HairdresserImage.objects.exclude(image="").values_list('image', flat=True)
        )

        # 2. Ruta física del directorio de imágenes de peluquerías
        hairdressers_dir = os.path.join(settings.MEDIA_ROOT, 'hairdressers')

        if not os.path.exists(hairdressers_dir):
            self.stdout.write(self.style.WARNING(f"El directorio {hairdressers_dir} no existe."))
            return

        self.stdout.write("Analizando archivos en el servidor...")
        orphans = []

        # 3. Recorrer los archivos físicos del directorio
        for filename in os.listdir(hairdressers_dir):
            # Reconstruir la ruta relativa tal como se guardaría en el campo ImageField
            relative_path = os.path.join('hairdressers', filename).replace('\\', '/')
            
            if relative_path not in db_images:
                orphans.append(os.path.join(hairdressers_dir, filename))

        if not orphans:
            self.stdout.write(self.style.SUCCESS("¡Todo limpio! No se encontraron imágenes huérfanas."))
            return

        self.stdout.write(self.style.WARNING(f"Se encontraron {len(orphans)} archivos huérfanos.\n"))

        # 4. Eliminar o simular la eliminación
        for filepath in orphans:
            filename = os.path.basename(filepath)
            if dry_run:
                self.stdout.write(f"[DRY-RUN] Se eliminaría: {filename}")
            else:
                try:
                    os.remove(filepath)
                    self.stdout.write(self.style.SUCCESS(f"Eliminado: {filename}"))
                except Exception as e:
                    self.stdout.write(self.style.ERROR(f"Error al eliminar {filename}: {e}"))

        if dry_run:
            self.stdout.write(self.style.WARNING("\nModo simulación activo. No se borró ningún archivo físico. Ejecuta sin '--dry-run' para confirmar."))
        else:
            self.stdout.write(self.style.SUCCESS(f"\nSe eliminaron correctamente {len(orphans)} archivos huérfanos."))
