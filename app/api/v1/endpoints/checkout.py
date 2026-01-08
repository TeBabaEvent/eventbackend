"""Routes pour le processus de paiement - Rate Limited"""
from fastapi import APIRouter, HTTPException, Depends, Request, status
from pydantic import BaseModel, EmailStr
from typing import Optional
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import select
from datetime import datetime, timedelta
import os
import logging

from app.db.database import get_db
from app.db import models
from app.services.mollie_client import mollie_client, MolliePaymentClient
from app.api.deps import get_mollie_client, get_settings
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


class CheckoutResponse(BaseModel):
    """Réponse avec URL de paiement"""
    order_number: str
    pay_url: str
    amount: float  # En EUR


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
    mollie: MolliePaymentClient = Depends(get_mollie_client),  # Injection de dépendance
    app_settings: Settings = Depends(get_settings)  # Injection de dépendance
):
    """
    Crée une session de paiement Mollie. (Rate limited: 10/min)

    Flow:
    1. Valider que l'événement et le pack existent
    2. Vérifier la disponibilité avec verrouillage (évite race conditions)
    3. Calculer le montant total
    4. Créer la commande en DB (status=pending)
    5. Appeler Mollie pour créer le paiement
    6. Sauvegarder l'ID du paiement Mollie
    7. Retourner l'URL de paiement au frontend

    Args:
        request: Données de la demande de paiement
        db: Session de base de données

    Returns:
        CheckoutResponse avec order_number, pay_url, amount

    Raises:
        HTTPException 404: Si l'événement ou le pack n'existe pas
        HTTPException 400: Si le pack n'est pas actif ou est sold out
        HTTPException 500: Si erreur Mollie ou DB
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
    amount_eur = amount_cents / 100  # Pour Mollie (EUR décimaux)

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
        expires_at=datetime.utcnow() + timedelta(minutes=ORDER_PENDING_TIMEOUT_MINUTES)
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
            order.paid_at = datetime.utcnow()

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

        # Retourner une réponse de succès SANS pay_url (pas de redirection Mollie)
        return CheckoutResponse(
            order_number=order.order_number,
            pay_url=f"{settings.frontend_url}/payment/complete?order={order.order_number}",
            amount=0.0
        )

    # 8. Créer le paiement Mollie (seulement si montant > 0)
    try:
        # Note: Mollie Bancontact n'a pas de limite QR de 1500€ comme CCV
        # Le paiement fonctionnera pour tous les montants
        
        # Debug: log webhook URL
        webhook_url = f"{app_settings.base_url}/api/webhooks/mollie"
        logger.info(f"🔗 Webhook URL pour Mollie: {webhook_url}")

        payment = mollie.create_payment(
            amount=amount_eur,
            description=f"Billets {event.title} x{checkout_request.quantity}",
            redirect_url=f"{app_settings.frontend_url}/payment/complete?order={order.order_number}",
            webhook_url=webhook_url,
            metadata={
                "order_number": order.order_number,
                "event_id": str(event.id),
                "customer_email": checkout_request.customer_email
            },
            method="bancontact",  # Forcer Bancontact (ou None pour choix libre)
            locale="fr_BE"  # Français Belgique
        )

        # 9. Sauvegarder l'ID du paiement Mollie
        order.mollie_payment_id = payment["id"]
        db.commit()

        logger.info(f"Paiement Mollie créé: {payment['id']} pour commande {order.order_number}")

        return CheckoutResponse(
            order_number=order.order_number,
            pay_url=payment["checkout_url"],
            amount=amount_eur
        )

    except Exception as e:
        # En cas d'erreur Mollie, marquer la commande comme failed
        logger.error(f"Erreur création paiement Mollie: {e}")
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
    mollie: MolliePaymentClient = Depends(get_mollie_client),  # Injection de dépendance
    app_settings: Settings = Depends(get_settings)  # Injection de dépendance
):
    """
    Crée une session de paiement Mollie pour un panier multi-pack. (Rate limited: 10/min)

    Flow:
    1. Valider tous les packs dans le panier avec verrouillage
    2. Vérifier la capacité pour chaque pack
    3. Calculer le montant total
    4. Créer la commande en DB avec OrderItems (status=pending)
    5. Appeler Mollie pour créer le paiement
    6. Sauvegarder l'ID du paiement Mollie
    7. Retourner l'URL de paiement au frontend

    Args:
        request: CartCheckoutRequest avec liste des articles
        db: Session de base de données

    Returns:
        CartCheckoutResponse avec order_number, pay_url, amount, total_items

    Raises:
        HTTPException 404: Si un événement ou pack n'existe pas
        HTTPException 400: Si un pack n'est pas actif ou est sold out
        HTTPException 500: Si erreur Mollie ou DB
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
        expires_at=datetime.utcnow() + timedelta(minutes=ORDER_PENDING_TIMEOUT_MINUTES)
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

    # 4.5. Gestion spéciale pour les commandes gratuites (0€)
    if total_amount_eur == 0:
        logger.info(f"Commande panier gratuite détectée: {order_number}")

        # Compléter la commande immédiatement (pas de paiement nécessaire)
        order.status = "completed"
        order.paid_at = datetime.utcnow()

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

        # Retourner une réponse de succès SANS pay_url (pas de redirection Mollie)
        return CartCheckoutResponse(
            order_number=order.order_number,
            pay_url=f"{settings.frontend_url}/payment/complete?order={order.order_number}",
            amount=0.0,
            total_items=len(validated_items)
        )

    # 5. Créer le paiement Mollie (seulement si montant > 0)
    try:
        # Construire la description
        event = db.query(models.Event).filter(models.Event.id == event_id).first()
        pack_names = [item_data["pack"].name for item_data in validated_items]
        description = f"Billets {event.title} - {', '.join(pack_names)}"
        
        # Debug: log webhook URL
        webhook_url = f"{app_settings.base_url}/api/webhooks/mollie"
        logger.info(f"🔗 Webhook URL pour Mollie: {webhook_url}")

        payment = mollie.create_payment(
            amount=total_amount_eur,
            description=description,
            redirect_url=f"{app_settings.frontend_url}/payment/complete?order={order.order_number}",
            webhook_url=webhook_url,
            metadata={
                "order_number": order.order_number,
                "event_id": str(event_id),
                "customer_email": cart_request.customer_email,
                "is_cart": "true",
                "total_packs": str(len(validated_items))
            },
            method="bancontact",  # Forcer Bancontact (ou None pour choix libre)
            locale="fr_BE"  # Français Belgique
        )

        # 6. Sauvegarder l'ID du paiement Mollie
        order.mollie_payment_id = payment["id"]
        db.commit()

        logger.info(f"Paiement Mollie créé pour panier: {payment['id']} - {order.order_number}")

        return CartCheckoutResponse(
            order_number=order.order_number,
            pay_url=payment["checkout_url"],
            amount=total_amount_eur,
            total_items=len(validated_items)
        )

    except Exception as e:
        # En cas d'erreur Mollie, marquer la commande comme failed
        logger.error(f"Erreur création paiement Mollie pour panier: {e}")
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

    return {
        "order_number": order.order_number,
        "status": order.status,
        "amount": order.amount / 100,  # Convertir en EUR
        "event_name": order.event.title,
        "event_id": order.event.id,
        "quantity": order.total_quantity,  # Utiliser la propriété pour supporter les deux systèmes
        "pack_display": order.pack_display,  # Résumé des packs achetés
        "pack_items": order.pack_items_list,  # Détail des packs
        "customer_email": order.customer_email,
        "customer_name": order.customer_name,
        "tickets": tickets_data,
        "created_at": order.created_at.isoformat() if order.created_at else None,
        "paid_at": order.paid_at.isoformat() if order.paid_at else None
    }
