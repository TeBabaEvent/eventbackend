"""Schémas pour les artistes"""
from typing import Optional
from datetime import datetime
from pydantic import BaseModel


class EventArtistInfo(BaseModel):
    """Informations d'association Event-Artist"""
    artist_id: str
    start_time: Optional[str] = None
    end_time: Optional[str] = None
    order: int = 0


class ArtistBase(BaseModel):
    name: str
    role: Optional[str] = None
    role_translations: Optional[dict] = None  # {"fr": "", "en": "", "nl": "", "sq": ""}
    description: Optional[str] = None
    description_translations: Optional[dict] = None  # {"fr": "", "en": "", "nl": "", "sq": ""}
    image_url: Optional[str] = None
    events_count: Optional[int] = 0
    badge: Optional[str] = None
    instagram: Optional[str] = None
    show_on_website: Optional[bool] = True


class ArtistCreate(ArtistBase):
    pass


class ArtistUpdate(BaseModel):
    name: Optional[str] = None
    role: Optional[str] = None
    role_translations: Optional[dict] = None
    description: Optional[str] = None
    description_translations: Optional[dict] = None
    image_url: Optional[str] = None
    events_count: Optional[int] = None
    badge: Optional[str] = None
    instagram: Optional[str] = None
    show_on_website: Optional[bool] = None


class Artist(ArtistBase):
    id: str
    created_at: datetime
    updated_at: Optional[datetime] = None
    
    class Config:
        from_attributes = True


class ArtistWithTiming(Artist):
    """Artiste avec infos de timing pour un événement spécifique"""
    start_time: Optional[str] = None
    end_time: Optional[str] = None
    order: Optional[int] = None


class ArtistList(BaseModel):
    """Version simplifiée pour les listes"""
    id: str
    name: str
    role: Optional[str]
    image_url: Optional[str]
    
    class Config:
        from_attributes = True

