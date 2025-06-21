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