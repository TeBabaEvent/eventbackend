"""Routes pour les packs"""
from typing import List
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.db import models
from app.schemas import pack as schemas
from app.api.deps import require_admin

router = APIRouter()


@router.get("", response_model=List[schemas.Pack])
async def get_packs(
    skip: int = 0, 
    limit: int = 100,
    active_only: bool = True,
    db: Session = Depends(get_db)
):
    """Récupérer la liste des packs"""
    query = db.query(models.Pack)
    if active_only:
        query = query.filter(models.Pack.is_active == True)
    packs = query.offset(skip).limit(limit).all()
    return packs


@router.get("/{pack_id}", response_model=schemas.Pack)
async def get_pack(pack_id: str, db: Session = Depends(get_db)):
    """Récupérer un pack par son ID"""
    pack = db.query(models.Pack).filter(models.Pack.id == pack_id).first()
    if not pack:
        raise HTTPException(status_code=404, detail="Pack non trouvé")
    return pack


@router.post("", response_model=schemas.Pack)
async def create_pack(
    pack: schemas.PackCreate,
    db: Session = Depends(get_db),
    _: None = Depends(require_admin)
):
    """Créer un nouveau pack (admin seulement)"""
    db_pack = models.Pack(**pack.model_dump())
    db.add(db_pack)
    db.commit()
    db.refresh(db_pack)
    return db_pack


@router.put("/{pack_id}", response_model=schemas.Pack)
async def update_pack(
    pack_id: str,
    pack: schemas.PackUpdate,
    db: Session = Depends(get_db),
    _: None = Depends(require_admin)
):
    """Mettre à jour un pack (admin seulement)"""
    db_pack = db.query(models.Pack).filter(models.Pack.id == pack_id).first()
    if not db_pack:
        raise HTTPException(status_code=404, detail="Pack non trouvé")
    
    for key, value in pack.model_dump(exclude_unset=True).items():
        setattr(db_pack, key, value)
    
    db.commit()
    db.refresh(db_pack)
    return db_pack


@router.delete("/{pack_id}")
async def delete_pack(
    pack_id: str,
    db: Session = Depends(get_db),
    _: None = Depends(require_admin)
):
    """Supprimer un pack (admin seulement)"""
    db_pack = db.query(models.Pack).filter(models.Pack.id == pack_id).first()
    if not db_pack:
        raise HTTPException(status_code=404, detail="Pack non trouvé")
    
    db.delete(db_pack)
    db.commit()
    return {"message": "Pack supprimé avec succès"}

