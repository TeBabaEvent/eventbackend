"""Service pour la gestion des commandes admin - Single Responsibility"""
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import func, or_
from datetime import date, timedelta
from typing import Optional, List, Dict, Any
import logging

from app.db import models
from app.services.order_formatting_service import format_pack_display, get_pack_items_for_display

logger = logging.getLogger(__name__)


class AdminOrderService:
    """Service dédié à la gestion des commandes admin"""
    
    def __init__(self, db: Session):
        self.db = db
    
    def get_orders_paginated(
        self,
        event_id: Optional[str] = None,
        status: Optional[str] = None,
        search: Optional[str] = None,
        date_from: Optional[date] = None,
        date_to: Optional[date] = None,
        page: int = 1,
        limit: int = 50
    ) -> Dict[str, Any]:
        """
        Récupère les commandes avec filtres et pagination.
        
        Returns:
            Dict avec orders, total, page, limit, total_pages et stats globales
        """
        query = self.db.query(models.Order)
        
        # Appliquer les filtres
        if event_id:
            query = query.filter(models.Order.event_id == event_id)
        if status:
            query = query.filter(models.Order.status == status)
        if search:
            pattern = f"%{search}%"
            query = query.filter(
                or_(
                    models.Order.customer_email.ilike(pattern),
                    models.Order.order_number.ilike(pattern)
                )
            )
        if date_from:
            query = query.filter(models.Order.created_at >= date_from)
        if date_to:
            query = query.filter(models.Order.created_at < date_to + timedelta(days=1))
        
        # Pagination
        total = query.count()
        total_pages = (total + limit - 1) // limit if total > 0 else 0
        offset = (page - 1) * limit
        
        # ✅ Eager loading pour éviter N+1 queries
        orders = query.options(
            joinedload(models.Order.event),
            joinedload(models.Order.pack),
            joinedload(models.Order.items).joinedload(models.OrderItem.pack)
        ).order_by(models.Order.created_at.desc()).limit(limit).offset(offset).all()
        
        # Formater les résultats
        results = [self._format_order_list_item(order) for order in orders]
        
        # Stats globales
        global_stats = self._get_global_order_stats()
        
        return {
            "orders": results,
            "total": total,
            "page": page,
            "limit": limit,
            "total_pages": total_pages,
            **global_stats
        }
    
    def get_order_by_id(self, order_id: str) -> Optional[models.Order]:
        """Récupère une commande par ID avec eager loading"""
        return self.db.query(models.Order).options(
            joinedload(models.Order.event),
            joinedload(models.Order.pack),
            joinedload(models.Order.items).joinedload(models.OrderItem.pack),
            joinedload(models.Order.tickets).joinedload(models.Ticket.scanner)
        ).filter(models.Order.id == order_id).first()
    
    def format_order_detail(self, order: models.Order) -> Dict[str, Any]:
        """Formate les détails complets d'une commande"""
        # ✅ Utiliser les tickets déjà chargés via eager loading (get_order_by_id)
        tickets_data = []
        for ticket in order.tickets:
            # Le scanner est déjà chargé via joinedload
            scanned_by = ticket.scanner.username if ticket.scanner else None
            
            tickets_data.append({
                "id": ticket.id,
                "ticket_code": ticket.ticket_code,
                "holder_name": ticket.holder_name or order.customer_name,
                "status": ticket.status,
                "scanned_at": ticket.scanned_at.isoformat() if ticket.scanned_at else None,
                "scanned_by": scanned_by
            })
        
        return {
            "id": order.id,
            "order_number": order.order_number,
            "customer_name": order.customer_name,
            "customer_email": order.customer_email,
            "customer_phone": order.customer_phone,
            "event_id": order.event_id,
            "event_title": order.event.title if order.event else "N/A",
            "event_date": order.event.date if order.event else None,  # date est déjà une string YYYY-MM-DD
            "pack_id": order.pack_id,
            "pack_name": order.pack.name if order.pack else "N/A",
            "quantity": order.quantity or 0,
            "pack_display": format_pack_display(order),
            "pack_items": get_pack_items_for_display(order),
            "total_quantity": order.total_quantity,
            "amount": order.amount / 100,
            "status": order.status,
            "mollie_payment_id": order.mollie_payment_id,
            "payment_failure_reason": getattr(order, 'payment_failure_reason', None),
            "created_at": order.created_at.isoformat() if order.created_at else None,
            "paid_at": order.paid_at.isoformat() if order.paid_at else None,
            "tickets": tickets_data
        }
    
    def _format_order_list_item(self, order: models.Order) -> Dict[str, Any]:
        """Formate un item de la liste des commandes"""
        return {
            "id": order.id,
            "order_number": order.order_number,
            "customer_name": order.customer_name,
            "customer_email": order.customer_email,
            "event_id": order.event_id,
            "event_title": order.event.title if order.event else "N/A",
            "pack_name": order.pack.name if order.pack else "N/A",
            "quantity": order.quantity or 0,
            "pack_display": format_pack_display(order),
            "pack_items": get_pack_items_for_display(order),
            "total_quantity": order.total_quantity,
            "amount": order.amount / 100,
            "status": order.status,
            "mollie_payment_id": order.mollie_payment_id,
            "created_at": order.created_at.isoformat() if order.created_at else None,
            "paid_at": order.paid_at.isoformat() if order.paid_at else None
        }
    
    def _get_global_order_stats(self) -> Dict[str, Any]:
        """Récupère les statistiques globales des commandes"""
        # Revenu total
        global_revenue_centimes = self.db.query(
            func.sum(models.Order.amount)
        ).filter(models.Order.status == "completed").scalar() or 0
        
        # Comptage par statut
        orders_by_status = self.db.query(
            models.Order.status,
            func.count(models.Order.id).label('count')
        ).group_by(models.Order.status).all()
        
        status_counts = {status: count for status, count in orders_by_status}
        
        return {
            "global_revenue": float(global_revenue_centimes) / 100,
            "global_completed": status_counts.get("completed", 0),
            "global_pending": status_counts.get("pending", 0),
            "global_failed": status_counts.get("failed", 0)
        }


# Dependency injection helper
def get_admin_order_service(db: Session) -> AdminOrderService:
    """Factory pour créer un AdminOrderService"""
    return AdminOrderService(db)

