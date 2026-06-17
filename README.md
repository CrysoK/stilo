# Stilo

Plataforma web para conectar clientes con peluquerías, permitiendo la gestión de servicios y la reserva de turnos online de manera dinámica y moderna.

## 🚀 Características principales

- **Gestión de usuarios y roles**: Registro e inicio de sesión diferenciado para clientes y dueños de peluquerías.
- **Mapa interactivo**: Localización de peluquerías en tiempo real con geocodificación de direcciones utilizando Leaflet.
- **Reserva de turnos**: Interfaz interactiva para la selección de servicios, fechas y franjas horarias.
- **Notificaciones**:
  - **Notificaciones por correo (SMTP)** para recordatorios y confirmación de turnos.
  - **Notificaciones Web Push** en tiempo real (con Service Workers y claves VAPID) para mantener a los usuarios al tanto de sus reservas.
- **Panel de administración**: Gestión completa del catálogo de servicios, imágenes y turnos por parte de los dueños.

## 💻 Configuración y ejecución local

Este proyecto utiliza [uv](https://github.com/astral-sh/uv) como gestor de paquetes y entornos virtuales rápido para Python.

### Requisitos previos

- Python >= 3.12
- `uv` instalado en el sistema

### Pasos para levantar el proyecto localmente

1. **Clonar el repositorio**:

   ```bash
   git clone https://github.com/CrysoK/stilo.git
   cd stilo
   ```

2. **Instalar dependencias y crear el entorno virtual**:

   ```bash
   uv sync
   ```

   *(Esto crea automáticamente el entorno virtual en la carpeta `.venv` e instala todas las dependencias definidas en `pyproject.toml` y `uv.lock`)*

3. **Configurar el archivo `.env`**:
   Crear un archivo `.env` en la raíz del proyecto basándose en las variables requeridas:

   ```ini
   SECRET_KEY=tu_clave_secreta_django
   DEBUG=True
   ALLOWED_HOSTS=localhost,127.0.0.1
   DATABASE_URL=sqlite:///db.sqlite3

   # Configuración de Correo (SMTP)
   EMAIL_HOST=smtp.gmail.com
   EMAIL_PORT=587
   EMAIL_HOST_USER=tu_correo@gmail.com
   EMAIL_HOST_PASSWORD=tu_contraseña_de_aplicacion
   EMAIL_USE_TLS=True
   DEFAULT_FROM_EMAIL=Stilo <tu_correo@gmail.com>

   # Web Push VAPID Keys
   VAPID_PUBLIC_KEY=tu_clave_publica_vapid
   VAPID_PRIVATE_KEY=tu_clave_privada_vapid
   ```

4. **Ejecutar migraciones y cargar base de datos**:

   ```bash
   uv run manage.py migrate
   ```

5. **Iniciar el servidor de desarrollo**:

   ```bash
   uv run manage.py runserver
   ```

   Acceder a `http://127.0.0.1:8000` en el navegador.

## 🌐 Guía de despliegue en PythonAnywhere

A continuación se detallan los pasos necesarios para desplegar y actualizar los últimos cambios del proyecto en el servidor de producción de **PythonAnywhere** (`<usuario>.pythonanywhere.com`).

### Configuración en la pestaña "Web" de PythonAnywhere

Dado que `uv` crea el entorno virtual dentro de la raíz del proyecto (`/home/<usuario>/stilo/.venv`), la ruta de **Virtualenv** en la pestaña **Web** debe estar configurada a:
`/home/<usuario>/stilo/.venv`

### Actualizar cambios desde la consola Bash

1. **Ingresar al directorio y descargar el último código**:

   ```bash
   cd ~/stilo
   git pull
   ```

2. **Configurar las variables de entorno en producción**:
   El archivo `.env` en la carpeta del proyecto debe contener las claves de correo y VAPID correspondientes:

   ```ini
   EMAIL_HOST=smtp.gmail.com
   EMAIL_PORT=587
   EMAIL_HOST_USER=tu_correo@gmail.com
   EMAIL_HOST_PASSWORD=tu_contraseña_de_aplicacion
   EMAIL_USE_TLS=True
   DEFAULT_FROM_EMAIL=Stilo <tu_correo@gmail.com>

   VAPID_PUBLIC_KEY=tu_clave_publica_vapid
   VAPID_PRIVATE_KEY=tu_clave_privada_vapid
   ```

3. **Sincronizar las dependencias con `uv`**:

   ```bash
   uv sync
   ```

   *(Esto creará o actualizará automáticamente el entorno virtual `.venv` con las dependencias exactas definidas en `uv.lock` y `pyproject.toml`)*

4. **Aplicar migraciones de la base de datos y recolectar archivos estáticos**:

   ```bash
   uv run manage.py migrate
   uv run manage.py collectstatic --noinput
   ```

5. **Reiniciar la aplicación web**:
   Ve a la pestaña **Web** del panel de control de PythonAnywhere y haz clic en el botón verde **Reload** para aplicar los cambios en el servidor web.
