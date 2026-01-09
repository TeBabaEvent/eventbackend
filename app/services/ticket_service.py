"""
Service de génération et gestion des tickets
Génère les tickets avec QR codes JWT signés
"""
import jwt
from datetime import datetime, timedelta, timezone
from io import BytesIO
from sqlalchemy.orm import Session
from typing import List, Optional
import logging

from app.db.models import Ticket, Event, Order
from app.utils.generators import generate_ticket_code
from app.core.config import settings

logger = logging.getLogger(__name__)

# ============== VALIDATION JWT ==============

def _validate_jwt_config():
    """Valide la configuration JWT au démarrage"""
    if not settings.jwt_secret_key:
        logger.error("❌ JWT_SECRET_KEY non configurée dans .env")
        raise ValueError("JWT_SECRET_KEY est requise pour la sécurité des tickets")
    
    if len(settings.jwt_secret_key) < 32:
        logger.warning("⚠️ JWT_SECRET_KEY trop courte (recommandé: min 32 caractères)")

# Valider au chargement du module
try:
    _validate_jwt_config()
except ValueError as e:
    logger.warning(f"Configuration JWT: {e}")


def generate_ticket_qr_data(ticket: Ticket, event: Event) -> str:
    """
    Génère le JWT pour le QR code d'un ticket.

    Le JWT contient:
    - ticket_id, ticket_code: Identifiants du ticket
    - event_id, event_name: Identifiants de l'événement
    - holder: Nom du titulaire
    - iat: Date de création
    - exp: Date d'expiration (24h après l'événement)

    Args:
        ticket: Le ticket à encoder
        event: L'événement associé

    Returns:
        str: JWT signé

    Example:
        >>> jwt_token = generate_ticket_qr_data(ticket, event)
        >>> # Le QR code contiendra ce JWT
    """
    # Calculer la date d'expiration
    # Format de event.date: "YYYY-MM-DD"
    try:
        event_date = datetime.strptime(event.date, "%Y-%m-%d")
    except (ValueError, AttributeError):
        # Si parsing échoue, utiliser 7 jours à partir d'aujourd'hui
        event_date = datetime.now(timezone.utc)
        logger.warning(f"Date événement invalide: {event.date}, utilisation date actuelle")

    expiration = event_date + timedelta(days=1)  # Expire 24h après l'événement

    payload = {
        "ticket_id": ticket.id,
        "ticket_code": ticket.ticket_code,
        "event_id": event.id,
        "event_name": event.title,
        "pack_id": ticket.pack_id,
        "pack_name": ticket.pack_name or "Standard",
        "holder": ticket.holder_name or "Invité",
        "iat": datetime.now(timezone.utc),
        "exp": expiration
    }

    token = jwt.encode(payload, settings.jwt_secret_key, algorithm="HS256")
    logger.debug(f"JWT généré pour ticket {ticket.ticket_code}")

    return token


def generate_qr_image(qr_data: str) -> bytes:
    """
    Génère l'image QR code avec segno.

    Args:
        qr_data: Les données à encoder (JWT)

    Returns:
        bytes: Image PNG du QR code

    Note:
        Utilise segno car c'est plus rapide et sans dépendances que qrcode
    """
    try:
        import segno
    except ImportError:
        logger.error("segno n'est pas installé. Exécutez: pip install segno")
        raise ImportError("segno est requis pour la génération de QR codes")

    # Créer le QR code avec correction d'erreur haute
    qr = segno.make(qr_data, error='H')

    # Générer l'image PNG en mémoire
    buffer = BytesIO()
    qr.save(buffer, kind='png', scale=10, border=2)

    logger.debug("Image QR générée")
    return buffer.getvalue()


async def generate_tickets_for_order(order: Order, db: Session) -> List[Ticket]:
    """
    Génère tous les tickets d'une commande après paiement.

    Support deux types de commandes:
    - Commandes legacy (single-pack): Utilise order.quantity
    - Commandes panier (multi-pack): Utilise order.items (OrderItems)

    Pour chaque ticket:
    1. Génère un code unique (BABA-XXXXXXXX)
    2. Crée le JWT pour le QR code
    3. Crée l'entrée en base de données

    Args:
        order: La commande payée
        db: Session de base de données

    Returns:
        List[Ticket]: Liste des tickets générés

    Example:
        >>> tickets = await generate_tickets_for_order(order, db)
        >>> len(tickets) == order.total_quantity
        True
    """
    tickets = []

    # Récupérer l'événement (nécessaire pour le JWT)
    event = order.event

    # Déterminer le type de commande
    if order.is_cart_order:
        # Nouvelle logique multi-pack avec OrderItems
        logger.info(f"Génération tickets pour commande panier {order.order_number} ({len(order.items)} packs)")

        ticket_index = 0
        for order_item in order.items:
            # Récupérer le nom du pack pour le snapshot
            pack_name = order_item.pack.name if order_item.pack else None
            
            # Générer les tickets pour chaque OrderItem
            for i in range(order_item.quantity):
                # Générer un code unique
                ticket_code = generate_ticket_code()

                # Vérifier l'unicité (très rare, mais possible)
                while db.query(Ticket).filter(Ticket.ticket_code == ticket_code).first():
                    ticket_code = generate_ticket_code()
                    logger.warning(f"Collision code ticket, régénération: {ticket_code}")

                # Créer le ticket avec référence au pack
                ticket = Ticket(
                    ticket_code=ticket_code,
                    order_id=order.id,
                    event_id=order.event_id,
                    pack_id=order_item.pack_id,
                    pack_name=pack_name,
                    holder_name=order.customer_name if ticket_index == 0 else f"Invité {ticket_index}",
                    status="valid"
                )

                # Générer le QR data (JWT)
                ticket.qr_data = generate_ticket_qr_data(ticket, event)

                db.add(ticket)
                tickets.append(ticket)
                ticket_index += 1

        logger.info(f"{len(tickets)} tickets générés pour {len(order.items)} packs différents")

    else:
        # Ancienne logique single-pack (backward compatibility)
        logger.info(f"Génération de {order.quantity} tickets pour commande {order.order_number}")
        
        # Récupérer le nom du pack pour le snapshot
        pack_name = order.pack.name if order.pack else None

        for i in range(order.quantity):
            # Générer un code unique
            ticket_code = generate_ticket_code()

            # Vérifier l'unicité (très rare, mais possible)
            while db.query(Ticket).filter(Ticket.ticket_code == ticket_code).first():
                ticket_code = generate_ticket_code()
                logger.warning(f"Collision code ticket, régénération: {ticket_code}")

            # Créer le ticket avec référence au pack
            ticket = Ticket(
                ticket_code=ticket_code,
                order_id=order.id,
                event_id=order.event_id,
                pack_id=order.pack_id,
                pack_name=pack_name,
                holder_name=order.customer_name if i == 0 else f"Invité {i}",
                status="valid"
            )

            # Générer le QR data (JWT)
            ticket.qr_data = generate_ticket_qr_data(ticket, event)

            db.add(ticket)
            tickets.append(ticket)

    db.commit()

    # Refresh pour avoir les IDs générés
    for ticket in tickets:
        db.refresh(ticket)

    logger.info(f"{len(tickets)} tickets générés avec succès")
    return tickets
