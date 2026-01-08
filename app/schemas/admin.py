"""Schemas pour les endpoints d'administration"""
from pydantic import BaseModel, EmailStr, field_validator
from typing import Optional, List, Literal
import re


# ===== ORDER SCHEMAS =====

class OrderListItem(BaseModel):
    """Item de commande dans la liste"""
    id: str
    order_number: str
    customer_name: str
    customer_email: str
    event_id: str
    event_title: str
    # Legacy fields - Kept for backward compatibility
    pack_name: str
    quantity: int
    # NEW: Multi-pack support
    pack_display: str
    pack_items: List[dict]
    total_quantity: int
    amount: float
    status: str
    payment_method: str = "online"  # online, cash
    paypal_order_id: Optional[str]
    created_at: str
    paid_at: Optional[str]

    class Config:
        from_attributes = True


class OrdersListResponse(BaseModel):
    """Réponse de la liste des commandes"""
    orders: List[OrderListItem]
    total: int
    page: int
    limit: int
    total_pages: int
    global_revenue: float
    global_completed: int
    global_pending: int
    global_pending_cash: int = 0  # Réservations cash en attente
    global_failed: int


class TicketDetail(BaseModel):
    """Détail d'un ticket"""
    id: str
    ticket_code: str
    holder_name: str
    status: str
    scanned_at: Optional[str]
    scanned_by: Optional[str]

    class Config:
        from_attributes = True


class OrderDetail(BaseModel):
    """Détail complet d'une commande"""
    id: str
    order_number: str
    customer_name: str
    customer_email: str
    customer_phone: Optional[str]
    event_id: str
    event_title: str
    event_date: str
    pack_id: Optional[str]
    pack_name: str
    quantity: int
    pack_display: str
    pack_items: List[dict]
    total_quantity: int
    amount: float
    status: str
    payment_method: str = "online"  # online, cash
    paypal_order_id: Optional[str]
    payment_failure_reason: Optional[str]
    created_at: str
    paid_at: Optional[str]
    tickets: List[TicketDetail]

    class Config:
        from_attributes = True


class RefundRequest(BaseModel):
    """Demande de remboursement"""
    amount: Optional[float] = None
    reason: Optional[str] = None


class RefundResponse(BaseModel):
    """Réponse de remboursement"""
    success: bool
    message: str
    refund_amount: float
    order_status: str


class ResendEmailResponse(BaseModel):
    """Réponse de renvoi d'email"""
    success: bool
    message: str


# ===== STATS SCHEMAS =====

class EventStatsResponse(BaseModel):
    """Statistiques de ventes d'un événement"""
    event_id: str
    event_title: str
    total_orders: int
    total_revenue: float
    tickets_sold: int
    tickets_scanned: int
    scan_rate: float
    orders_by_status: dict
    sales_by_pack: List[dict]
    sales_by_day: List[dict]


class TopEventStats(BaseModel):
    """Stats résumées d'un événement pour le classement"""
    event_id: str
    event_title: str
    event_date: str
    revenue: float
    tickets_sold: int
    orders_count: int


class GlobalStatsResponse(BaseModel):
    """Statistiques globales de toutes les ventes"""
    total_revenue: float
    total_orders: int
    completed_orders: int
    pending_orders: int
    failed_orders: int
    refunded_orders: int
    tickets_sold: int
    tickets_scanned: int
    scan_rate: float
    top_events: List[TopEventStats]


# ===== USER SCHEMAS =====

class UserCreate(BaseModel):
    """Création d'un utilisateur"""
    username: str
    email: EmailStr
    password: str
    name: str
    role: Literal["admin", "steward", "super_admin"]
    phone: Optional[str] = None

    @field_validator('password')
    @classmethod
    def validate_password(cls, v: str) -> str:
        """Valider la force du mot de passe"""
        if len(v) < 8:
            raise ValueError("Le mot de passe doit contenir au moins 8 caractères")
        if not re.search(r'[A-Z]', v):
            raise ValueError("Le mot de passe doit contenir au moins une majuscule")
        if not re.search(r'[a-z]', v):
            raise ValueError("Le mot de passe doit contenir au moins une minuscule")
        if not re.search(r'[0-9]', v):
            raise ValueError("Le mot de passe doit contenir au moins un chiffre")
        if not re.search(r'[!@#$%^&*(),.?":{}|<>\-_=+\[\]\\;\'`~]', v):
            raise ValueError("Le mot de passe doit contenir au moins un caractère spécial")
        
        common_passwords = [
            'password', '12345678', 'qwerty', 'abc123', 'password123',
            'admin', 'letmein', 'welcome', 'monkey', 'dragon',
            'master', 'login', 'princess', 'qwertyuiop', 'password1',
            'iloveyou', 'sunshine', 'admin123', 'passw0rd', '123456789'
        ]
        if v.lower() in common_passwords:
            raise ValueError("Ce mot de passe est trop courant.")
        
        return v


class UserUpdate(BaseModel):
    """Mise à jour d'un utilisateur"""
    username: Optional[str] = None
    email: Optional[EmailStr] = None
    name: Optional[str] = None
    role: Optional[Literal["admin", "steward", "super_admin"]] = None
    phone: Optional[str] = None
    is_active: Optional[bool] = None


class UserResponse(BaseModel):
    """Réponse utilisateur"""
    id: str
    username: str
    email: str
    name: str
    role: str
    phone: Optional[str]
    is_active: bool
    created_at: str
    last_login: Optional[str]

    class Config:
        from_attributes = True

