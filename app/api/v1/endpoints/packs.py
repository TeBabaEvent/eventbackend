"""Routes pour les packs"""
import logging
from typing import List
from fastapi import APIRouter, Depends, HTTPException, status, Query, Path
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.db import models
from app.schemas import pack as schemas
from app.api.deps import require_admin

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("", response_model=List[schemas.Pack])
def get_packs(
    skip: int = Query(0, ge=0, description="Nombre d'éléments à sauter"),
    limit: int = Query(100, ge=1, le=500, description="Nombre maximum de packs"),
    active_only: bool = Query(True, description="Ne retourner que les packs actifs"),
    db: Session = Depends(get_db)
):
    """Récupérer la liste des packs"""
    query = db.query(models.Pack)
    if active_only:
        query = query.filter(models.Pack.is_active == True)
    packs = query.offset(skip).limit(limit).all()
    return packs


@router.get("/{pack_id}", response_model=schemas.Pack)
def get_pack(
    pack_id: str = Path(..., description="ID du pack (UUID)", min_length=36, max_length=36),
    db: Session = Depends(get_db)
):
    """Récupérer un pack par son ID"""
    pack = db.query(models.Pack).filter(models.Pack.id == pack_id).first()
    if not pack:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Pack non trouvé")
    return pack


@router.post("", response_model=schemas.Pack, status_code=status.HTTP_201_CREATED)
def create_pack(
    pack: schemas.PackCreate,
    db: Session = Depends(get_db),
    _: None = Depends(require_admin)
):
    """Créer un nouveau pack (admin seulement)"""
    try:
        db_pack = models.Pack(**pack.model_dump())
        db.add(db_pack)
        db.commit()
        db.refresh(db_pack)
        logger.info(f"✨ Pack created: {db_pack.name} (ID: {db_pack.id})")
        return db_pack
    except Exception as e:
        db.rollback()
        logger.error(f"❌ Error creating pack: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Erreur lors de la création du pack"
        )


@router.put("/{pack_id}", response_model=schemas.Pack)
def update_pack(
    pack_id: str = Path(..., description="ID du pack (UUID)", min_length=36, max_length=36),
    pack: schemas.PackUpdate = ...,
    db: Session = Depends(get_db),
    _: None = Depends(require_admin)
):
    """Mettre à jour un pack (admin seulement)"""
    db_pack = db.query(models.Pack).filter(models.Pack.id == pack_id).first()
    if not db_pack:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Pack non trouvé")
    
    try:
        for key, value in pack.model_dump(exclude_unset=True).items():
            setattr(db_pack, key, value)
        
        db.commit()
        db.refresh(db_pack)
        logger.info(f"📝 Pack updated: {db_pack.name} (ID: {pack_id})")
        return db_pack
    except Exception as e:
        db.rollback()
        logger.error(f"❌ Error updating pack {pack_id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Erreur lors de la mise à jour du pack"
        )


@router.delete("/{pack_id}")
def delete_pack(
    pack_id: str = Path(..., description="ID du pack (UUID)", min_length=36, max_length=36),
    db: Session = Depends(get_db),
    _: None = Depends(require_admin)
):
    """Supprimer un pack (admin seulement)"""
    db_pack = db.query(models.Pack).filter(models.Pack.id == pack_id).first()
    if not db_pack:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Pack non trouvé")
    
    try:
        pack_name = db_pack.name
        db.delete(db_pack)
        db.commit()
        logger.info(f"🗑️ Pack deleted: {pack_name} (ID: {pack_id})")
        return {"message": "Pack supprimé avec succès"}
    except Exception as e:
        db.rollback()
        logger.error(f"❌ Error deleting pack {pack_id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Erreur lors de la suppression du pack"
        )

