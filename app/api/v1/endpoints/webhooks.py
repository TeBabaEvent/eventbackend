"""Routes pour les webhooks de paiement"""
from fastapi import APIRouter, Request, HTTPException, BackgroundTasks, Depends
from sqlalchemy.orm import Session, joinedload
from datetime import datetime
import logging
import httpx

from app.db.database import get_db
from app.db import models
from app.services.ticket_service import generate_tickets_for_order

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("/paypal")
async def paypal_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db)
):
    """
    Webhook PayPal - Reçoit les notifications de paiement.

    ⚠️ IMPORTANT - Format PayPal:
    - Content-Type: application/json
    - Body: JSON avec event_type et resource

    Sécurité:
    - PayPal signe les webhooks (headers PAYPAL-TRANSMISSION-SIG, etc.)
    - Vérifier la signature avant traitement

    Events:
    - PAYMENT.CAPTURE.COMPLETED: Paiement capturé ✅
    - PAYMENT.CAPTURE.DENIED: Paiement refusé ❌
    - CHECKOUT.ORDER.APPROVED: Commande approuvée (nécessite capture)

    Returns:
        dict: {"status": "processed"} ou {"status": "error"}
    """
    from app.services.paypal_client import paypal_client
    
    # Récupérer le JSON
    try:
        body = await request.json()
    except Exception:
        logger.warning("Webhook PayPal reçu avec body invalide")
        return {"status": "invalid_body"}
    
    event_type = body.get("event_type")
    resource = body.get("resource", {})
    
    logger.info(f"📨 Webhook PayPal reçu: {event_type}")
    
    # Récupérer l'order_number depuis custom_id ou reference_id
    order_number = None
    purchase_units = resource.get("purchase_units", [])
    if purchase_units:
        order_number = purchase_units[0].get("reference_id") or purchase_units[0].get("custom_id")
    
    # Fallback: chercher dans supplementary_data
    if not order_number:
        supplementary = resource.get("supplementary_data", {})
        related = supplementary.get("related_ids", {})
        order_number = related.get("order_id")
    
    if not order_number:
        logger.warning(f"Webhook PayPal sans order_number identifiable")
        return {"status": "missing_order_number"}
    
    # Trouver la commande
    order = db.query(models.Order).filter(
        models.Order.order_number == order_number
    ).first()
    
    if not order:
        # Fallback par paypal_order_id
        paypal_order_id = resource.get("id")
        if paypal_order_id:
            order = db.query(models.Order).filter(
                models.Order.paypal_order_id == paypal_order_id
            ).first()
    
    if not order:
        logger.error(f"❌ Commande non trouvée: {order_number}")
        return {"status": "order_not_found"}
    
    # Idempotence check
    existing = db.query(models.WebhookEvent).filter(
        models.WebhookEvent.provider_event_id == body.get("id"),
        models.WebhookEvent.provider == "paypal"
    ).first()
    
    if existing and existing.status == "processed":
        logger.info(f"Webhook {body.get('id')} déjà traité, ignoré")
        return {"status": "already_processed"}
    
    # Enregistrer le webhook
    webhook_event = models.WebhookEvent(
        provider="paypal",
        provider_event_id=body.get("id"),
        event_type=event_type,
        status="processing",
        raw_payload=body
    )
    db.add(webhook_event)
    db.commit()
    
    try:
        # Traiter selon le type d'événement
        if event_type == "CHECKOUT.ORDER.APPROVED":
            # L'ordre a été approuvé, il faut le capturer
            logger.info(f"📝 Commande approuvée, capture en cours: {order.order_number}")
            
            paypal_order_id = resource.get("id")
            capture_result = paypal_client.capture_order(paypal_order_id)
            
            if capture_result.get("status") == "COMPLETED":
                # Paiement réussi !
                order.status = "completed"
                order.paid_at = datetime.utcnow()
                
                # Mettre à jour les compteurs
                if order.items:
                    for order_item in order.items:
                        event_pack = db.query(models.EventPack).filter(
                            models.EventPack.event_id == order_item.event_id,
                            models.EventPack.pack_id == order_item.pack_id
                        ).with_for_update().first()
                        if event_pack:
                            event_pack.sold_count = (event_pack.sold_count or 0) + order_item.quantity
                elif order.pack_id and order.quantity:
                    event_pack = db.query(models.EventPack).filter(
                        models.EventPack.event_id == order.event_id,
                        models.EventPack.pack_id == order.pack_id
                    ).with_for_update().first()
                    if event_pack:
                        event_pack.sold_count = (event_pack.sold_count or 0) + order.quantity
                
                db.commit()
                
                # Générer tickets en background
                background_tasks.add_task(process_successful_payment, order.id)
                
        elif event_type == "PAYMENT.CAPTURE.COMPLETED":
            # Capture complétée (peut arriver après CHECKOUT.ORDER.APPROVED)
            if order.status == "pending":
                order.status = "completed"
                order.paid_at = datetime.utcnow()
                
                # Mettre à jour les compteurs
                if order.items:
                    for order_item in order.items:
                        event_pack = db.query(models.EventPack).filter(
                            models.EventPack.event_id == order_item.event_id,
                            models.EventPack.pack_id == order_item.pack_id
                        ).with_for_update().first()
                        if event_pack:
                            event_pack.sold_count = (event_pack.sold_count or 0) + order_item.quantity
                elif order.pack_id and order.quantity:
                    event_pack = db.query(models.EventPack).filter(
                        models.EventPack.event_id == order.event_id,
                        models.EventPack.pack_id == order.pack_id
                    ).with_for_update().first()
                    if event_pack:
                        event_pack.sold_count = (event_pack.sold_count or 0) + order.quantity
                
                db.commit()
                background_tasks.add_task(process_successful_payment, order.id)
                
        elif event_type in ["PAYMENT.CAPTURE.DENIED", "PAYMENT.CAPTURE.DECLINED"]:
            # Paiement échoué
            if order.status == "pending":
                order.status = "failed"
                db.commit()
        
        # Marquer webhook comme traité
        webhook_event.status = "processed"
        webhook_event.processed_at = datetime.utcnow()
        db.commit()
        
        return {"status": "processed"}
        
    except Exception as e:
        webhook_event.status = "failed"
        webhook_event.error_message = str(e)
        db.commit()
        logger.exception(f"❌ Erreur traitement webhook PayPal: {e}")
        return {"status": "error", "message": str(e)}


@router.post("/mollie")
async def mollie_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db)
):
    """
    Webhook Mollie - LEGACY - Conservé pour les anciennes commandes.

    ⚠️ DEPRECATED: Utiliser PayPal pour les nouvelles commandes.

    ⚠️ IMPORTANT - Format Mollie:
    - Content-Type: application/x-www-form-urlencoded
    - Body: id=tr_xxxxxxxx
    - PAS de JSON, PAS de statut dans le payload!

    Returns:
        dict: {"status": "processed"} ou {"status": "already_processed"}
    """
    from app.services.mollie_client import mollie_client
    
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
    5. Générer un PDF individuel par ticket (avec QR code grand et centré)
    6. Envoyer l'email de confirmation avec tous les PDFs en pièces jointes

    Args:
        order_id: ID de la commande à traiter
    """
    from app.db.database import SessionLocal
    from app.services.pdf_service import generate_individual_ticket_pdfs, delete_pdf_file
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

        # 3. Générer un PDF individuel par ticket
        pdf_paths = []
        try:
            pdf_paths = await generate_individual_ticket_pdfs(tickets, order)
            logger.info(f"{len(pdf_paths)} PDFs individuels générés pour commande {order.order_number}")
        except Exception as e:
            logger.error(f"Erreur génération PDFs: {e}")
            # Continuer même si les PDFs échouent
            pdf_paths = []

        # 4. Envoyer l'email de confirmation avec tous les PDFs
        if pdf_paths:
            email_sent = False
            try:
                await send_confirmation_email(
                    to_email=order.customer_email,
                    customer_name=order.customer_name,
                    order=order,
                    tickets=tickets,
                    pdf_paths=pdf_paths
                )
                logger.info(f"Email de confirmation envoyé à {order.customer_email} avec {len(pdf_paths)} billets")
                email_sent = True
            except Exception as e:
                logger.error(f"Erreur envoi email: {e}")
                # Ne pas faire échouer le traitement si email échoue

            # 5. Nettoyer tous les PDFs après envoi réussi
            if email_sent:
                for pdf_path in pdf_paths:
                    delete_pdf_file(pdf_path)
        else:
            logger.warning(f"Pas de PDFs - email non envoyé pour {order.order_number}")

        logger.info(f"Traitement post-paiement terminé pour {order.order_number}")

    except Exception as e:
        db.rollback()
        logger.exception(f"Erreur traitement post-paiement: {e}")
    finally:
        db.close()
