"""Routes pour les artistes"""
from typing import List
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.db import models
from app.schemas import artist as schemas
from app.api.deps import require_admin

router = APIRouter()


@router.get("", response_model=List[schemas.Artist])
async def get_artists(
    skip: int = 0, 
    limit: int = 100,
    db: Session = Depends(get_db)
):
    """Récupérer la liste des artistes"""
    artists = db.query(models.Artist).offset(skip).limit(limit).all()
    return artists


@router.get("/{artist_id}", response_model=schemas.Artist)
async def get_artist(artist_id: str, db: Session = Depends(get_db)):
    """Récupérer un artiste par son ID"""
    artist = db.query(models.Artist).filter(models.Artist.id == artist_id).first()
    if not artist:
        raise HTTPException(status_code=404, detail="Artiste non trouvé")
    return artist


@router.post("", response_model=schemas.Artist)
async def create_artist(
    artist: schemas.ArtistCreate,
    db: Session = Depends(get_db),
    _: None = Depends(require_admin)
):
    """Créer un nouveau artiste (admin seulement)"""
    db_artist = models.Artist(**artist.model_dump())
    db.add(db_artist)
    db.commit()
    db.refresh(db_artist)
    return db_artist


@router.put("/{artist_id}", response_model=schemas.Artist)
async def update_artist(
    artist_id: str,
    artist: schemas.ArtistUpdate,
    db: Session = Depends(get_db),
    _: None = Depends(require_admin)
):
    """Mettre à jour un artiste (admin seulement)"""
    db_artist = db.query(models.Artist).filter(models.Artist.id == artist_id).first()
    if not db_artist:
        raise HTTPException(status_code=404, detail="Artiste non trouvé")
    
    for key, value in artist.model_dump(exclude_unset=True).items():
        setattr(db_artist, key, value)
    
    db.commit()
    db.refresh(db_artist)
    return db_artist


@router.delete("/{artist_id}")
async def delete_artist(
    artist_id: str,
    db: Session = Depends(get_db),
    _: None = Depends(require_admin)
):
    """Supprimer un artiste (admin seulement)"""
    db_artist = db.query(models.Artist).filter(models.Artist.id == artist_id).first()
    if not db_artist:
        raise HTTPException(status_code=404, detail="Artiste non trouvé")
    
    db.delete(db_artist)
    db.commit()
    return {"message": "Artiste supprimé avec succès"}

