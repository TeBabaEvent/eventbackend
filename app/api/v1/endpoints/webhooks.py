"""Routes pour les webhooks de paiement"""
from fastapi import APIRouter, Request, HTTPException, BackgroundTasks, Depends
from sqlalchemy.orm import Session, joinedload
from datetime import datetime
import logging
import httpx

from app.db.database import get_db
from app.db import models
from app.services.mollie_client import mollie_client
from app.services.ticket_service import generate_tickets_for_order

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("/mollie")
async def mollie_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db)
):
    """
    Webhook Mollie - Reçoit les notifications de paiement.

    ⚠️ IMPORTANT - Format Mollie:
    - Content-Type: application/x-www-form-urlencoded
    - Body: id=tr_xxxxxxxx
    - PAS de JSON, PAS de statut dans le payload!

    Sécurité:
    - Mollie ne signe pas les webhooks
    - On DOIT toujours vérifier le statut via l'API
    - Un attaquant pourrait appeler cette URL avec n'importe quel ID

    Statuts Mollie:
    - open: Paiement créé, client n'a pas encore payé
    - pending: Paiement en cours de traitement
    - paid: Paiement réussi ✅
    - failed: Paiement échoué
    - canceled: Annulé par le client
    - expired: Expiré (timeout)

    Flow:
    1. Extraire l'ID du paiement
    2. Vérifier l'idempotence (déjà traité?)
    3. Enregistrer le webhook (status=processing)
    4. Appeler l'API Mollie pour le VRAI statut
    5. Trouver la commande
    6. Traiter selon le statut
    7. Marquer webhook comme processed

    Retries:
    - Mollie retry jusqu'à 10 fois si pas de 200 OK
    - Timeout après 15 secondes
    - Toujours retourner 200 même en cas d'erreur interne

    Returns:
        dict: {"status": "processed"} ou {"status": "already_processed"}
    """
    # ⚠️ CRITIQUE: Mollie envoie du form-urlencoded, pas du JSON!
    form_data = await request.form()
    mollie_payment_id = form_data.get("id")

    if not mollie_payment_id:
        logger.warning("Webhook Mollie reçu sans 'id'")
        # Retourner 200 quand même pour éviter les retries inutiles
        return {"status": "missing_id"}

    logger.info(f"📨 Webhook Mollie reçu: {mollie_payment_id}")

    # 1. CHECK IDEMPOTENCE - Déjà traité?
    existing = db.query(models.WebhookEvent).filter(
        models.WebhookEvent.provider_event_id == mollie_payment_id,
        models.WebhookEvent.provider == "mollie"
    ).first()

    if existing and existing.status == "processed":
        logger.info(f"Webhook {mollie_payment_id} déjà traité, ignoré")
        return {"status": "already_processed"}

    # 2. Enregistrer comme 'processing'
    webhook_event = models.WebhookEvent(
        provider="mollie",
        provider_event_id=mollie_payment_id,
        event_type="payment.notification",
        status="processing",
        raw_payload={"id": mollie_payment_id}
    )
    db.add(webhook_event)
    db.commit()
    db.refresh(webhook_event)

    try:
        # 3. ⚠️ OBLIGATOIRE: Récupérer le VRAI statut via l'API Mollie
        payment = mollie_client.get_payment(mollie_payment_id)

        status = payment["status"]
        is_paid = payment["is_paid"]
        is_failed = payment["is_failed"]
        is_canceled = payment["is_canceled"]
        is_expired = payment["is_expired"]
        metadata = payment.get("metadata", {})

        # Extraire l'order_number depuis metadata
        order_number = metadata.get("order_number") if metadata else None

        logger.info(f"✅ Statut Mollie vérifié: {status} pour commande {order_number}")

        # Mettre à jour le webhook avec le type d'événement
        webhook_event.event_type = f"payment.{status}"

        # 4. Trouver la commande
        order = None

        # D'abord par order_number dans metadata
        if order_number:
            order = db.query(models.Order).filter(
                models.Order.order_number == order_number
            ).first()

        # Fallback: par mollie_payment_id
        if not order:
            order = db.query(models.Order).filter(
                models.Order.mollie_payment_id == mollie_payment_id
            ).first()

        if not order:
            webhook_event.status = "failed"
            webhook_event.error_message = f"Order not found: {order_number}"
            db.commit()
            logger.error(f"❌ Commande non trouvée: {order_number}")
            # Retourner 200 pour éviter les retries
            return {"status": "order_not_found"}

        # 5. Traiter selon le statut Mollie
        if is_paid and order.status == "pending":
            # ✅ PAIEMENT RÉUSSI
            logger.info(f"💰 Paiement réussi pour {order.order_number}")

            order.status = "completed"
            order.paid_at = datetime.utcnow()
            
            # Incrémenter le compteur de ventes pour chaque pack
            if order.items:  # Nouvelle commande multi-pack
                for order_item in order.items:
                    event_pack = db.query(models.EventPack).filter(
                        models.EventPack.event_id == order_item.event_id,
                        models.EventPack.pack_id == order_item.pack_id
                    ).with_for_update().first()
                    if event_pack:
                        event_pack.sold_count = (event_pack.sold_count or 0) + order_item.quantity
                        logger.info(f"📊 Stock mis à jour: {event_pack.pack_id} sold_count={event_pack.sold_count}")
            elif order.pack_id and order.quantity:  # Ancienne commande single-pack
                event_pack = db.query(models.EventPack).filter(
                    models.EventPack.event_id == order.event_id,
                    models.EventPack.pack_id == order.pack_id
                ).with_for_update().first()
                if event_pack:
                    event_pack.sold_count = (event_pack.sold_count or 0) + order.quantity
                    logger.info(f"📊 Stock mis à jour: {event_pack.pack_id} sold_count={event_pack.sold_count}")
            
            db.commit()

            # Générer tickets + email en background
            background_tasks.add_task(
                process_successful_payment,
                order.id
            )

        elif is_failed or is_canceled or is_expired:
            # ❌ PAIEMENT ÉCHOUÉ
            if order.status == "pending":
                reason = "failed" if is_failed else ("canceled" if is_canceled else "expired")
                logger.info(f"❌ Paiement {reason} pour {order.order_number}")

                order.status = "failed"
                # Optionnel: stocker la raison dans un champ dédié
                # order.failure_reason = reason
                db.commit()

        else:
            # ⏳ STATUT INTERMÉDIAIRE (open, pending)
            logger.info(f"⏳ Statut intermédiaire '{status}' pour {order.order_number}")

        # 6. Marquer webhook comme traité
        webhook_event.status = "processed"
        webhook_event.processed_at = datetime.utcnow()
        db.commit()

        return {"status": "processed"}

    except Exception as e:
        webhook_event.status = "failed"
        webhook_event.error_message = str(e)
        db.commit()
        logger.exception(f"❌ Erreur traitement webhook Mollie: {e}")
        # Retourner 200 pour éviter les retries infinis
        return {"status": "error", "message": str(e)}


async def process_successful_payment(order_id: str):
    """
    Traitement post-paiement (background task).

    Exécuté en arrière-plan pour ne pas bloquer la réponse au webhook.

    Flow:
    1. Récupérer la commande
    2. Vérifier si les tickets n'ont pas déjà été générés
    3. Générer les tickets avec QR codes JWT
    4. Marquer tickets_generated = True
    5. Générer le PDF des tickets
    6. Envoyer l'email de confirmation

    Args:
        order_id: ID de la commande à traiter
    """
    from app.db.database import SessionLocal
    from app.services.pdf_service import generate_tickets_pdf, delete_pdf_file
    from app.services.email_service import send_confirmation_email

    db = SessionLocal()
    try:
        # Charger l'ordre avec toutes les relations nécessaires (eager loading)
        order = db.query(models.Order).options(
            joinedload(models.Order.event),
            joinedload(models.Order.pack),
            joinedload(models.Order.items).joinedload(models.OrderItem.pack)
        ).filter(models.Order.id == order_id).first()
        
        if not order:
            logger.error(f"Order {order_id} non trouvé pour traitement post-paiement")
            return
        
        # Vérifier si les tickets ont déjà été générés (idempotence)
        if order.tickets_generated:
            logger.info(f"Tickets déjà générés pour {order.order_number}, skip")
            return

        logger.info(f"Traitement post-paiement pour {order.order_number}")

        # 1. Générer les tickets
        tickets = await generate_tickets_for_order(order, db)
        logger.info(f"{len(tickets)} tickets générés pour commande {order.order_number}")
        
        # 2. Marquer la génération comme réussie
        order.tickets_generated = True
        db.commit()

        # 3. Générer le PDF
        try:
            pdf_path = await generate_tickets_pdf(tickets, order)
            logger.info(f"PDF généré: {pdf_path}")
        except Exception as e:
            logger.error(f"Erreur génération PDF: {e}")
            # Continuer même si le PDF échoue
            pdf_path = None

        # 4. Envoyer l'email de confirmation
        if pdf_path:
            email_sent = False
            try:
                await send_confirmation_email(
                    to_email=order.customer_email,
                    customer_name=order.customer_name,
                    order=order,
                    tickets=tickets,
                    pdf_path=pdf_path
                )
                logger.info(f"Email de confirmation envoyé à {order.customer_email}")
                email_sent = True
            except Exception as e:
                logger.error(f"Erreur envoi email: {e}")
                # Ne pas faire échouer le traitement si email échoue

            # 5. Nettoyer le PDF après envoi réussi
            if email_sent:
                delete_pdf_file(pdf_path)
        else:
            logger.warning(f"Pas de PDF - email non envoyé pour {order.order_number}")

        logger.info(f"Traitement post-paiement terminé pour {order.order_number}")

    except Exception as e:
        db.rollback()
        logger.exception(f"Erreur traitement post-paiement: {e}")
    finally:
        db.close()
