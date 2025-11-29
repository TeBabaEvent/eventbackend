"""Routes pour les événements"""
from typing import List
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session, joinedload

from app.db.database import get_db
from app.db import models
from app.schemas import event as schemas
from app.api.deps import require_admin
from app.utils.serializers import serialize_event

router = APIRouter()


@router.get("/featured")
async def get_featured_events(
    limit: int = 3,
    db: Session = Depends(get_db)
):
    """Récupérer les événements à la une - Optimisé avec eager loading"""
    events = db.query(models.Event).options(
        joinedload(models.Event.artist_associations).joinedload(models.EventArtist.artist),
        joinedload(models.Event.pack_associations).joinedload(models.EventPack.pack)
    ).filter(
        models.Event.featured == True,
        models.Event.status == "upcoming"
    ).limit(limit).all()
    return [serialize_event(event) for event in events]


@router.get("")
async def get_events(
    skip: int = 0, 
    limit: int = 100,
    category: str = None,
    featured: bool = None,
    status: str = None,
    db: Session = Depends(get_db)
):
    """Récupérer la liste des événements avec filtres optionnels - Optimisé"""
    query = db.query(models.Event).options(
        joinedload(models.Event.artist_associations).joinedload(models.EventArtist.artist),
        joinedload(models.Event.pack_associations).joinedload(models.EventPack.pack)
    )
    
    if category:
        query = query.filter(models.Event.category == category)
    if featured is not None:
        query = query.filter(models.Event.featured == featured)
    if status:
        query = query.filter(models.Event.status == status)
    
    events = query.offset(skip).limit(limit).all()
    return [serialize_event(event) for event in events]


@router.get("/{event_id}")
async def get_event(event_id: str, db: Session = Depends(get_db)):
    """Récupérer un événement par son ID - Optimisé avec eager loading"""
    event = db.query(models.Event).options(
        joinedload(models.Event.artist_associations).joinedload(models.EventArtist.artist),
        joinedload(models.Event.pack_associations).joinedload(models.EventPack.pack)
    ).filter(models.Event.id == event_id).first()
    
    if not event:
        raise HTTPException(status_code=404, detail="Événement non trouvé")
    return serialize_event(event)


@router.post("", response_model=schemas.Event)
async def create_event(
    event: schemas.EventCreate,
    db: Session = Depends(get_db),
    _: None = Depends(require_admin)
):
    """Créer un nouvel événement (admin seulement)"""
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
    return serialize_event(db_event)


@router.put("/{event_id}")
async def update_event(
    event_id: str,
    event: schemas.EventUpdate,
    db: Session = Depends(get_db),
    _: None = Depends(require_admin)
):
    """Mettre à jour un événement (admin seulement)"""
    db_event = db.query(models.Event).filter(models.Event.id == event_id).first()
    if not db_event:
        raise HTTPException(status_code=404, detail="Événement non trouvé")
    
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
    return serialize_event(db_event)


@router.delete("/{event_id}")
async def delete_event(
    event_id: str,
    db: Session = Depends(get_db),
    _: None = Depends(require_admin)
):
    """Supprimer un événement (admin seulement)"""
    db_event = db.query(models.Event).filter(models.Event.id == event_id).first()
    if not db_event:
        raise HTTPException(status_code=404, detail="Événement non trouvé")
    
    db.delete(db_event)
    db.commit()
    return {"message": "Événement supprimé avec succès"}


@router.patch("/{event_id}/packs/{pack_id}/soldout")
async def toggle_pack_soldout(
    event_id: str,
    pack_id: str,
    is_soldout: bool,
    db: Session = Depends(get_db),
    _: None = Depends(require_admin)
):
    """Mettre à jour le statut soldout d'un pack pour un événement spécifique"""
    event_pack = db.query(models.EventPack).filter(
        models.EventPack.event_id == event_id,
        models.EventPack.pack_id == pack_id
    ).first()
    
    if not event_pack:
        raise HTTPException(status_code=404, detail="Association pack-événement non trouvée")
    
    event_pack.is_soldout = is_soldout
    db.commit()
    
    return {"message": f"Statut soldout mis à jour", "is_soldout": is_soldout}

