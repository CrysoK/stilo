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