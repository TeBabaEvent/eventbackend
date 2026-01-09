"""Schémas pour le système de panier (cart)"""
from typing import List
from pydantic import BaseModel, EmailStr, field_validator


class CartItemRequest(BaseModel):
    """Un article dans le panier"""
    event_id: str
    pack_id: str
    quantity: int

    @field_validator('quantity')
    @classmethod
    def validate_quantity(cls, v):
        if v < 1:
            raise ValueError('La quantité doit être au moins 1')
        if v > 50:
            raise ValueError('Maximum 50 tickets par pack')
        return v


class CartCheckoutRequest(BaseModel):
    """Demande de checkout pour un panier multi-pack"""
    items: List[CartItemRequest]
    customer_name: str
    customer_email: EmailStr
    customer_phone: str | None = None
    payment_method: str = "online"  # online, cash

    # GDPR Consent - Mandatory
    terms_accepted: bool = False

    @field_validator('terms_accepted')
    @classmethod
    def validate_terms_accepted(cls, v):
        if not v:
            raise ValueError('You must accept the terms and conditions')
        return v

    @field_validator('payment_method')
    @classmethod
    def validate_payment_method(cls, v):
        if v not in ['online', 'cash']:
            raise ValueError('Méthode de paiement invalide. Utilisez "online" ou "cash"')
        return v

    @field_validator('items')
    @classmethod
    def validate_items(cls, v):
        if not v or len(v) == 0:
            raise ValueError('Le panier ne peut pas être vide')

        if len(v) > 10:
            raise ValueError('Maximum 10 packs différents par commande')

        # Vérifier la limite totale de 50 tickets
        total_quantity = sum(item.quantity for item in v)
        if total_quantity > 50:
            raise ValueError(f'Maximum 50 tickets total par commande (vous avez {total_quantity})')

        # Vérifier qu'il n'y a pas de doublons (même event_id + pack_id)
        seen = set()
        for item in v:
            key = (item.event_id, item.pack_id)
            if key in seen:
                raise ValueError(f'Pack dupliqué trouvé: {item.pack_id}')
            seen.add(key)

        return v


class CartCheckoutResponse(BaseModel):
    """Réponse avec URL de paiement pour le panier"""
    order_number: str
    pay_url: str
    amount: float  # En EUR
    total_items: int
    payment_method: str = "online"  # online, cash
    is_pending_cash: bool = False  # True si réservation cash en attente
    paypal_order_id: str | None = None

