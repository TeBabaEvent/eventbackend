"""Modèles SQLAlchemy"""
from sqlalchemy import Column, String, DateTime, Integer, Text, Float, Boolean, ForeignKey, JSON, Index
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
    """Association Event-Pack avec statut et capacité"""
    __tablename__ = "event_packs"
    
    event_id = Column(String(36), ForeignKey('events.id', ondelete='CASCADE'), primary_key=True)
    pack_id = Column(String(36), ForeignKey('packs.id', ondelete='CASCADE'), primary_key=True)
    is_soldout = Column(Boolean, default=False)     # Si ce pack est sold out pour cet événement (override manuel)
    capacity = Column(Integer, nullable=True)       # Capacité max pour ce pack (null = illimité)
    sold_count = Column(Integer, default=0)         # Nombre de tickets vendus (mis à jour après paiement)
    
    # Relations
    event = relationship("Event", back_populates="pack_associations")
    pack = relationship("Pack", back_populates="event_associations")
    
    @property
    def remaining(self) -> int | None:
        """Places restantes (None si capacité illimitée)"""
        if self.capacity is None:
            return None
        return max(0, self.capacity - self.sold_count)
    
    @property
    def is_available(self) -> bool:
        """True si le pack est encore disponible à l'achat"""
        if self.is_soldout:
            return False
        if self.capacity is None:
            return True
        return self.sold_count < self.capacity


class User(Base):
    """Modèle de base de données pour les utilisateurs"""
    __tablename__ = "users"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    username = Column(String(100), unique=True, nullable=False, index=True)
    email = Column(String(255), unique=True, nullable=False, index=True)
    name = Column(String(255), nullable=True)
    hashed_password = Column(String(255), nullable=False)
    role = Column(String(50), default="user", nullable=False, index=True)  # user, admin, super_admin, steward
    phone = Column(String(50), nullable=True)  # Téléphone pour stewards
    is_active = Column(Boolean, default=True, nullable=False, index=True)  # Index for filtering active users
    last_login = Column(DateTime(timezone=True), nullable=True)  # Dernière connexion
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    # Relations
    scan_logs = relationship("ScanLog", back_populates="steward")
    scanned_tickets = relationship("Ticket", back_populates="scanner", foreign_keys="[Ticket.scanned_by]")

    def __repr__(self):
        return f"<User(id={self.id}, username={self.username}, email={self.email}, role={self.role})>"


class Event(Base):
    """Modèle pour les événements"""
    __tablename__ = "events"
    
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    slug = Column(String(300), unique=True, nullable=True, index=True)  # URL-friendly slug (nullable pour migration)
    title = Column(String(255), nullable=False, index=True)  # Titre principal (langue par défaut)
    title_translations = Column(JSON, nullable=True)  # {"fr": "", "en": "", "nl": "", "sq": ""}
    description = Column(Text, nullable=False)  # Description principale (langue par défaut)
    description_translations = Column(JSON, nullable=True)  # {"fr": "", "en": "", "nl": "", "sq": ""}
    category = Column(String(50), nullable=False, index=True)  # concert, festival, party, wedding
    date = Column(String(20), nullable=False, index=True)  # Format: YYYY-MM-DD
    time = Column(String(10), nullable=False)  # Format: HH:MM
    location = Column(String(255), nullable=False)
    address = Column(String(500), nullable=True)
    city = Column(String(100), nullable=False)
    maps_embed_url = Column(Text, nullable=True)  # URL d'embed Google Maps
    image_url = Column(Text, nullable=True)  # Text pour supporter les images base64
    youtube_shorts_url = Column(Text, nullable=True)  # URL after movie YouTube Shorts
    instagram_reels_url = Column(Text, nullable=True)  # URL after movie Instagram Reels
    capacity = Column(Integer, nullable=True)
    status = Column(String(20), default="upcoming", index=True)  # upcoming, past, cancelled
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    
    # Relations
    artist_associations = relationship("EventArtist", back_populates="event", cascade="all, delete-orphan")
    pack_associations = relationship("EventPack", back_populates="event", cascade="all, delete-orphan")
    orders = relationship("Order", back_populates="event")
    tickets = relationship("Ticket", back_populates="event")
    scan_logs = relationship("ScanLog", back_populates="event")
    
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
    role = Column(String(100), nullable=True, index=True)  # Ex: Resident DJ, Live Performer
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
    is_active = Column(Boolean, default=True, index=True)  # Index for filtering active packs
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    
    # Relations
    event_associations = relationship("EventPack", back_populates="pack", cascade="all, delete-orphan")
    orders = relationship("Order", back_populates="pack")

    @property
    def events(self):
        return [assoc.event for assoc in self.event_associations]

    def __repr__(self):
        return f"<Pack(id={self.id}, name={self.name}, type={self.type}, price={self.price})>"


# ============== BILLETTERIE - ORDER ITEMS ==============

class OrderItem(Base):
    """Modèle pour les articles d'une commande (liaison Order-Pack)"""
    __tablename__ = "order_items"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    order_id = Column(String(36), ForeignKey("orders.id", ondelete='CASCADE'), nullable=False, index=True)
    pack_id = Column(String(36), ForeignKey("packs.id"), nullable=False, index=True)
    event_id = Column(String(36), ForeignKey("events.id", ondelete='CASCADE'), nullable=False, index=True)  # Denormalized for performance

    # Détails de l'article
    quantity = Column(Integer, nullable=False)  # Nombre de tickets de ce pack
    unit_price = Column(Float, nullable=False)  # Prix unitaire au moment de l'achat (snapshot)

    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # Relations
    order = relationship("Order", back_populates="items")
    pack = relationship("Pack", lazy="joined")  # Eager load to avoid N+1 queries
    event = relationship("Event")

    def __repr__(self):
        return f"<OrderItem(id={self.id}, pack_id={self.pack_id}, quantity={self.quantity})>"


# ============== BILLETTERIE - ORDERS ==============

class Order(Base):
    """Modèle pour les commandes de billets"""
    __tablename__ = "orders"
    __table_args__ = (
        # Composite index for common query patterns
        Index('ix_orders_status_created', 'status', 'created_at'),  # For filtering by status + date range
        Index('ix_orders_event_status', 'event_id', 'status'),  # For event-specific order queries
    )

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    order_number = Column(String(20), unique=True, nullable=False, index=True)  # Format: BABA-XXXXXX

    # Relations
    event_id = Column(String(36), ForeignKey("events.id", ondelete='CASCADE'), nullable=False, index=True)

    # Legacy fields (nullable pour backward compatibility)
    pack_id = Column(String(36), ForeignKey("packs.id"), nullable=True, index=True)  # Deprecated: use items
    quantity = Column(Integer, nullable=True)  # Deprecated: use items

    # Détails commande
    amount = Column(Integer, nullable=False)  # En centimes (stockage interne)
    status = Column(String(20), default="pending", nullable=False, index=True)  # pending, completed, failed, refunded

    # Payment Method & Provider
    payment_method = Column(String(20), default="online", nullable=False)  # online, cash
    paypal_order_id = Column(String(50), nullable=True, index=True)  # ID commande PayPal

    # Informations client
    customer_email = Column(String(255), nullable=False, index=True)
    customer_name = Column(String(255), nullable=False)
    customer_phone = Column(String(50), nullable=True)

    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)  # Index for date filtering and sorting
    paid_at = Column(DateTime(timezone=True), nullable=True)
    refunded_at = Column(DateTime(timezone=True), nullable=True)
    expires_at = Column(DateTime(timezone=True), nullable=True, index=True)  # Index for expired orders cleanup

    # Ticket generation tracking
    tickets_generated = Column(Boolean, default=False, nullable=False, index=True)  # Index for recovery queries

    # Relations
    event = relationship("Event", back_populates="orders")
    pack = relationship("Pack", back_populates="orders")  # Legacy
    items = relationship("OrderItem", back_populates="order", cascade="all, delete-orphan")  # NEW: Multi-pack support
    tickets = relationship("Ticket", back_populates="order", cascade="all, delete-orphan")

    # Helper properties
    @property
    def total_quantity(self) -> int:
        """Total number of tickets across all items"""
        if self.items:
            return sum(item.quantity for item in self.items)
        return self.quantity or 0  # Fallback to legacy field

    @property
    def is_cart_order(self) -> bool:
        """True if order uses new cart system (has OrderItems)"""
        return len(self.items) > 0 if self.items else False
    
    @property
    def is_expired(self) -> bool:
        """True if pending order has expired"""
        if self.status != "pending" or not self.expires_at:
            return False
        from datetime import datetime
        return datetime.utcnow() > self.expires_at.replace(tzinfo=None)

    @property
    def pack_items_list(self) -> list:
        """
        Liste structurée des packs de la commande.
        Retourne: [{"name": str, "quantity": int, "price": float}, ...]
        Fonctionne pour multi-pack et legacy single-pack.
        """
        result = []
        if self.items and len(self.items) > 0:
            for item in self.items:
                result.append({
                    "name": item.pack.name if item.pack else "Pack",
                    "quantity": item.quantity,
                    "price": item.unit_price
                })
        elif self.pack:
            result.append({
                "name": self.pack.name,
                "quantity": self.quantity or 1,
                "price": self.pack.price
            })
        else:
            result.append({
                "name": "Standard",
                "quantity": self.quantity or 1,
                "price": 0
            })
        return result

    @property
    def pack_display(self) -> str:
        """
        Résumé textuel des packs pour affichage.
        Ex: "VIP x2, Standard x3" ou "Standard"
        """
        items = self.pack_items_list
        if len(items) == 1 and items[0]["quantity"] == 1:
            return items[0]["name"]
        return ", ".join([f"{p['name']} x{p['quantity']}" for p in items])

    def __repr__(self):
        return f"<Order(id={self.id}, order_number={self.order_number}, status={self.status})>"


# ============== BILLETTERIE - TICKETS ==============

class Ticket(Base):
    """Modèle pour les billets électroniques"""
    __tablename__ = "tickets"
    __table_args__ = (
        # Composite index for event ticket statistics
        Index('ix_tickets_event_status', 'event_id', 'status'),  # For counting tickets per event by status
    )

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    ticket_code = Column(String(20), unique=True, nullable=False, index=True)  # Format: BABA-XXXXXXXX
    qr_data = Column(Text, nullable=False)  # JWT signé pour sécurité

    # Relations
    order_id = Column(String(36), ForeignKey("orders.id", ondelete='CASCADE'), nullable=False, index=True)
    event_id = Column(String(36), ForeignKey("events.id", ondelete='CASCADE'), nullable=False, index=True)
    pack_id = Column(String(36), ForeignKey("packs.id"), nullable=True, index=True)  # Type de ticket (VIP, Standard, etc.)

    # Détails ticket
    holder_name = Column(String(255), nullable=True)  # Nom du titulaire
    pack_name = Column(String(100), nullable=True)  # Snapshot du nom du pack au moment de l'achat
    status = Column(String(20), default="valid", nullable=False, index=True)  # valid, used, cancelled, expired

    # Informations de scan
    scanned_at = Column(DateTime(timezone=True), nullable=True)
    scanned_by = Column(String(36), ForeignKey("users.id"), nullable=True)  # Steward qui a scanné

    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # Relations
    order = relationship("Order", back_populates="tickets")
    event = relationship("Event", back_populates="tickets")
    pack = relationship("Pack")  # Lien vers le type de pack
    scanner = relationship("User", back_populates="scanned_tickets", foreign_keys=[scanned_by])

    def __repr__(self):
        return f"<Ticket(id={self.id}, ticket_code={self.ticket_code}, pack={self.pack_name}, status={self.status})>"


# ============== WEBHOOKS - IDEMPOTENCE ==============

class WebhookEvent(Base):
    """Modèle pour la gestion des webhooks (idempotence)"""
    __tablename__ = "webhook_events"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    provider = Column(String(50), nullable=False, index=True)  # "mollie"
    provider_event_id = Column(String(100), nullable=False, index=True)  # ID de l'événement chez le provider
    event_type = Column(String(100), nullable=True)  # Type d'événement (ex: "payment.success")
    status = Column(String(20), default="processing", nullable=False, index=True)  # Index for status filtering
    raw_payload = Column(JSON, nullable=True)  # Payload brut du webhook
    error_message = Column(Text, nullable=True)  # Message d'erreur si échec

    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    processed_at = Column(DateTime(timezone=True), nullable=True)

    def __repr__(self):
        return f"<WebhookEvent(id={self.id}, provider={self.provider}, status={self.status})>"


# ============== SCAN - HISTORIQUE ==============

class ScanLog(Base):
    """Modèle pour l'historique des scans de tickets (audit)"""
    __tablename__ = "scan_logs"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    ticket_id = Column(String(36), ForeignKey("tickets.id"), nullable=True, index=True)  # Peut être null si ticket invalide
    scanned_code = Column(String(500), nullable=False)  # Code scanné (pour audit)
    event_id = Column(String(36), ForeignKey("events.id", ondelete='SET NULL'), nullable=True, index=True)  # Nullable si event non déterminable
    steward_id = Column(String(36), ForeignKey("users.id"), nullable=False, index=True)
    result = Column(String(20), nullable=False, index=True)  # success, already_used, invalid, cancelled, wrong_event, expired

    # Timestamp
    scanned_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)  # Index for time-based queries

    # Relations
    ticket = relationship("Ticket")
    event = relationship("Event", back_populates="scan_logs")
    steward = relationship("User", back_populates="scan_logs")

    def __repr__(self):
        return f"<ScanLog(id={self.id}, result={self.result}, scanned_at={self.scanned_at})>"

