"""Modèles SQLAlchemy"""
from sqlalchemy import Column, String, DateTime, Integer, Text, Float, Boolean, ForeignKey, JSON
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
import uuid

from app.db.database import Base


class EventArtist(Base):
    """Association Event-Artist avec informations spécifiques"""
    __tablename__ = "event_artists"
    
    event_id = Column(String(36), ForeignKey('events.id', ondelete='CASCADE'), primary_key=True)
    artist_id = Column(String(36), ForeignKey('artists.id', ondelete='CASCADE'), primary_key=True)
    start_time = Column(String(10), nullable=True)  # Heure de début du set
    end_time = Column(String(10), nullable=True)    # Heure de fin du set
    order = Column(Integer, default=0)              # Ordre de passage (0 = premier, 1 = deuxième, etc.)
    
    # Relations
    event = relationship("Event", back_populates="artist_associations")
    artist = relationship("Artist", back_populates="event_associations")


class EventPack(Base):
    """Association Event-Pack avec statut"""
    __tablename__ = "event_packs"
    
    event_id = Column(String(36), ForeignKey('events.id', ondelete='CASCADE'), primary_key=True)
    pack_id = Column(String(36), ForeignKey('packs.id', ondelete='CASCADE'), primary_key=True)
    is_soldout = Column(Boolean, default=False)     # Si ce pack est sold out pour cet événement
    
    # Relations
    event = relationship("Event", back_populates="pack_associations")
    pack = relationship("Pack", back_populates="event_associations")


class User(Base):
    """Modèle de base de données pour les utilisateurs"""
    __tablename__ = "users"
    
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    username = Column(String(100), unique=True, nullable=False, index=True)
    email = Column(String(255), unique=True, nullable=False, index=True)
    name = Column(String(255), nullable=True)
    hashed_password = Column(String(255), nullable=False)
    role = Column(String(50), default="user", nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    
    def __repr__(self):
        return f"<User(id={self.id}, username={self.username}, email={self.email}, role={self.role})>"


class Event(Base):
    """Modèle pour les événements"""
    __tablename__ = "events"
    
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    title = Column(String(255), nullable=False, index=True)  # Titre principal (langue par défaut)
    title_translations = Column(JSON, nullable=True)  # {"fr": "", "en": "", "nl": "", "sq": ""}
    description = Column(Text, nullable=False)  # Description principale (langue par défaut)
    description_translations = Column(JSON, nullable=True)  # {"fr": "", "en": "", "nl": "", "sq": ""}
    category = Column(String(50), nullable=False)  # concert, festival, party, wedding
    date = Column(String(20), nullable=False)  # Format: YYYY-MM-DD
    time = Column(String(10), nullable=False)  # Format: HH:MM
    location = Column(String(255), nullable=False)
    address = Column(String(500), nullable=True)
    city = Column(String(100), nullable=False)
    maps_embed_url = Column(Text, nullable=True)  # URL d'embed Google Maps
    image_url = Column(Text, nullable=True)  # Text pour supporter les images base64
    capacity = Column(Integer, nullable=True)
    featured = Column(Boolean, default=False)
    status = Column(String(20), default="upcoming")  # upcoming, past, cancelled
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    
    # Relations
    artist_associations = relationship("EventArtist", back_populates="event", cascade="all, delete-orphan")
    pack_associations = relationship("EventPack", back_populates="event", cascade="all, delete-orphan")
    
    # Propriétés pour faciliter l'accès
    @property
    def artists(self):
        return [assoc.artist for assoc in self.artist_associations]
    
    @property
    def packs(self):
        return [assoc.pack for assoc in self.pack_associations]
    
    def __repr__(self):
        return f"<Event(id={self.id}, title={self.title}, date={self.date})>"


class Artist(Base):
    """Modèle pour les Artistes/DJs"""
    __tablename__ = "artists"
    
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    name = Column(String(255), nullable=False, index=True)
    role = Column(String(100), nullable=True)  # Ex: Resident DJ, Live Performer
    role_translations = Column(JSON, nullable=True)  # {"fr": "", "en": "", "nl": "", "sq": ""}
    description = Column(Text, nullable=True)
    description_translations = Column(JSON, nullable=True)  # {"fr": "", "en": "", "nl": "", "sq": ""}
    image_url = Column(Text, nullable=True)  # Text pour supporter les images base64
    events_count = Column(Integer, default=0)
    badge = Column(String(20), nullable=True)  # star, fire, premium
    instagram = Column(String(255), nullable=True)
    show_on_website = Column(Boolean, default=True)  # Afficher sur le site web (team)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    
    # Relations
    event_associations = relationship("EventArtist", back_populates="artist", cascade="all, delete-orphan")
    
    @property
    def events(self):
        return [assoc.event for assoc in self.event_associations]
    
    def __repr__(self):
        return f"<Artist(id={self.id}, name={self.name}, role={self.role})>"


class Pack(Base):
    """Modèle pour les packs de réservation"""
    __tablename__ = "packs"
    
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    name = Column(String(100), nullable=False)  # Standard, Premium, VIP
    name_translations = Column(JSON, nullable=True)  # {"fr": "", "en": "", "nl": "", "sq": ""}
    type = Column(String(50), nullable=False)  # standard, premium, vip
    description = Column(Text, nullable=True)
    description_translations = Column(JSON, nullable=True)  # {"fr": "", "en": "", "nl": "", "sq": ""}
    price = Column(Float, nullable=False)
    currency = Column(String(10), default="€")
    unit = Column(String(50), nullable=True)  # Ex: "/ personne", "/ table de 6"
    features = Column(JSON, nullable=True)    # Liste des avantages en JSON
    features_translations = Column(JSON, nullable=True)  # {"fr": [], "en": [], "nl": [], "sq": []}
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    
    # Relations
    event_associations = relationship("EventPack", back_populates="pack", cascade="all, delete-orphan")
    
    @property
    def events(self):
        return [assoc.event for assoc in self.event_associations]
    
    def __repr__(self):
        return f"<Pack(id={self.id}, name={self.name}, type={self.type}, price={self.price})>"

