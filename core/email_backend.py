import logging
import email.utils
import requests
from django.conf import settings
from django.core.mail.backends.base import BaseEmailBackend

logger = logging.getLogger("core")


class BrevoEmailBackend(BaseEmailBackend):
    """
    Backend de correo personalizado para enviar correos transaccionales a través de la API HTTP de Brevo.
    Evita bloqueos de puertos SMTP (587/465) en entornos como la versión gratuita de PythonAnywhere.
    """

    def __init__(self, fail_silently=False, **kwargs):
        super().__init__(fail_silently=fail_silently, **kwargs)
        self.api_key = getattr(settings, "BREVO_API_KEY", "")
        self.api_url = "https://api.brevo.com/v3/smtp/email"

    def send_messages(self, email_messages):
        """
        Envía una lista de mensajes a través de la API de Brevo.
        Retorna la cantidad de mensajes enviados con éxito.
        """
        if not email_messages:
            return 0

        if not self.api_key:
            logger.error("Brevo API Key no configurada. Establece BREVO_API_KEY en settings.")
            if not self.fail_silently:
                raise ValueError("Brevo API Key no configurada.")
            return 0

        headers = {
            "accept": "application/json",
            "api-key": self.api_key,
            "content-type": "application/json",
        }

        sent_counter = 0

        for message in email_messages:
            try:
                # Parsear remitente
                sender_name, sender_email = email.utils.parseaddr(message.from_email)
                sender = {"email": sender_email}
                if sender_name:
                    sender["name"] = sender_name

                # Parsear destinatarios
                to_list = []
                for recipient in message.to:
                    name, addr = email.utils.parseaddr(recipient)
                    to_list.append({"email": addr, "name": name if name else addr})

                if not to_list:
                    logger.warning("Mensaje de correo omitido: Lista de destinatarios ('to') vacía.")
                    continue

                # Construir el payload JSON
                payload = {
                    "sender": sender,
                    "to": to_list,
                    "subject": message.subject,
                }

                # Cuerpos de mensaje (Texto y HTML)
                html_content = None
                text_content = message.body

                # Buscar contenido alternativo en HTML
                if hasattr(message, "alternatives"):
                    for alt in message.alternatives:
                        if alt[1] == "text/html":
                            html_content = alt[0]
                            break

                if html_content:
                    payload["htmlContent"] = html_content
                if text_content:
                    payload["textContent"] = text_content

                # Enviar petición POST a Brevo
                response = requests.post(self.api_url, headers=headers, json=payload, timeout=10)

                if response.status_code in [200, 201, 202]:
                    sent_counter += 1
                else:
                    logger.error(
                        f"Error de la API de Brevo ({response.status_code}): {response.text}"
                    )
                    if not self.fail_silently:
                        response.raise_for_status()

            except Exception as e:
                logger.error(f"Fallo al enviar correo a través de Brevo: {e}")
                if not self.fail_silently:
                    raise

        return sent_counter
