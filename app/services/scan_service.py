"""
Service de validation des scans de tickets
Gère la validation des QR codes et le logging des scans
"""
import jwt
from datetime import datetime
from sqlalchemy.orm import Session
from typing import Optional, Dict, Any
import logging

from app.db.models import Ticket, ScanLog, Event
from app.core.config import settings

logger = logging.getLogger(__name__)

# Validation de la clé JWT au chargement du module
if not settings.jwt_secret_key or len(settings.jwt_secret_key) < 32:
    logger.warning("⚠️ JWT_SECRET_KEY non configurée ou trop courte (min 32 caractères)")


def decode_qr_jwt(qr_data: str) -> Dict[str, Any]:
    """
    Décode et valide le JWT du QR code.
    
    Args:
        qr_data: Le contenu du QR code (JWT)
    
    Returns:
        dict: Payload décodé du JWT
    
    Raises:
        jwt.ExpiredSignatureError: Si le JWT est expiré
        jwt.InvalidTokenError: Si le JWT est invalide
    """
    return jwt.decode(
        qr_data,
        settings.jwt_secret_key,
        algorithms=["HS256"]
    )


def log_scan(
    db: Session,
    ticket_id: Optional[str],
    qr_data: str,
    event_id: Optional[str],
    steward_id: str,
    result: str,
    auto_commit: bool = True
) -> ScanLog:
    """
    Enregistre un scan dans les logs pour audit.

    Args:
        db: Session de base de données
        ticket_id: ID du ticket (None si invalide)
        qr_data: Données scannées (tronquées à 500 caractères)
        event_id: ID de l'événement (peut être None si non déterminé)
        steward_id: ID du steward
        result: Résultat du scan (success, already_used, invalid, etc.)
        auto_commit: Si True, commit automatiquement (défaut: True)
    
    Returns:
        ScanLog: L'entrée de log créée
    """
    # Tronquer le QR data pour éviter les problèmes de stockage (JWT peut être long)
    truncated_qr = qr_data[:500] if qr_data else ""
    
    log_entry = ScanLog(
        ticket_id=ticket_id,
        scanned_code=truncated_qr,
        event_id=event_id,  # Peut être None si l'événement n'a pas pu être déterminé
        steward_id=steward_id,
        result=result
    )
    
    db.add(log_entry)
    
    if auto_commit:
        try:
            db.commit()
            db.refresh(log_entry)
        except Exception as e:
            logger.error(f"Erreur lors du commit du log de scan: {e}")
            db.rollback()
    
    return log_entry


def validate_ticket_scan(
    qr_data: str,
    steward_id: str,
    db: Session,
    event_id: Optional[str] = None
) -> Dict[str, Any]:
    """
    Valide un scan de ticket.

    L'event_id est extrait automatiquement du QR code (JWT).
    Si un event_id est fourni en paramètre, il sert de vérification croisée optionnelle.

    Processus de validation:
    1. Décoder et vérifier le JWT (signature, expiration)
    2. Vérifier que l'événement du ticket existe
    3. Récupérer le ticket en DB avec verrouillage (évite race condition)
    4. Vérifier le statut du ticket (valid, used, cancelled, expired)
    5. Si valide: marquer comme utilisé et logger le succès

    Args:
        qr_data: Contenu du QR code (JWT signé)
        steward_id: ID du steward qui scanne
        db: Session de base de données
        event_id: ID de l'événement (optionnel, pour vérification croisée)

    Returns:
        dict avec:
        - valid: bool (True si scan réussi)
        - result: str (success, already_used, invalid, cancelled, expired, wrong_event)
        - message: str (message à afficher au steward)
        - ticket: Ticket | None (si trouvé)
        - holder: str | None (nom du titulaire)
        - pack_name: str | None (type de pack)
        - event_id: str | None (ID de l'événement du ticket)
        - event_name: str | None (nom de l'événement)

    Example:
        >>> result = validate_ticket_scan(qr_data, steward_id, db)
        >>> if result['valid']:
        >>>     print(f"✓ Entrée validée pour {result['holder']}")
    """
    ticket_event_id = None
    ticket_event_name = None
    
    # ========== 1. DÉCODAGE JWT ==========
    try:
        payload = decode_qr_jwt(qr_data)
        ticket_event_id = payload.get("event_id")
        ticket_event_name = payload.get("event_name")
        
    except jwt.ExpiredSignatureError:
        # JWT expiré (événement passé depuis >24h)
        logger.info(f"Scan: JWT expiré")
        log_scan(db, None, qr_data, event_id, steward_id, "expired")
        return {
            "valid": False,
            "result": "expired",
            "message": "Ce billet a expiré",
            "ticket": None,
            "holder": None,
            "pack_name": None,
            "event_id": None,
            "event_name": None
        }

    except jwt.InvalidTokenError as e:
        # JWT invalide (falsifié, corrompu, mauvaise signature, etc.)
        logger.warning(f"Scan: JWT invalide - {type(e).__name__}: {e}")
        log_scan(db, None, qr_data, event_id, steward_id, "invalid")
        return {
            "valid": False,
            "result": "invalid",
            "message": "QR code invalide ou falsifié",
            "ticket": None,
            "holder": None,
            "pack_name": None,
            "event_id": None,
            "event_name": None
        }
    
    # ========== 2. VÉRIFICATION ÉVÉNEMENT ==========
    event = db.query(Event).filter(Event.id == ticket_event_id).first()
    
    if not event:
        logger.warning(f"Scan: Événement non trouvé - {ticket_event_id}")
        log_scan(db, None, qr_data, ticket_event_id, steward_id, "invalid")
        return {
            "valid": False,
            "result": "invalid",
            "message": "Événement du billet non trouvé",
            "ticket": None,
            "holder": None,
            "pack_name": None,
            "event_id": ticket_event_id,
            "event_name": ticket_event_name
        }
    
    # Vérification croisée optionnelle (si steward scanne pour un événement spécifique)
    if event_id and event_id != ticket_event_id:
        logger.warning(f"Scan: Mauvais événement - attendu {event_id}, reçu {ticket_event_id}")
        log_scan(db, None, qr_data, ticket_event_id, steward_id, "wrong_event")
        return {
            "valid": False,
            "result": "wrong_event",
            "message": f"Ce billet est pour: {event.title}",
            "ticket": None,
            "holder": None,
            "pack_name": None,
            "event_id": ticket_event_id,
            "event_name": event.title
        }
    
    # ========== 3. RÉCUPÉRATION TICKET AVEC VERROUILLAGE ==========
    ticket_code = payload.get("ticket_code")
    ticket_id = payload.get("ticket_id")
    
    # Utiliser le ticket_code (plus fiable) ou ticket_id comme fallback
    ticket = None
    if ticket_code:
        ticket = db.query(Ticket).filter(
            Ticket.ticket_code == ticket_code
        ).with_for_update().first()
    
    if not ticket and ticket_id:
        ticket = db.query(Ticket).filter(
            Ticket.id == ticket_id
        ).with_for_update().first()

    if not ticket:
        logger.warning(f"Scan: Ticket non trouvé - code={ticket_code}, id={ticket_id}")
        log_scan(db, None, qr_data, ticket_event_id, steward_id, "invalid")
        return {
            "valid": False,
            "result": "invalid",
            "message": "Billet non trouvé dans le système",
            "ticket": None,
            "holder": None,
            "pack_name": None,
            "event_id": ticket_event_id,
            "event_name": event.title
        }
    
    # ========== 4. VÉRIFICATION STATUT DU TICKET ==========
    pack_name = payload.get("pack_name") or ticket.pack_name or "Standard"
    holder_name = ticket.holder_name or payload.get("holder") or "Invité"
    
    if ticket.status == "used":
        # Déjà utilisé - afficher l'heure du scan précédent
        scanned_time = ticket.scanned_at.strftime("%H:%M") if ticket.scanned_at else "heure inconnue"
        logger.info(f"Scan: Ticket déjà utilisé - {ticket_code} à {scanned_time}")
        log_scan(db, ticket.id, qr_data, ticket_event_id, steward_id, "already_used")
        return {
            "valid": False,
            "result": "already_used",
            "message": f"Billet déjà utilisé à {scanned_time}",
            "ticket": ticket,
            "holder": holder_name,
            "pack_name": pack_name,
            "event_id": ticket_event_id,
            "event_name": event.title
        }

    if ticket.status == "cancelled":
        # Annulé (remboursement)
        logger.info(f"Scan: Ticket annulé - {ticket_code}")
        log_scan(db, ticket.id, qr_data, ticket_event_id, steward_id, "cancelled")
        return {
            "valid": False,
            "result": "cancelled",
            "message": "Ce billet a été annulé",
            "ticket": ticket,
            "holder": holder_name,
            "pack_name": pack_name,
            "event_id": ticket_event_id,
            "event_name": event.title
        }

    if ticket.status == "expired":
        # Expiré manuellement
        logger.info(f"Scan: Ticket expiré - {ticket_code}")
        log_scan(db, ticket.id, qr_data, ticket_event_id, steward_id, "expired")
        return {
            "valid": False,
            "result": "expired",
            "message": "Ce billet a expiré",
            "ticket": ticket,
            "holder": holder_name,
            "pack_name": pack_name,
            "event_id": ticket_event_id,
            "event_name": event.title
        }
    
    # ========== 5. SUCCÈS - MARQUER COMME UTILISÉ ==========
    ticket.status = "used"
    ticket.scanned_at = datetime.utcnow()
    ticket.scanned_by = steward_id
    
    # Logger et commit
    log_scan(db, ticket.id, qr_data, ticket_event_id, steward_id, "success", auto_commit=False)
    
    try:
        db.commit()
    except Exception as e:
        logger.error(f"Erreur commit après scan réussi: {e}")
        db.rollback()
        return {
            "valid": False,
            "result": "error",
            "message": "Erreur technique, réessayez",
            "ticket": None,
            "holder": None,
            "pack_name": None,
            "event_id": ticket_event_id,
            "event_name": event.title
        }

    logger.info(f"✅ Scan réussi: {ticket_code} ({pack_name}) - {holder_name}")

    return {
        "valid": True,
        "result": "success",
        "message": f"✓ Entrée validée - {pack_name}",
        "ticket": ticket,
        "holder": holder_name,
        "pack_name": pack_name,
        "event_id": ticket_event_id,
        "event_name": event.title
    }


def get_ticket_info(qr_data: str, db: Session) -> Dict[str, Any]:
    """
    Récupère les informations d'un ticket sans le valider.
    Utile pour prévisualiser les infos avant le scan.
    
    Args:
        qr_data: Contenu du QR code (JWT)
        db: Session de base de données
    
    Returns:
        dict avec les informations du ticket
    """
    try:
        payload = decode_qr_jwt(qr_data)
        
        ticket_code = payload.get("ticket_code")
        ticket = db.query(Ticket).filter(Ticket.ticket_code == ticket_code).first()
        
        event = db.query(Event).filter(Event.id == payload.get("event_id")).first()
        
        return {
            "valid": True,
            "ticket_code": ticket_code,
            "ticket_id": payload.get("ticket_id"),
            "event_id": payload.get("event_id"),
            "event_name": event.title if event else payload.get("event_name"),
            "pack_name": payload.get("pack_name"),
            "holder": payload.get("holder"),
            "status": ticket.status if ticket else "unknown",
            "already_used": ticket.status == "used" if ticket else False,
            "scanned_at": ticket.scanned_at.isoformat() if ticket and ticket.scanned_at else None
        }
        
    except jwt.ExpiredSignatureError:
        return {"valid": False, "error": "expired", "message": "Billet expiré"}
    except jwt.InvalidTokenError:
        return {"valid": False, "error": "invalid", "message": "QR code invalide"}


def verify_jwt_signature(qr_data: str) -> bool:
    """
    Vérifie uniquement la signature du JWT sans valider l'expiration.
    Utile pour le debug.
    
    Args:
        qr_data: Le JWT à vérifier
    
    Returns:
        bool: True si la signature est valide
    """
    try:
        jwt.decode(
            qr_data,
            settings.jwt_secret_key,
            algorithms=["HS256"],
            options={"verify_exp": False}  # Ignorer l'expiration
        )
        return True
    except jwt.InvalidTokenError:
        return False
