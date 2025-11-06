"""Schémas pour les packs"""
from typing import Optional, List
from datetime import datetime
from pydantic import BaseModel


class EventPackInfo(BaseModel):
    """Informations d'association Event-Pack"""
    pack_id: str
    is_soldout: bool = False


class PackBase(BaseModel):
    name: str
    name_translations: Optional[dict] = None  # {"fr": "", "en": "", "nl": "", "sq": ""}
    type: str  # standard, premium, vip
    description: Optional[str] = None
    description_translations: Optional[dict] = None  # {"fr": "", "en": "", "nl": "", "sq": ""}
    price: float
    currency: str = "€"
    unit: Optional[str] = None
    features: Optional[List[str]] = None  # Liste des features
    features_translations: Optional[dict] = None  # {"fr": [], "en": [], "nl": [], "sq": []}
    is_active: bool = True


class PackCreate(PackBase):
    pass


class PackUpdate(BaseModel):
    name: Optional[str] = None
    name_translations: Optional[dict] = None
    type: Optional[str] = None
    description: Optional[str] = None
    description_translations: Optional[dict] = None
    price: Optional[float] = None
    currency: Optional[str] = None
    unit: Optional[str] = None
    features: Optional[List[str]] = None
    features_translations: Optional[dict] = None
    is_active: Optional[bool] = None


class Pack(PackBase):
    id: str
    created_at: datetime
    updated_at: Optional[datetime] = None
    
    class Config:
        from_attributes = True


class PackWithStatus(Pack):
    """Pack avec statut soldout pour un événement spécifique"""
    is_soldout: Optional[bool] = None


class PackList(BaseModel):
    """Version simplifiée pour les listes"""
    id: str
    name: str
    type: str
    price: float
    currency: str
    
    class Config:
        from_attributes = True

