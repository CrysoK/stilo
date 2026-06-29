import hashlib
import hmac
import json
import requests
from django.conf import settings as app_settings
from django.http import HttpResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
from core.models import Hairdresser, Appointment, WebhookEvent, PaymentTransaction
from decimal import Decimal
import logging

logger = logging.getLogger('mp')


def _verify_mp_signature(request):
    """
    Verifica la firma x-signature del webhook de MercadoPago.
    MercadoPago puede enviar los webhooks con diferentes formatos de parámetros:
    - Formato 1: ?data.id=ID&type=payment
    - Formato 2: ?id=ID&topic=payment
    """
    webhook_secret = getattr(app_settings, "MERCADOPAGO_WEBHOOK_SECRET", None)
    if not webhook_secret:
        if app_settings.DEBUG:
            logger.warning(
                "MERCADOPAGO_WEBHOOK_SECRET no está configurado. Omitiendo validación de firma en modo DEBUG."
            )
            return True
        else:
            logger.error(
                "MERCADOPAGO_WEBHOOK_SECRET no está configurado en producción. Validación de firma fallida."
            )
            return False

    x_signature = request.headers.get("x-signature", "")
    x_request_id = request.headers.get("x-request-id", "")

    if not x_signature:
        logger.warning("Webhook recibido sin header x-signature.")
        return False

    # Parsear ts y v1 del header x-signature: ts=XXX,v1=YYY
    ts = None
    v1 = None
    for part in x_signature.split(","):
        part = part.strip()
        if part.startswith("ts="):
            ts = part[3:]
        elif part.startswith("v1="):
            v1 = part[3:]

    if not ts or not v1:
        logger.warning("Header x-signature malformado.")
        return False

    # MercadoPago envía el ID de dos formas: 'data.id' o 'id'
    data_id = request.GET.get("data.id") or request.GET.get("id", "")

    if not data_id:
        logger.warning(f"Webhook recibido sin data.id o id. Query: {dict(request.GET)}")
        return False

    # Convertir data.id a minúsculas si contiene caracteres alfanuméricos
    data_id = str(data_id).lower()

    # Construir el manifest: id:[data.id];request-id:[x-request-id];ts:[ts];
    manifest = f"id:{data_id};request-id:{x_request_id};ts:{ts};"

    # Calcular HMAC-SHA256
    expected = hmac.new(
        webhook_secret.encode("utf-8"),
        manifest.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()

    # Comparar firmas de forma segura
    if not hmac.compare_digest(expected, v1):
        logger.warning(
            f"Firma de webhook inválida. data_id={data_id}, manifest={manifest!r}"
        )
        logger.debug(f"Expected: {expected}, Got: {v1}")
        return False

    logger.info(f"✓ Webhook signature válida para data.id={data_id}")
    return True


@csrf_exempt
@require_POST
def mercadopago_webhook(request, hairdresser_id):
    # 1. Validar firma antes de hacer cualquier otra cosa
    if not _verify_mp_signature(request):
        return HttpResponse("Firma inválida", status=400)

    try:
        hairdresser = Hairdresser.objects.get(pk=hairdresser_id)
    except Hairdresser.DoesNotExist:
        logger.error(f"Webhook error: Hairdresser with id {hairdresser_id} not found.")
        return HttpResponse("Hairdresser not found", status=404)

    # En sandbox, usar el token de prueba del panel (misma lógica que la creación de preferencias)
    if app_settings.MERCADOPAGO_SANDBOX and app_settings.MERCADOPAGO_TEST_ACCESS_TOKEN:
        access_token = app_settings.MERCADOPAGO_TEST_ACCESS_TOKEN
    else:
        access_token = hairdresser.mercadopago_access_token
    if not access_token:
        logger.error(
            f"Webhook error: MercadoPago not active/configured for hairdresser {hairdresser_id}."
        )
        return HttpResponse(
            "MercadoPago not configured for this hairdresser", status=400
        )

    payment_id = None

    # Comprobar si hay 'topic' e 'id' en los parámetros GET (estilo IPN)
    topic = request.GET.get("topic") or request.GET.get("type")
    if topic == "payment":
        payment_id = request.GET.get("id") or request.GET.get("data.id")

    # Comprobar si la notificación es un POST JSON de webhook
    if not payment_id:
        try:
            body = json.loads(request.body)
            action = body.get("action")
            body_type = body.get("type")

            if (
                body_type == "payment"
                or action == "payment.created"
                or action == "payment.updated"
            ):
                payment_id = body.get("data", {}).get("id")
            elif "id" in body and body.get("topic") == "payment":
                payment_id = body.get("id")
        except json.JSONDecodeError:
            pass

    if not payment_id:
        logger.info("Webhook warning: No payment ID found in notification. Ignored.")
        return HttpResponse("Notification ignored (no payment id)", status=200)

    # Control de Idempotencia por Base de Datos (Rápido)
    from django.db import transaction
    payment_id_str = str(payment_id)
    try:
        with transaction.atomic():
            event, created = WebhookEvent.objects.select_for_update().get_or_create(
                payment_id=payment_id_str,
                defaults={"mp_request_id": request.headers.get("x-request-id")}
            )
            if not created and event.processed:
                logger.info(
                    f"Webhook idempotencia: pago {payment_id_str} ya fue procesado con éxito."
                )
                return HttpResponse("OK", status=200)
    except Exception as db_err:
        logger.error(
            f"Error de base de datos al verificar idempotencia para pago {payment_id_str}: {str(db_err)}"
        )
        return HttpResponse("Database Error", status=500)

    # Consultar los detalles del pago en MercadoPago
    url = f"https://api.mercadopago.com/v1/payments/{payment_id_str}"
    headers = {"Authorization": f"Bearer {access_token}"}

    try:
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()
        payment_data = response.json()
    except Exception as e:
        logger.error(
            f"Webhook error: Failed to fetch payment {payment_id} details: {str(e)}"
        )
        return HttpResponse(f"Error fetching payment details: {str(e)}", status=500)

    status = payment_data.get("status")
    external_reference = payment_data.get("external_reference")
    transaction_amount = payment_data.get("transaction_amount")

    if not external_reference:
        logger.warning(
            f"Webhook warning: Payment {payment_id} does not contain an external_reference."
        )
        return HttpResponse("No external reference found in payment", status=200)

    try:
        appointment = Appointment.objects.get(pk=external_reference)
    except Appointment.DoesNotExist:
        logger.error(
            f"Webhook error: Appointment with id {external_reference} not found."
        )
        return HttpResponse(
            "Appointment not found", status=200
        )  # Retornar 200 para que MercadoPago no reintente

    # Registrar la transacción de pago para auditoría (inmutable)
    try:
        PaymentTransaction.objects.update_or_create(
            payment_id=payment_id_str,
            defaults={
                "appointment": appointment,
                "amount": Decimal(str(transaction_amount)),
                "status": status,
            }
        )
    except Exception as trans_err:
        logger.error(
            f"Error al registrar PaymentTransaction en webhook para pago {payment_id_str}: {str(trans_err)}"
        )

    if status == "approved":
        from django.db import transaction

        try:
            with transaction.atomic():
                # Bloquear WebhookEvent para evitar concurrencia
                event = WebhookEvent.objects.select_for_update().get(payment_id=payment_id_str)
                if event.processed:
                    logger.info(
                        f"Webhook idempotencia (concurrente): pago {payment_id_str} ya fue procesado."
                    )
                    return HttpResponse("OK", status=200)

                # Bloquear fila del turno para evitar concurrencia
                appointment_locked = Appointment.objects.select_for_update().get(
                    pk=appointment.id
                )

                if appointment_locked.status != "CONFIRMED":
                    # Verificar si ya existe otro turno CONFIRMADO que se superpone con este
                    has_overlap = (
                        Appointment.objects.filter(
                            service__hairdresser=appointment_locked.service.hairdresser,
                            status="CONFIRMED",
                            start_time__lt=appointment_locked.end_time,
                            end_time__gt=appointment_locked.start_time,
                        )
                        .exclude(pk=appointment_locked.id)
                        .exists()
                    )

                    if has_overlap:
                        # El turno ya fue ocupado: cancelar y reembolsar automáticamente
                        appointment_locked.status = "CANCELLED"
                        appointment_locked.amount_paid = Decimal(
                            str(transaction_amount)
                        )
                        appointment_locked.mercadopago_payment_id = str(payment_id_str)
                        appointment_locked.expires_at = None
                        appointment_locked.save()

                        # Reembolsar en MercadoPago
                        try:
                            refund_url = f"https://api.mercadopago.com/v1/payments/{payment_id_str}/refunds"
                            refund_resp = requests.post(
                                refund_url, headers=headers, json={}, timeout=10
                            )
                            refund_resp.raise_for_status()
                            logger.warning(
                                f"Sobreventa detectada: Turno {appointment_locked.id} reembolsado automáticamente. Pago ID: {payment_id_str}"
                            )
                        except Exception as refund_err:
                            logger.error(
                                f"Error reembolsando pago {payment_id_str} para turno {appointment_locked.id}: {str(refund_err)}"
                            )
                            # Registrar reembolso pendiente para reintento automático
                            from core.models import PendingRefund
                            PendingRefund.objects.get_or_create(
                                appointment=appointment_locked,
                                defaults={
                                    'payment_id': payment_id_str,
                                    'amount': Decimal(str(transaction_amount)),
                                    'last_error': str(refund_err)
                                }
                            )

                        # Enviar notificación especial al cliente
                        from core.utils import notify_user

                        notify_user(
                            user=appointment_locked.client,
                            event_type="APPOINTMENT_CANCELLED_CLIENT",
                            context={
                                "appointment": appointment_locked,
                                "overbooked_refund": True,
                            },
                            subject="Reembolso de Turno - Stilo",
                            push_title="Turno cancelado y reembolsado",
                            push_message=f"Tu turno en {appointment_locked.service.hairdresser.name} no estaba disponible y fue reembolsado automáticamente.",
                        )
                    else:
                        # Verificar que el monto pagado sea suficiente
                        expected_amount = appointment_locked.get_expected_payment_amount()
                        paid_amount = Decimal(str(transaction_amount))

                        if paid_amount < expected_amount:
                            # Pago insuficiente: cancelar y reembolsar automáticamente
                            appointment_locked.status = "CANCELLED"
                            appointment_locked.amount_paid = paid_amount
                            appointment_locked.mercadopago_payment_id = str(payment_id_str)
                            appointment_locked.expires_at = None
                            appointment_locked.save()

                            # Reembolsar en MercadoPago
                            try:
                                refund_url = f"https://api.mercadopago.com/v1/payments/{payment_id_str}/refunds"
                                refund_resp = requests.post(
                                    refund_url, headers=headers, json={}, timeout=10
                                )
                                refund_resp.raise_for_status()
                                logger.warning(
                                    f"Pago insuficiente detectado: Turno {appointment_locked.id} reembolsado automáticamente. Pago ID: {payment_id_str}. Esperado: {expected_amount}, Pagado: {paid_amount}"
                                )
                            except Exception as refund_err:
                                logger.error(
                                    f"Error reembolsando pago insuficiente {payment_id_str} para turno {appointment_locked.id}: {str(refund_err)}"
                                )
                                # Registrar reembolso pendiente para reintento automático
                                from core.models import PendingRefund
                                PendingRefund.objects.get_or_create(
                                    appointment=appointment_locked,
                                    defaults={
                                        'payment_id': payment_id_str,
                                        'amount': paid_amount,
                                        'last_error': str(refund_err)
                                    }
                                )

                            # Enviar notificación especial al cliente
                            from core.utils import notify_user

                            notify_user(
                                user=appointment_locked.client,
                                event_type="APPOINTMENT_CANCELLED_CLIENT",
                                context={
                                    "appointment": appointment_locked,
                                    "underpaid_refund": True,
                                },
                                subject="Reembolso de Turno - Stilo",
                                push_title="Turno cancelado por pago insuficiente",
                                push_message=f"Tu turno en {appointment_locked.service.hairdresser.name} fue cancelado y reembolsado porque el pago fue menor al requerido.",
                            )
                        else:
                            # Confirmar
                            appointment_locked.status = "CONFIRMED"
                            appointment_locked.amount_paid = paid_amount
                            appointment_locked.mercadopago_payment_id = str(payment_id_str)
                            appointment_locked.expires_at = None
                            appointment_locked.save()
                            logger.info(
                                f"Webhook success: Appointment {appointment_locked.id} paid and CONFIRMED. Paid amount: {paid_amount}"
                            )
                
                # Marcar evento como procesado
                event.processed = True
                event.save()
        except Exception as e:
            logger.error(f"Error procesando confirmación atómica en webhook: {str(e)}")
            return HttpResponse("Error processing confirmation", status=500)

    return HttpResponse("OK", status=200)
