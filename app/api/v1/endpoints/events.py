"""Routes pour les événements"""
import logging
from typing import List
from datetime import date
from fastapi import APIRouter, Depends, HTTPException, status, Query, Path
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import asc, desc

from app.db.database import get_db
from app.db import models
from app.schemas import event as schemas
from app.api.deps import require_admin
from app.utils.serializers import serialize_event

logger = logging.getLogger(__name__)

router = APIRouter()


def get_today_str() -> str:
    """Retourne la date d'aujourd'hui au format YYYY-MM-DD"""
    return date.today().isoformat()


# ✅ OPTIMISATION: auto_update_past_events() a été déplacé vers le scheduler CRON
# Voir app/services/scheduler.py - job_update_past_events()
# Exécuté automatiquement tous les jours à 00:05 au lieu de chaque requête


@router.get("/upcoming")
def get_upcoming_events(
    limit: int = Query(10, ge=1, le=50, description="Nombre maximum d'événements à retourner"),
    db: Session = Depends(get_db)
):
    """
    Récupérer les événements à venir (date >= aujourd'hui), triés par date.
    Utilisé pour le site public (Hero, EventsSection).
    L'événement reste visible jusqu'à 23:59 le jour même, disparaît le lendemain à 00:00.
    """
    today = get_today_str()
    events = db.query(models.Event).options(
        joinedload(models.Event.artist_associations).joinedload(models.EventArtist.artist),
        joinedload(models.Event.pack_associations).joinedload(models.EventPack.pack)
    ).filter(
        models.Event.status == "upcoming",
        models.Event.date >= today  # >= inclut le jour même
    ).order_by(asc(models.Event.date)).limit(limit).all()

    return [serialize_event(event) for event in events]


@router.get("/past")
def get_past_events(
    limit: int = Query(12, ge=1, le=100, description="Nombre d'événements par page"),
    offset: int = Query(0, ge=0, description="Décalage pour la pagination"),
    db: Session = Depends(get_db)
):
    """
    Récupérer les événements passés (date < aujourd'hui), triés du plus récent au plus ancien.
    Utilisé pour la section "Historique" du site public.
    Supporte la pagination avec limit et offset.
    
    Returns:
        dict avec items, total, has_more pour la pagination infinie
    """
    today = get_today_str()
    
    # Query de base pour les événements passés
    base_query = db.query(models.Event).filter(models.Event.date < today)
    
    # Compter le total pour la pagination
    total = base_query.count()
    
    # Récupérer les événements paginés
    events = base_query.options(
        joinedload(models.Event.artist_associations).joinedload(models.EventArtist.artist),
        joinedload(models.Event.pack_associations).joinedload(models.EventPack.pack)
    ).order_by(desc(models.Event.date)).offset(offset).limit(limit).all()

    return {
        "items": [serialize_event(event) for event in events],
        "total": total,
        "offset": offset,
        "limit": limit,
        "has_more": offset + len(events) < total
    }


@router.get("")
def get_events(
    skip: int = Query(0, ge=0, description="Nombre d'éléments à sauter"),
    limit: int = Query(100, ge=1, le=500, description="Nombre maximum d'événements"),
    category: str = Query(None, description="Filtrer par catégorie (concert, festival, party, wedding)"),
    event_status: str = Query(None, alias="status", description="Filtrer par statut (upcoming, past, cancelled)"),
    upcoming_only: bool = Query(False, description="Ne retourner que les événements à venir"),
    db: Session = Depends(get_db)
):
    """
    Récupérer la liste des événements avec filtres optionnels - Optimisé.
    Pour le dashboard admin, retourne tous les événements.
    """
    query = db.query(models.Event).options(
        joinedload(models.Event.artist_associations).joinedload(models.EventArtist.artist),
        joinedload(models.Event.pack_associations).joinedload(models.EventPack.pack)
    )
    
    if category:
        query = query.filter(models.Event.category == category)
    if event_status:
        query = query.filter(models.Event.status == event_status)
    
    # Filtre pour n'avoir que les événements à venir (date > aujourd'hui)
    if upcoming_only:
        today = get_today_str()
        query = query.filter(
            models.Event.status == "upcoming",
            models.Event.date > today
        )
    
    # Toujours trier par date
    events = query.order_by(asc(models.Event.date)).offset(skip).limit(limit).all()
    return [serialize_event(event) for event in events]


@router.get("/{event_id}")
def get_event(
    event_id: str = Path(..., description="ID de l'événement (UUID)", min_length=36, max_length=36),
    db: Session = Depends(get_db)
):
    """Récupérer un événement par son ID - Optimisé avec eager loading"""
    event = db.query(models.Event).options(
        joinedload(models.Event.artist_associations).joinedload(models.EventArtist.artist),
        joinedload(models.Event.pack_associations).joinedload(models.EventPack.pack)
    ).filter(models.Event.id == event_id).first()
    
    if not event:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Événement non trouvé")
    return serialize_event(event)


@router.post("", response_model=schemas.Event, status_code=status.HTTP_201_CREATED)
def create_event(
    event: schemas.EventCreate,
    db: Session = Depends(get_db),
    _: None = Depends(require_admin)
):
    """Créer un nouvel événement (admin seulement)"""
    try:
        # Extraire les artistes et packs
        artists_info = event.artists
        packs_info = event.packs
        
        # Créer l'événement sans les relations
        event_data = event.model_dump(exclude={"artists", "packs"})
        db_event = models.Event(**event_data)
        
        # Ajouter l'événement d'abord pour avoir l'ID
        db.add(db_event)
        db.flush()
        
        # Ajouter les artistes avec leurs infos
        if artists_info:
            for artist_info in artists_info:
                artist = db.query(models.Artist).filter(models.Artist.id == artist_info.artist_id).first()
                if artist:
                    event_artist = models.EventArtist(
                        event_id=db_event.id,
                        artist_id=artist_info.artist_id,
                        start_time=artist_info.start_time,
                        end_time=artist_info.end_time,
                        order=artist_info.order
                    )
                    db.add(event_artist)
        
        # Ajouter les packs avec leur statut
        if packs_info:
            for pack_info in packs_info:
                pack = db.query(models.Pack).filter(models.Pack.id == pack_info.pack_id).first()
                if pack:
                    event_pack = models.EventPack(
                        event_id=db_event.id,
                        pack_id=pack_info.pack_id,
                        is_soldout=pack_info.is_soldout
                    )
                    db.add(event_pack)
        
        db.commit()
        db.refresh(db_event)
        logger.info(f"✨ Event created: {db_event.title} (ID: {db_event.id})")
        return serialize_event(db_event)
    except Exception as e:
        db.rollback()
        logger.error(f"❌ Error creating event: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Erreur lors de la création de l'événement"
        )


@router.put("/{event_id}")
def update_event(
    event_id: str = Path(..., description="ID de l'événement (UUID)", min_length=36, max_length=36),
    event: schemas.EventUpdate = ...,
    db: Session = Depends(get_db),
    _: None = Depends(require_admin)
):
    """Mettre à jour un événement (admin seulement)"""
    db_event = db.query(models.Event).filter(models.Event.id == event_id).first()
    if not db_event:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Événement non trouvé")
    
    try:
        # Extraire les artistes et packs
        artists_info = event.artists
        packs_info = event.packs
        
        # Mettre à jour les champs simples
        for key, value in event.model_dump(exclude_unset=True, exclude={"artists", "packs"}).items():
            setattr(db_event, key, value)
        
        # Mettre à jour les artistes si fournis
        if artists_info is not None:
            # Supprimer les anciennes associations
            db.query(models.EventArtist).filter(models.EventArtist.event_id == event_id).delete()
            
            # Créer les nouvelles
            for artist_info in artists_info:
                artist = db.query(models.Artist).filter(models.Artist.id == artist_info.artist_id).first()
                if artist:
                    event_artist = models.EventArtist(
                        event_id=event_id,
                        artist_id=artist_info.artist_id,
                        start_time=artist_info.start_time,
                        end_time=artist_info.end_time,
                        order=artist_info.order
                    )
                    db.add(event_artist)
        
        # Mettre à jour les packs si fournis
        if packs_info is not None:
            # Supprimer les anciennes associations
            db.query(models.EventPack).filter(models.EventPack.event_id == event_id).delete()
            
            # Créer les nouvelles
            for pack_info in packs_info:
                pack = db.query(models.Pack).filter(models.Pack.id == pack_info.pack_id).first()
                if pack:
                    event_pack = models.EventPack(
                        event_id=event_id,
                        pack_id=pack_info.pack_id,
                        is_soldout=pack_info.is_soldout
                    )
                    db.add(event_pack)
        
        db.commit()
        db.refresh(db_event)
        logger.info(f"📝 Event updated: {db_event.title} (ID: {event_id})")
        return serialize_event(db_event)
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"❌ Error updating event {event_id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Erreur lors de la mise à jour de l'événement"
        )


@router.delete("/{event_id}")
def delete_event(
    event_id: str = Path(..., description="ID de l'événement (UUID)", min_length=36, max_length=36),
    db: Session = Depends(get_db),
    _: None = Depends(require_admin)
):
    """Supprimer un événement (admin seulement)"""
    db_event = db.query(models.Event).filter(models.Event.id == event_id).first()
    if not db_event:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Événement non trouvé")
    
    try:
        event_title = db_event.title
        db.delete(db_event)
        db.commit()
        logger.info(f"🗑️ Event deleted: {event_title} (ID: {event_id})")
        return {"message": "Événement supprimé avec succès"}
    except Exception as e:
        db.rollback()
        logger.error(f"❌ Error deleting event {event_id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Erreur lors de la suppression de l'événement"
        )


@router.patch("/{event_id}/packs/{pack_id}/soldout")
def toggle_pack_soldout(
    event_id: str = Path(..., description="ID de l'événement (UUID)", min_length=36, max_length=36),
    pack_id: str = Path(..., description="ID du pack (UUID)", min_length=36, max_length=36),
    is_soldout: bool = Query(..., description="Nouveau statut soldout"),
    db: Session = Depends(get_db),
    _: None = Depends(require_admin)
):
    """Mettre à jour le statut soldout d'un pack pour un événement spécifique"""
    event_pack = db.query(models.EventPack).filter(
        models.EventPack.event_id == event_id,
        models.EventPack.pack_id == pack_id
    ).first()
    
    if not event_pack:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Association pack-événement non trouvée")
    
    try:
        event_pack.is_soldout = is_soldout
        db.commit()
        logger.info(f"📦 Pack soldout status updated: event={event_id}, pack={pack_id}, soldout={is_soldout}")
        return {"message": "Statut soldout mis à jour", "is_soldout": is_soldout}
    except Exception as e:
        db.rollback()
        logger.error(f"❌ Error updating pack soldout status: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Erreur lors de la mise à jour du statut"
        )

