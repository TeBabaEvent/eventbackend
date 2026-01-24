"""Routes pour les artistes"""
import logging
from typing import List
from fastapi import APIRouter, Depends, HTTPException, status, Query, Path
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.db import models
from app.schemas import artist as schemas
from app.api.deps import require_admin
from app.services.image_service import get_image_service

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("", response_model=List[schemas.Artist])
def get_artists(
    skip: int = Query(0, ge=0, description="Nombre d'éléments à sauter"),
    limit: int = Query(100, ge=1, le=500, description="Nombre maximum d'artistes"),
    db: Session = Depends(get_db)
):
    """Récupérer la liste des artistes"""
    artists = db.query(models.Artist).offset(skip).limit(limit).all()
    return artists


@router.get("/{artist_id}", response_model=schemas.Artist)
def get_artist(
    artist_id: str = Path(..., description="ID de l'artiste (UUID)", min_length=36, max_length=36),
    db: Session = Depends(get_db)
):
    """Récupérer un artiste par son ID"""
    artist = db.query(models.Artist).filter(models.Artist.id == artist_id).first()
    if not artist:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Artiste non trouvé")
    return artist


@router.post("", response_model=schemas.Artist, status_code=status.HTTP_201_CREATED)
def create_artist(
    artist: schemas.ArtistCreate,
    db: Session = Depends(get_db),
    _: None = Depends(require_admin)
):
    """Créer un nouveau artiste (admin seulement)"""
    try:
        db_artist = models.Artist(**artist.model_dump())
        db.add(db_artist)
        db.commit()
        db.refresh(db_artist)
        logger.info(f"✨ Artist created: {db_artist.name} (ID: {db_artist.id})")
        return db_artist
    except Exception as e:
        db.rollback()
        logger.error(f"❌ Error creating artist: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Erreur lors de la création de l'artiste"
        )


@router.put("/{artist_id}", response_model=schemas.Artist)
def update_artist(
    artist_id: str = Path(..., description="ID de l'artiste (UUID)", min_length=36, max_length=36),
    artist: schemas.ArtistUpdate = ...,
    db: Session = Depends(get_db),
    _: None = Depends(require_admin)
):
    """Mettre à jour un artiste (admin seulement)"""
    db_artist = db.query(models.Artist).filter(models.Artist.id == artist_id).first()
    if not db_artist:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Artiste non trouvé")
    
    try:
        for key, value in artist.model_dump(exclude_unset=True).items():
            setattr(db_artist, key, value)
        
        db.commit()
        db.refresh(db_artist)
        logger.info(f"📝 Artist updated: {db_artist.name} (ID: {artist_id})")
        return db_artist
    except Exception as e:
        db.rollback()
        logger.error(f"❌ Error updating artist {artist_id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Erreur lors de la mise à jour de l'artiste"
        )


@router.delete("/{artist_id}")
async def delete_artist(
    artist_id: str = Path(..., description="ID de l'artiste (UUID)", min_length=36, max_length=36),
    db: Session = Depends(get_db),
    _: None = Depends(require_admin)
):
    """Supprimer un artiste (admin seulement)"""
    db_artist = db.query(models.Artist).filter(models.Artist.id == artist_id).first()
    if not db_artist:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Artiste non trouvé")

    try:
        artist_name = db_artist.name

        # Delete associated image file if it exists and is local
        if db_artist.image_url:
            image_service = get_image_service()
            if image_service.is_local_image(db_artist.image_url):
                deleted = await image_service.delete(db_artist.image_url)
                if deleted:
                    logger.info(f"🖼️ Image deleted for artist {artist_id}")

        db.delete(db_artist)
        db.commit()
        logger.info(f"🗑️ Artist deleted: {artist_name} (ID: {artist_id})")
        return {"message": "Artiste supprimé avec succès"}
    except Exception as e:
        db.rollback()
        logger.error(f"❌ Error deleting artist {artist_id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Erreur lors de la suppression de l'artiste"
        )

