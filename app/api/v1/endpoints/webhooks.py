"""Routes pour les webhooks de paiement"""
from fastapi import APIRouter, Request, HTTPException, BackgroundTasks, Depends
from sqlalchemy.orm import Session, joinedload
from datetime import datetime, timezone
import logging
import json

from app.db.database import get_db
from app.db import models
from app.services.ticket_service import generate_tickets_for_order
from app.core.config import settings

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
    from app.services.paypal_client import paypal_client, verify_webhook_signature
    
    # Récupérer le body brut AVANT le parsing JSON (nécessaire pour la vérification de signature)
    raw_body = await request.body()
    
    # Vérifier la signature PayPal
    signature_verified = verify_webhook_signature(
        webhook_id=settings.paypal_webhook_id,
        transmission_id=request.headers.get("PAYPAL-TRANSMISSION-ID"),
        timestamp=request.headers.get("PAYPAL-TRANSMISSION-TIME"),
        webhook_signature=request.headers.get("PAYPAL-TRANSMISSION-SIG"),
        cert_url=request.headers.get("PAYPAL-CERT-URL"),
        auth_algo=request.headers.get("PAYPAL-AUTH-ALGO"),
        raw_body=raw_body,
        paypal_client_instance=paypal_client
    )
    
    if not signature_verified:
        logger.warning("❌ Signature webhook PayPal invalide - requête rejetée")
        raise HTTPException(status_code=401, detail="Invalid webhook signature")
    
    # Parser le JSON
    try:
        body = json.loads(raw_body.decode('utf-8'))
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
            # L'ordre a été approuvé (PayPal wallet), il faut le capturer
            logger.info(f"📝 Commande approuvée, capture en cours: {order.order_number}")
            
            paypal_order_id = resource.get("id")
            capture_result = paypal_client.capture_order(paypal_order_id)
            
            if capture_result.get("status") == "COMPLETED":
                # Paiement réussi !
                if order.status != "completed":  # Idempotence
                    order.status = "completed"
                    order.paid_at = datetime.now(timezone.utc)
                    
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
                
        elif event_type == "CHECKOUT.ORDER.COMPLETED":
            # Pour les APMs (Bancontact, etc.), le paiement est capturé automatiquement
            # On reçoit directement CHECKOUT.ORDER.COMPLETED sans besoin de capture manuelle
            logger.info(f"📝 Commande APM complétée automatiquement: {order.order_number}")
            
            if order.status != "completed":  # Idempotence
                order.status = "completed"
                order.paid_at = datetime.now(timezone.utc)
                
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
                order.paid_at = datetime.now(timezone.utc)
                
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
        webhook_event.processed_at = datetime.now(timezone.utc)
        db.commit()
        
        return {"status": "processed"}
        
    except Exception as e:
        webhook_event.status = "failed"
        webhook_event.error_message = str(e)
        db.commit()
        logger.exception(f"❌ Erreur traitement webhook PayPal: {e}")
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
