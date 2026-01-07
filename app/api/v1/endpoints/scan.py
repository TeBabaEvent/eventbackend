"""Routes pour la validation des tickets (scan) - Rate Limited"""
from fastapi import APIRouter, HTTPException, Depends, Request, status, Query, Path
from pydantic import BaseModel
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import func
from typing import Optional
import logging

from app.db.database import get_db
from app.db import models
from app.services.scan_service import validate_ticket_scan
from app.api.deps import require_steward
from app.core.rate_limiter import limiter, RATE_LIMITS

logger = logging.getLogger(__name__)
router = APIRouter()


class ScanRequest(BaseModel):
    """Demande de validation de scan"""
    qr_data: str  # Contenu du QR code (JWT)
    event_id: Optional[str] = None  # ID de l'événement (optionnel, détecté depuis le QR)


class ScanResponse(BaseModel):
    """Réponse de validation de scan"""
    valid: bool
    result: str  # success, already_used, invalid, cancelled, expired, wrong_event, error
    message: str
    holder: Optional[str] = None
    ticket_code: Optional[str] = None
    pack_name: Optional[str] = None  # Type de ticket (VIP, Standard, etc.)
    scanned_at: Optional[str] = None
    event_id: Optional[str] = None  # ID de l'événement détecté depuis le QR
    event_name: Optional[str] = None  # Nom de l'événement détecté


@router.post(
    "/validate",
    response_model=ScanResponse,
    status_code=status.HTTP_200_OK,
    responses={
        403: {"description": "Access restricted to stewards and admins"},
        429: {"description": "Rate limit exceeded"}
    }
)
@limiter.limit(RATE_LIMITS["scan"])  # 10 scans per second for quick scanning
def validate_scan(
    request_obj: Request,
    request: ScanRequest,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_steward)  # Injection de dépendance pour le contrôle d'accès
):
    """
    Valide un scan de ticket.

    Endpoint utilisé par l'application steward pour valider les entrées.
    L'event_id est automatiquement détecté depuis le QR code (JWT).

    Vérifie:
    - JWT valide et non expiré
    - Ticket non utilisé
    - Ticket non annulé

    Args:
        request: QR data (event_id optionnel)
        db: Session de base de données
        current_user: Utilisateur authentifié (steward/admin via require_steward)

    Returns:
        ScanResponse avec résultat de la validation
    """

    # Valider le scan (l'event_id est extrait du JWT automatiquement)
    result = validate_ticket_scan(
        qr_data=request.qr_data,
        steward_id=current_user.id,
        db=db,
        event_id=request.event_id  # Optionnel, pour vérification croisée si fourni
    )

    logger.info(
        f"Scan par {current_user.username}: {result['result']} - "
        f"Event: {result.get('event_id', 'unknown')}"
    )

    # Préparer la réponse
    response = ScanResponse(
        valid=result["valid"],
        result=result["result"],
        message=result["message"],
        holder=result.get("holder"),
        pack_name=result.get("pack_name"),
        event_id=result.get("event_id"),
        event_name=result.get("event_name")
    )

    if result.get("ticket"):
        ticket = result["ticket"]
        response.ticket_code = ticket.ticket_code
        # Fallback pour pack_name si non dans le résultat
        if not response.pack_name and ticket.pack_name:
            response.pack_name = ticket.pack_name
        if ticket.scanned_at:
            response.scanned_at = ticket.scanned_at.isoformat()

    return response


@router.get("/history")
def get_scan_history(
    event_id: Optional[str] = Query(None, description="Filtrer par ID d'événement (UUID)"),
    limit: int = Query(50, ge=1, le=200, description="Nombre maximum de résultats"),
    offset: int = Query(0, ge=0, description="Décalage pour la pagination"),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_steward)  # Injection de dépendance pour le contrôle d'accès
):
    """
    Récupère l'historique des scans.

    Args:
        event_id: Filtrer par événement (optionnel)
        limit: Nombre max de résultats (défaut: 50)
        offset: Décalage pour pagination (défaut: 0)
        db: Session de base de données
        current_user: Utilisateur authentifié (via require_steward)

    Returns:
        dict avec scans et total

    Note:
        - Stewards: Voient uniquement leurs scans
        - Admins: Voient tous les scans
    """

    # Construire la requête
    query = db.query(models.ScanLog)

    # Filtrer par événement si spécifié
    if event_id:
        query = query.filter(models.ScanLog.event_id == event_id)

    # Si steward, montrer uniquement ses scans
    if current_user.role == "steward":
        query = query.filter(models.ScanLog.steward_id == current_user.id)

    # Compter le total
    total = query.count()

    # ✅ Eager loading pour éviter N+1 queries
    scans = query.options(
        joinedload(models.ScanLog.ticket),
        joinedload(models.ScanLog.event),
        joinedload(models.ScanLog.steward)
    ).order_by(
        models.ScanLog.scanned_at.desc()
    ).limit(limit).offset(offset).all()

    # Formater les résultats (les relations sont déjà chargées)
    results = []
    for scan in scans:
        results.append({
            "id": scan.id,
            "ticket_code": scan.ticket.ticket_code if scan.ticket else None,
            "holder": scan.ticket.holder_name if scan.ticket else None,
            "event_id": scan.event_id,
            "event_name": scan.event.title if scan.event else None,
            "result": scan.result,
            "scanned_at": scan.scanned_at.isoformat() if scan.scanned_at else None,
            "steward_name": scan.steward.name if scan.steward else None
        })

    return {
        "scans": results,
        "total": total,
        "limit": limit,
        "offset": offset
    }


@router.get("/stats/{event_id}")
def get_scan_stats(
    event_id: str = Path(..., description="ID de l'événement (UUID)", min_length=36, max_length=36),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_steward)  # Injection de dépendance pour le contrôle d'accès
):
    """
    Récupère les statistiques de scan pour un événement.

    Args:
        event_id: ID de l'événement
        db: Session de base de données
        current_user: Utilisateur authentifié (via require_steward)

    Returns:
        dict avec statistiques d'entrées

    Raises:
        HTTPException 404: Si l'événement n'existe pas
    """

    # Vérifier que l'événement existe
    event = db.query(models.Event).filter(models.Event.id == event_id).first()
    if not event:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Événement non trouvé")

    # Compter le total de tickets pour cet événement
    total_tickets = db.query(models.Ticket).filter(
        models.Ticket.event_id == event_id
    ).count()

    # Compter les tickets scannés (status = used)
    scanned_tickets = db.query(models.Ticket).filter(
        models.Ticket.event_id == event_id,
        models.Ticket.status == "used"
    ).count()

    # Calculer le taux de scan
    scan_rate = (scanned_tickets / total_tickets * 100) if total_tickets > 0 else 0

    # Compter les scans par résultat
    scan_results = db.query(
        models.ScanLog.result,
        func.count(models.ScanLog.id).label('count')
    ).filter(
        models.ScanLog.event_id == event_id
    ).group_by(models.ScanLog.result).all()

    results_by_type = {result: count for result, count in scan_results}

    # Scans par heure (optionnel - pour graphiques)
    # Grouper par heure dans la journée
    scans_by_hour = db.query(
        func.hour(models.ScanLog.scanned_at).label('hour'),
        func.count(models.ScanLog.id).label('count')
    ).filter(
        models.ScanLog.event_id == event_id,
        models.ScanLog.result == "success"
    ).group_by('hour').all()

    scans_by_hour_dict = {hour: count for hour, count in scans_by_hour if hour is not None}

    return {
        "event_id": event_id,
        "event_name": event.title,
        "total_tickets": total_tickets,
        "scanned_tickets": scanned_tickets,
        "scan_rate": round(scan_rate, 2),
        "results_by_type": results_by_type,
        "scans_by_hour": scans_by_hour_dict,
        "success_count": results_by_type.get("success", 0),
        "already_used_count": results_by_type.get("already_used", 0),
        "invalid_count": results_by_type.get("invalid", 0)
    }
