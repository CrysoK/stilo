from django.conf import settings

def vapid_keys(request):
    """
    Exposar la clave pública VAPID globalmente para las plantillas.
    """
    return {
        'VAPID_PUBLIC_KEY': getattr(settings, 'VAPID_PUBLIC_KEY', '')
    }
