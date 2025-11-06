"""Schémas pour les événements"""
from typing import Optional, List
from datetime import datetime
from pydantic import BaseModel

from app.schemas.artist import ArtistWithTiming, EventArtistInfo
from app.schemas.pack import PackWithStatus, EventPackInfo


class EventBase(BaseModel):
    title: str
    title_translations: Optional[dict] = None  # {"fr": "", "en": "", "nl": "", "sq": ""}
    description: str
    description_translations: Optional[dict] = None  # {"fr": "", "en": "", "nl": "", "sq": ""}
    category: str  # concert, festival, party, wedding
    date: str  # Format: YYYY-MM-DD
    time: str  # Format: HH:MM
    location: str
    address: Optional[str] = None
    city: str
    maps_embed_url: Optional[str] = None
    image_url: Optional[str] = None
    capacity: Optional[int] = None
    featured: bool = False
    status: str = "upcoming"


class EventCreate(EventBase):
    artists: Optional[List[EventArtistInfo]] = []
    packs: Optional[List[EventPackInfo]] = []


class EventUpdate(BaseModel):
    title: Optional[str] = None
    title_translations: Optional[dict] = None
    description: Optional[str] = None
    description_translations: Optional[dict] = None
    category: Optional[str] = None
    date: Optional[str] = None
    time: Optional[str] = None
    location: Optional[str] = None
    address: Optional[str] = None
    city: Optional[str] = None
    maps_embed_url: Optional[str] = None
    image_url: Optional[str] = None
    capacity: Optional[int] = None
    featured: Optional[bool] = None
    status: Optional[str] = None
    artists: Optional[List[EventArtistInfo]] = None
    packs: Optional[List[EventPackInfo]] = None


class Event(EventBase):
    id: str
    title_translations: Optional[dict] = None
    description_translations: Optional[dict] = None
    created_at: datetime
    updated_at: Optional[datetime] = None
    artists: List[ArtistWithTiming] = []
    packs: List[PackWithStatus] = []
    
    class Config:
        from_attributes = True


class EventList(BaseModel):
    """Version simplifiée pour les listes"""
    id: str
    title: str
    category: str
    date: str
    time: str
    location: str
    city: str
    image_url: Optional[str] = None
    featured: bool
    status: str
    
    class Config:
        from_attributes = True

