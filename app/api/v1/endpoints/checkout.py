"""Routes pour le processus de paiement - Rate Limited"""
from fastapi import APIRouter, HTTPException, Depends, Request, status
from pydantic import BaseModel, EmailStr
from typing import Optional
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import select
from datetime import datetime, timedelta, timezone
import os
import logging

from app.db.database import get_db
from app.db import models
from app.services.paypal_client import paypal_client, PayPalPaymentClient
from app.api.deps import get_paypal_client, get_settings
from app.utils.generators import generate_order_number
from app.schemas.cart import CartCheckoutRequest, CartCheckoutResponse
from app.core.config import settings, Settings
from app.core.rate_limiter import limiter, RATE_LIMITS

logger = logging.getLogger(__name__)
router = APIRouter()

# Durée de validité d'une commande pending avant expiration
ORDER_PENDING_TIMEOUT_MINUTES = 30


class CheckoutRequest(BaseModel):
    """Demande de création de session de paiement"""
    event_id: str
    pack_id: str
    quantity: int
    customer_name: str
    customer_email: EmailStr
    customer_phone: Optional[str] = None
    
    # GDPR Consent - Mandatory
    terms_accepted: bool = False


class CheckoutResponse(BaseModel):
    """Réponse avec URL de paiement"""
    order_number: str
    pay_url: str
    amount: float  # En EUR
    paypal_order_id: Optional[str] = None


@router.post(
    "/create-session",
    response_model=CheckoutResponse,
    status_code=status.HTTP_201_CREATED,
    responses={
        400: {"description": "Invalid request (pack unavailable, soldout, etc.)"},
        404: {"description": "Event or pack not found"},
        429: {"description": "Rate limit exceeded"},
        500: {"description": "Payment provider error"}
    }
)
@limiter.limit(RATE_LIMITS["checkout"])  # 10 checkout attempts per minute
async def create_checkout_session(
    request: Request,  # Required for rate limiting (must be named 'request' for slowapi)
    checkout_request: CheckoutRequest,
    db: Session = Depends(get_db),
    paypal: PayPalPaymentClient = Depends(get_paypal_client),  # Injection de dépendance
    app_settings: Settings = Depends(get_settings)  # Injection de dépendance
):
    """
    Crée une session de paiement PayPal. (Rate limited: 10/min)

    Flow:
    1. Valider que l'événement et le pack existent
    2. Vérifier la disponibilité avec verrouillage (évite race conditions)
    3. Calculer le montant total
    4. Créer la commande en DB (status=pending)
    5. Appeler PayPal pour créer la commande
    6. Sauvegarder l'ID de la commande PayPal
    7. Retourner l'URL de paiement au frontend

    Args:
        request: Données de la demande de paiement
        db: Session de base de données

    Returns:
        CheckoutResponse avec order_number, pay_url, amount

    Raises:
        HTTPException 404: Si l'événement ou le pack n'existe pas
        HTTPException 400: Si le pack n'est pas actif ou est sold out
        HTTPException 500: Si erreur PayPal ou DB
    """
    # 1. Valider l'événement
    event = db.query(models.Event).filter(models.Event.id == checkout_request.event_id).first()
    if not event:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Événement non trouvé")

    # 2. Valider le pack
    pack = db.query(models.Pack).filter(models.Pack.id == checkout_request.pack_id).first()
    if not pack:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Pack non trouvé")

    if not pack.is_active:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Ce pack n'est plus disponible")

    # 3. Vérifier la disponibilité avec verrouillage FOR UPDATE (évite race conditions)
    event_pack = db.query(models.EventPack).filter(
        models.EventPack.event_id == checkout_request.event_id,
        models.EventPack.pack_id == checkout_request.pack_id
    ).with_for_update().first()

    if not event_pack:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Ce pack n'est pas associé à cet événement")

    # Vérifier soldout manuel
    if event_pack.is_soldout:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Ce pack est complet pour cet événement")
    
    # Vérifier capacité automatique
    if event_pack.capacity is not None:
        remaining = event_pack.capacity - event_pack.sold_count
        if checkout_request.quantity > remaining:
            if remaining <= 0:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Ce pack est complet pour cet événement")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, 
                detail=f"Il ne reste que {remaining} place(s) disponible(s) pour ce pack"
            )

    # 4. Valider la quantité
    if checkout_request.quantity <= 0:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="La quantité doit être supérieure à 0")

    if checkout_request.quantity > 50:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Maximum 50 billets par commande")

    # 5. Calculer le montant
    amount_cents = int(pack.price * checkout_request.quantity * 100)  # Stocker en centimes
    amount_eur = amount_cents / 100  # Pour PayPal (EUR décimaux)

    logger.info(f"Création commande: {checkout_request.quantity}x {pack.name} pour {event.title}")

    # 6. Générer un numéro de commande unique
    order_number = generate_order_number()

    # Vérifier l'unicité (très rare)
    while db.query(models.Order).filter(models.Order.order_number == order_number).first():
        order_number = generate_order_number()
        logger.warning(f"Collision numéro commande, régénération: {order_number}")

    # 7. Créer la commande en DB (status=pending) avec expiration
    order = models.Order(
        order_number=order_number,
        event_id=checkout_request.event_id,
        pack_id=checkout_request.pack_id,
        quantity=checkout_request.quantity,
        amount=amount_cents,
        status="pending",
        customer_email=checkout_request.customer_email,
        customer_name=checkout_request.customer_name,
        customer_phone=checkout_request.customer_phone,
        
        # GDPR Consent
        terms_accepted=checkout_request.terms_accepted,
        terms_accepted_at=datetime.now(timezone.utc),
        
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=ORDER_PENDING_TIMEOUT_MINUTES)
    )

    db.add(order)
    db.commit()
    db.refresh(order)

    logger.info(f"Commande créée: {order_number} - {amount_eur}€")

    # 7.5. Gestion spéciale pour les tickets gratuits (0€)
    if amount_eur == 0:
        logger.info(f"Commande gratuite détectée: {order_number}")

        try:
            # Compléter la commande immédiatement (pas de paiement nécessaire)
            order.status = "completed"
            order.paid_at = datetime.now(timezone.utc)

            # Mettre à jour le compteur de ventes
            event_pack.sold_count = (event_pack.sold_count or 0) + checkout_request.quantity

            db.commit()
            db.refresh(order)
        except Exception as e:
            db.rollback()
            logger.error(f"Erreur lors de la finalisation de la commande gratuite: {e}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Erreur lors de la création de la commande"
            )

        # Générer les tickets immédiatement
        from app.services.ticket_service import generate_tickets_for_order
        from app.services.pdf_service import generate_individual_ticket_pdfs, delete_pdf_file
        from app.services.email_service import send_confirmation_email

        try:
            tickets = await generate_tickets_for_order(order, db)
            pdf_paths = await generate_individual_ticket_pdfs(tickets, order)
            await send_confirmation_email(
                to_email=order.customer_email,
                customer_name=order.customer_name,
                order=order,
                tickets=tickets,
                pdf_paths=pdf_paths
            )
            logger.info(f"Tickets gratuits générés et envoyés pour commande {order_number}")
            # Nettoyer les PDFs après envoi réussi
            for pdf_path in pdf_paths:
                delete_pdf_file(pdf_path)
        except Exception as e:
            logger.error(f"Erreur génération tickets gratuits: {e}")
            # Ne pas échouer la commande, les tickets peuvent être régénérés

        # Retourner une réponse de succès SANS pay_url (pas de paiement nécessaire)
        return CheckoutResponse(
            order_number=order.order_number,
            pay_url=f"{settings.frontend_url}/payment/complete?order={order.order_number}",
            amount=0.0
        )

    # 8. Créer la commande PayPal (seulement si montant > 0)
    try:
        # PayPal supporte tous les montants sans limite spécifique
        
        logger.info(f"🔗 Création commande PayPal pour {order.order_number}")

        payment = paypal.create_order(
            amount=amount_eur,
            description=f"Billets {event.title} x{checkout_request.quantity}",
            return_url=f"{app_settings.frontend_url}/payment/complete?order={order.order_number}",
            cancel_url=f"{app_settings.frontend_url}/payment/complete?order={order.order_number}&status=cancelled",
            reference_id=order.order_number,
            locale="fr-BE",
            payer_email=order.customer_email,
            payer_name=order.customer_name,
            payer_phone=order.customer_phone
        )

        # 9. Sauvegarder l'ID de la commande PayPal
        order.paypal_order_id = payment["id"]
        db.commit()

        logger.info(f"Commande PayPal créée: {payment['id']} pour commande {order.order_number}")

        return CheckoutResponse(
            order_number=order.order_number,
            pay_url=payment["approve_url"] or "",  # Smart Buttons n'utilisent pas ça
            amount=amount_eur,
            paypal_order_id=payment["id"]
        )

    except Exception as e:
        # En cas d'erreur PayPal, marquer la commande comme failed
        logger.error(f"Erreur création commande PayPal: {e}")
        order.status = "failed"
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erreur lors de la création du paiement: {str(e)}"
        )


@router.post(
    "/create-cart-session",
    response_model=CartCheckoutResponse,
    status_code=status.HTTP_201_CREATED,
    responses={
        400: {"description": "Invalid request (pack unavailable, soldout, etc.)"},
        404: {"description": "Event or pack not found"},
        429: {"description": "Rate limit exceeded"},
        500: {"description": "Payment provider error"}
    }
)
@limiter.limit(RATE_LIMITS["checkout"])  # 10 checkout attempts per minute
async def create_cart_checkout_session(
    request: Request,  # Required for rate limiting (must be named 'request' for slowapi)
    cart_request: CartCheckoutRequest,
    db: Session = Depends(get_db),
    paypal: PayPalPaymentClient = Depends(get_paypal_client),  # Injection de dépendance
    app_settings: Settings = Depends(get_settings)  # Injection de dépendance
):
    """
    Crée une session de paiement PayPal pour un panier multi-pack. (Rate limited: 10/min)

    Flow:
    1. Valider tous les packs dans le panier avec verrouillage
    2. Vérifier la capacité pour chaque pack
    3. Calculer le montant total
    4. Créer la commande en DB avec OrderItems (status=pending)
    5. Appeler PayPal pour créer la commande
    6. Sauvegarder l'ID de la commande PayPal
    7. Retourner l'URL de paiement au frontend

    Args:
        request: CartCheckoutRequest avec liste des articles
        db: Session de base de données

    Returns:
        CartCheckoutResponse avec order_number, pay_url, amount, total_items

    Raises:
        HTTPException 404: Si un événement ou pack n'existe pas
        HTTPException 400: Si un pack n'est pas actif ou est sold out
        HTTPException 500: Si erreur PayPal ou DB
    """
    # 1. Valider tous les articles du panier avec verrouillage
    validated_items = []
    total_amount_cents = 0
    event_id = None  # Tous les packs doivent être pour le même événement

    for item in cart_request.items:
        # Valider l'événement
        event = db.query(models.Event).filter(models.Event.id == item.event_id).first()
        if not event:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Événement {item.event_id} non trouvé")

        # Vérifier que tous les packs sont pour le même événement
        if event_id is None:
            event_id = item.event_id
        elif event_id != item.event_id:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Tous les packs doivent être pour le même événement")

        # Valider le pack
        pack = db.query(models.Pack).filter(models.Pack.id == item.pack_id).first()
        if not pack:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Pack {item.pack_id} non trouvé")

        if not pack.is_active:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Le pack {pack.name} n'est plus disponible")

        # Vérifier la disponibilité avec verrouillage FOR UPDATE (évite race conditions)
        event_pack = db.query(models.EventPack).filter(
            models.EventPack.event_id == item.event_id,
            models.EventPack.pack_id == item.pack_id
        ).with_for_update().first()

        if not event_pack:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Le pack {pack.name} n'est pas associé à cet événement")

        # Vérifier soldout manuel
        if event_pack.is_soldout:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Le pack {pack.name} est complet pour cet événement")
        
        # Vérifier capacité automatique
        if event_pack.capacity is not None:
            remaining = event_pack.capacity - event_pack.sold_count
            if item.quantity > remaining:
                if remaining <= 0:
                    raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Le pack {pack.name} est complet pour cet événement")
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST, 
                    detail=f"Il ne reste que {remaining} place(s) disponible(s) pour le pack {pack.name}"
                )

        # Calculer le montant pour cet article
        item_amount_cents = int(pack.price * item.quantity * 100)
        total_amount_cents += item_amount_cents

        # Stocker les informations validées
        validated_items.append({
            "event_id": item.event_id,
            "pack_id": item.pack_id,
            "pack": pack,
            "event_pack": event_pack,
            "quantity": item.quantity,
            "unit_price": pack.price,
            "item_amount_cents": item_amount_cents
        })

    total_amount_eur = total_amount_cents / 100

    logger.info(f"Création commande panier: {len(validated_items)} packs, {sum(item['quantity'] for item in validated_items)} tickets, {total_amount_eur}€")

    # 2. Générer un numéro de commande unique
    order_number = generate_order_number()

    # Vérifier l'unicité (très rare)
    while db.query(models.Order).filter(models.Order.order_number == order_number).first():
        order_number = generate_order_number()
        logger.warning(f"Collision numéro commande, régénération: {order_number}")

    # 3. Créer la commande en DB (status=pending) avec expiration
    order = models.Order(
        order_number=order_number,
        event_id=event_id,
        amount=total_amount_cents,
        status="pending",
        customer_email=cart_request.customer_email,
        customer_name=cart_request.customer_name,
        customer_phone=cart_request.customer_phone,
        
        # GDPR Consent
        terms_accepted=cart_request.terms_accepted,
        terms_accepted_at=datetime.now(timezone.utc),
        
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=ORDER_PENDING_TIMEOUT_MINUTES)
    )

    db.add(order)
    db.flush()  # Flush pour obtenir l'ID de la commande

    # 4. Créer les OrderItems
    for item_data in validated_items:
        order_item = models.OrderItem(
            order_id=order.id,
            pack_id=item_data["pack_id"],
            event_id=item_data["event_id"],
            quantity=item_data["quantity"],
            unit_price=item_data["unit_price"]
        )
        db.add(order_item)

    db.commit()
    db.refresh(order)

    logger.info(f"Commande panier créée: {order_number} - {len(validated_items)} packs - {total_amount_eur}€")

    # 4.5. Gestion du paiement cash ou virement bancaire
    if cart_request.payment_method in ["cash", "bank_transfer"]:
        payment_type = cart_request.payment_method
        logger.info(f"Réservation {payment_type} détectée: {order_number}")

        order.payment_method = payment_type
        order.status = "pending_cash"  # Statut spécial pour les réservations en attente
        order.expires_at = None  # Pas d'expiration pour ces réservations
        db.commit()
        db.refresh(order)

        # Envoyer l'email approprié selon le type de paiement
        try:
            if payment_type == "bank_transfer":
                from app.services.email_service import send_pending_bank_transfer_reservation_email
                await send_pending_bank_transfer_reservation_email(
                    to_email=order.customer_email,
                    customer_name=order.customer_name,
                    order=order
                )
            else:
                from app.services.email_service import send_pending_cash_reservation_email
                await send_pending_cash_reservation_email(
                    to_email=order.customer_email,
                    customer_name=order.customer_name,
                    order=order
                )
            logger.info(f"Email réservation {payment_type} envoyé pour commande {order_number}")
        except Exception as e:
            logger.error(f"Erreur envoi email réservation {payment_type}: {e}")

        # Retourner une réponse sans URL de paiement
        return CartCheckoutResponse(
            order_number=order.order_number,
            pay_url=f"{app_settings.frontend_url}/payment/complete?order={order.order_number}",
            amount=total_amount_eur,
            total_items=len(validated_items),
            payment_method=payment_type,
            is_pending_cash=True
        )
    
    # 4.6. Gestion spéciale pour les commandes gratuites (0€)
    if total_amount_eur == 0:
        logger.info(f"Commande panier gratuite détectée: {order_number}")

        # Compléter la commande immédiatement (pas de paiement nécessaire)
        order.status = "completed"
        order.paid_at = datetime.now(timezone.utc)

        # Mettre à jour le compteur de ventes pour chaque pack
        for item_data in validated_items:
            event_pack = item_data["event_pack"]
            event_pack.sold_count = (event_pack.sold_count or 0) + item_data["quantity"]

        db.commit()
        db.refresh(order)

        # Générer les tickets immédiatement
        from app.services.ticket_service import generate_tickets_for_order
        from app.services.pdf_service import generate_individual_ticket_pdfs, delete_pdf_file
        from app.services.email_service import send_confirmation_email

        try:
            tickets = await generate_tickets_for_order(order, db)
            pdf_paths = await generate_individual_ticket_pdfs(tickets, order)
            await send_confirmation_email(
                to_email=order.customer_email,
                customer_name=order.customer_name,
                order=order,
                tickets=tickets,
                pdf_paths=pdf_paths
            )
            logger.info(f"Tickets gratuits (panier) générés et envoyés pour commande {order_number}")
            # Nettoyer les PDFs après envoi réussi
            for pdf_path in pdf_paths:
                delete_pdf_file(pdf_path)
        except Exception as e:
            logger.error(f"Erreur génération tickets gratuits (panier): {e}")
            # Ne pas échouer la commande, les tickets peuvent être régénérés

        # Retourner une réponse de succès SANS pay_url (pas de paiement nécessaire)
        return CartCheckoutResponse(
            order_number=order.order_number,
            pay_url=f"{settings.frontend_url}/payment/complete?order={order.order_number}",
            amount=0.0,
            total_items=len(validated_items),
            payment_method="online",
            is_pending_cash=False
        )

    # 5. Créer la commande PayPal (seulement si montant > 0)
    try:
        # Construire la description
        event = db.query(models.Event).filter(models.Event.id == event_id).first()
        pack_names = [item_data["pack"].name for item_data in validated_items]
        description = f"Billets {event.title} - {', '.join(pack_names)}"
        
        logger.info(f"🔗 Création commande PayPal pour panier: {order.order_number}")

        payment = paypal.create_order(
            amount=total_amount_eur,
            description=description,
            return_url=f"{app_settings.frontend_url}/payment/complete?order={order.order_number}",
            cancel_url=f"{app_settings.frontend_url}/payment/complete?order={order.order_number}&status=cancelled",
            reference_id=order.order_number,
            locale="fr-BE",
            payer_email=order.customer_email,
            payer_name=order.customer_name,
            payer_phone=order.customer_phone,
            payment_source=cart_request.payment_source  # bancontact, card, paypal
        )

        # 6. Sauvegarder l'ID de la commande PayPal
        order.paypal_order_id = payment["id"]
        db.commit()

        logger.info(f"Commande PayPal créée pour panier: {payment['id']} - {order.order_number}")

        return CartCheckoutResponse(
            order_number=order.order_number,
            pay_url=payment["approve_url"] or "",  # Smart Buttons n'utilisent pas ça
            amount=total_amount_eur,
            total_items=len(validated_items),
            payment_method="online",
            is_pending_cash=False,
            paypal_order_id=payment["id"]
        )

    except Exception as e:
        # En cas d'erreur PayPal, marquer la commande comme failed
        logger.error(f"Erreur création commande PayPal pour panier: {e}")
        order.status = "failed"
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erreur lors de la création du paiement: {str(e)}"
        )


@router.get("/order/{order_number}")
@limiter.limit(RATE_LIMITS["order_status"])  # 60 status checks per minute
def get_order_status(request: Request, order_number: str, db: Session = Depends(get_db)):
    """
    Récupère le statut d'une commande. (Rate limited: 60/min)

    Utilisé par la page de retour après paiement pour afficher
    l'état de la commande et les billets si le paiement est complété.

    Args:
        order_number: Numéro de commande (ex: BABA-ABC123)
        db: Session de base de données

    Returns:
        dict avec order_number, status, amount, event_name, quantity, tickets

    Raises:
        HTTPException 404: Si la commande n'existe pas
    """
    # Charger l'ordre avec toutes les relations nécessaires
    order = db.query(models.Order).options(
        joinedload(models.Order.event),
        joinedload(models.Order.tickets),
        joinedload(models.Order.items).joinedload(models.OrderItem.pack)
    ).filter(
        models.Order.order_number == order_number
    ).first()

    if not order:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Commande non trouvée")

    # Récupérer les tickets si la commande est completed
    tickets_data = []
    if order.status == "completed" and order.tickets:
        tickets_data = [
            {
                "code": ticket.ticket_code,
                "holder": ticket.holder_name,
                "status": ticket.status
            }
            for ticket in order.tickets
        ]

    logger.info(f"📋 GET order {order_number}: status={order.status}, tickets_generated={order.tickets_generated}")

    # For bank_transfer orders, include bank account details from the event
    bank_account_info = {}
    if order.payment_method == "bank_transfer" and order.event:
        bank_account_info = {
            "bank_account_iban": order.event.bank_account_iban,
            "bank_account_name": order.event.bank_account_name,
            "bank_account_bic": order.event.bank_account_bic
        }

    return {
        "order_number": order.order_number,
        "status": order.status,
        "amount": order.amount / 100,  # Convertir en EUR
        "event_name": order.event.title,
        "event_id": order.event.id,
        "event_slug": order.event.slug,  # Slug pour les URLs SEO-friendly
        "quantity": order.total_quantity,  # Utiliser la propriété pour supporter les deux systèmes
        "pack_display": order.pack_display,  # Résumé des packs achetés
        "pack_items": order.pack_items_list,  # Détail des packs
        "customer_email": order.customer_email,
        "customer_name": order.customer_name,
        "payment_method": order.payment_method,  # online, cash, or bank_transfer
        "tickets": tickets_data,
        "created_at": order.created_at.isoformat() if order.created_at else None,
        "paid_at": order.paid_at.isoformat() if order.paid_at else None,
        **bank_account_info
    }


class CapturePaymentRequest(BaseModel):
    paypal_order_id: str


@router.post("/capture-payment/{order_number}")
async def capture_payment(
    order_number: str,
    capture_req: CapturePaymentRequest,
    db: Session = Depends(get_db),
    paypal: PayPalPaymentClient = Depends(get_paypal_client)
):
    """
    Capture le paiement PayPal (appelé depuis le frontend via JS SDK).
    """
    # 1. Récupérer la commande locale
    order = db.query(models.Order).filter(models.Order.order_number == order_number).first()
    if not order:
        raise HTTPException(status_code=404, detail="Commande non trouvée")

    # 2. Vérifier que c'est bien la bonne commande PayPal
    if order.paypal_order_id != capture_req.paypal_order_id:
        # Cas où l'ID n'a pas été sauvegardé (ex: création via une autre méthode?)
        # Ou tentative de fraude/mismatch
        if not order.paypal_order_id:
            # On l'associe maintenant pour être sûr (si pas déjà fait)
            order.paypal_order_id = capture_req.paypal_order_id
            db.commit()
        else:
            raise HTTPException(status_code=400, detail="Mismatch PayPal Order ID")

    # 3. Vérifier le statut
    if order.status == "completed":
        return {"status": "completed", "message": "Déjà payé"}
    
    # 4. Capturer via PayPal (Check if already captured by checking API status?)
    try:
        # get_order d'abord pour vérifier statut chez PayPal ?
        # Ou capture directe. Si déjà capturé, PayPal renverra une erreur ou infos.
        # On tente de capturer.
        capture_result = paypal.capture_order(capture_req.paypal_order_id)
        
        if capture_result["status"] != "COMPLETED":
             raise HTTPException(status_code=400, detail=f"Statut PayPal non valide: {capture_result['status']}")

    except Exception as e:
        logger.error(f"Erreur capture PayPal: {e}")
        # On vérifie si c'est "Order already captured"
        # Si oui, on continue le process de finalisation
        # Sinon, erreur
        raise HTTPException(status_code=500, detail="Erreur lors de la capture PayPal")

    # 5. Finaliser la commande
    order.status = "completed"
    order.paid_at = datetime.now(timezone.utc)
    
    # Update sold counts
    items = db.query(models.OrderItem).filter(models.OrderItem.order_id == order.id).all()
    # Note: Logic duplicated from webhook/checkout - consider refactoring into service
    # Pour l'instant on garde simple (on suppose que les sold_count ont été incrémentés à la création si le système le fait,
    # MAIS ici c'était pending. pending ne décrémente pas le stock dispo global si on utilise capacity? 
    # create_session vérifie capacity mais n'incrémente pas sold_count (seulement paid le fait?)
    # CHECKOUT.PY L176 (gratuit) incrémente sold_count.
    # L'implémentation actuelle incrémente sold_count uniquement au paiement?
    # WEBHOOKS.PY: `event_pack.sold_count = (event_pack.sold_count or 0) + item.quantity`
    # Donc OUI, il faut incrémenter ici.
    
    for item in items:
        # Trouver le EventPack
        ep = db.query(models.EventPack).filter(
            models.EventPack.event_id == item.event_id, 
            models.EventPack.pack_id == item.pack_id
        ).with_for_update().first()
        
        if ep:
            ep.sold_count = (ep.sold_count or 0) + item.quantity

    db.commit()
    db.refresh(order)

    # 6. Générer tickets et envoyer email
    from app.services.ticket_service import generate_tickets_for_order
    from app.services.pdf_service import generate_individual_ticket_pdfs, delete_pdf_file
    from app.services.email_service import send_confirmation_email

    try:
        tickets = await generate_tickets_for_order(order, db)
        pdf_paths = await generate_individual_ticket_pdfs(tickets, order)
        await send_confirmation_email(
            to_email=order.customer_email,
            customer_name=order.customer_name,
            order=order,
            tickets=tickets,
            pdf_paths=pdf_paths
        )
        # Nettoyer
        for pdf_path in pdf_paths:
            delete_pdf_file(pdf_path)
    except Exception as e:
        logger.error(f"Erreur tickets/mail post-capture: {e}")
        # Non-bloquant pour la réponse au client (il a payé)

    return {"status": "completed", "order_number": order.order_number}


@router.post("/cancel/{order_number}")
async def cancel_order(
    order_number: str,
    db: Session = Depends(get_db)
):
    """
    Marque une commande comme annulée.
    Appelé quand l'utilisateur annule le paiement sur PayPal.
    
    Seules les commandes en statut "pending" peuvent être annulées.
    """
    # Récupérer la commande
    order = db.query(models.Order).filter(
        models.Order.order_number == order_number
    ).first()
    
    if not order:
        raise HTTPException(status_code=404, detail="Commande non trouvée")
    
    # Vérifier que la commande peut être annulée
    if order.status == "cancelled":
        # Déjà annulée, on renvoie simplement le statut
        return {"status": "cancelled", "order_number": order.order_number}
    
    if order.status == "completed":
        # Une commande payée ne peut pas être annulée via cet endpoint
        raise HTTPException(
            status_code=400, 
            detail="Impossible d'annuler une commande déjà payée"
        )
    
    if order.status not in ["pending", "pending_cash"]:
        raise HTTPException(
            status_code=400,
            detail=f"Impossible d'annuler une commande avec le statut: {order.status}"
        )
    
    # Annuler la commande
    order.status = "cancelled"
    db.commit()
    
    logger.info(f"Commande {order_number} annulée par l'utilisateur")
    
    return {"status": "cancelled", "order_number": order.order_number}
