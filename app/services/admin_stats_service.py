"""Service pour les statistiques admin - Single Responsibility"""
from sqlalchemy.orm import Session
from sqlalchemy import func
from typing import Dict, Any, List, Optional
import logging

from app.db import models

logger = logging.getLogger(__name__)


class AdminStatsService:
    """Service dédié aux statistiques admin"""
    
    def __init__(self, db: Session):
        self.db = db
    
    def get_global_stats(self) -> Dict[str, Any]:
        """Récupère les statistiques globales de toutes les ventes"""
        # Revenu total (commandes completed uniquement)
        total_revenue_centimes = self.db.query(
            func.sum(models.Order.amount)
        ).filter(models.Order.status == "completed").scalar() or 0
        total_revenue = float(total_revenue_centimes) / 100
        
        # Compter les commandes par statut
        orders_by_status = self.db.query(
            models.Order.status,
            func.count(models.Order.id).label('count')
        ).group_by(models.Order.status).all()
        
        status_counts = {status: count for status, count in orders_by_status}
        total_orders = sum(status_counts.values())
        
        # Tickets vendus et scannés
        tickets_sold = self.db.query(models.Ticket).filter(
            models.Ticket.status.in_(["valid", "used"])
        ).count()
        
        tickets_scanned = self.db.query(models.Ticket).filter(
            models.Ticket.status == "used"
        ).count()
        
        scan_rate = (tickets_scanned / tickets_sold * 100) if tickets_sold > 0 else 0
        
        # Top événements
        top_events = self._get_top_events(limit=5)
        
        return {
            "total_revenue": total_revenue,
            "total_orders": total_orders,
            "completed_orders": status_counts.get("completed", 0),
            "pending_orders": status_counts.get("pending", 0),
            "failed_orders": status_counts.get("failed", 0),
            "refunded_orders": status_counts.get("refunded", 0),
            "tickets_sold": tickets_sold,
            "tickets_scanned": tickets_scanned,
            "scan_rate": round(scan_rate, 1),
            "top_events": top_events
        }
    
    def get_event_stats(self, event_id: str) -> Optional[Dict[str, Any]]:
        """Récupère les statistiques d'un événement spécifique"""
        event = self.db.query(models.Event).filter(models.Event.id == event_id).first()
        if not event:
            return None
        
        # Commandes de cet événement
        orders = self.db.query(models.Order).filter(
            models.Order.event_id == event_id
        ).all()
        
        total_orders = len(orders)
        
        # Revenu (completed uniquement)
        total_revenue_centimes = sum(
            o.amount for o in orders if o.status == "completed"
        )
        total_revenue = float(total_revenue_centimes) / 100
        
        # Tickets
        tickets = self.db.query(models.Ticket).filter(
            models.Ticket.event_id == event_id
        ).all()
        
        tickets_sold = len([t for t in tickets if t.status in ["valid", "used"]])
        tickets_scanned = len([t for t in tickets if t.status == "used"])
        scan_rate = (tickets_scanned / tickets_sold * 100) if tickets_sold > 0 else 0
        
        # Par statut
        orders_by_status = {}
        for order in orders:
            orders_by_status[order.status] = orders_by_status.get(order.status, 0) + 1
        
        # Ventes par pack
        sales_by_pack = self._get_sales_by_pack(event_id)
        
        # Ventes par jour
        sales_by_day = self._get_sales_by_day(event_id)
        
        return {
            "event_id": event_id,
            "event_title": event.title,
            "total_orders": total_orders,
            "total_revenue": total_revenue,
            "tickets_sold": tickets_sold,
            "tickets_scanned": tickets_scanned,
            "scan_rate": round(scan_rate, 1),
            "orders_by_status": orders_by_status,
            "sales_by_pack": sales_by_pack,
            "sales_by_day": sales_by_day
        }
    
    def _get_top_events(self, limit: int = 5) -> List[Dict[str, Any]]:
        """Récupère les top événements par revenu"""
        results = self.db.query(
            models.Event.id,
            models.Event.title,
            models.Event.date,
            func.sum(models.Order.amount).label('revenue'),
            func.count(models.Ticket.id).label('tickets_sold'),
            func.count(models.Order.id.distinct()).label('orders_count')
        ).join(
            models.Order, models.Order.event_id == models.Event.id
        ).outerjoin(
            models.Ticket, models.Ticket.order_id == models.Order.id
        ).filter(
            models.Order.status == "completed"
        ).group_by(
            models.Event.id
        ).order_by(
            func.sum(models.Order.amount).desc()
        ).limit(limit).all()
        
        return [
            {
                "event_id": str(r.id),
                "event_title": r.title,
                "event_date": r.date.isoformat() if r.date else None,
                "revenue": float(r.revenue or 0) / 100,
                "tickets_sold": r.tickets_sold or 0,
                "orders_count": r.orders_count or 0
            }
            for r in results
        ]
    
    def _get_sales_by_pack(self, event_id: str) -> List[Dict[str, Any]]:
        """Récupère les ventes par pack pour un événement"""
        results = self.db.query(
            models.Pack.name,
            func.count(models.Ticket.id).label('tickets_sold'),
            func.sum(models.Order.amount).label('revenue')
        ).join(
            models.Order, models.Order.pack_id == models.Pack.id
        ).join(
            models.Ticket, models.Ticket.order_id == models.Order.id
        ).filter(
            models.Order.event_id == event_id,
            models.Order.status == "completed"
        ).group_by(models.Pack.name).all()
        
        return [
            {
                "pack_name": r.name,
                "tickets_sold": r.tickets_sold,
                "revenue": float(r.revenue or 0) / 100
            }
            for r in results
        ]
    
    def _get_sales_by_day(self, event_id: str) -> List[Dict[str, Any]]:
        """Récupère les ventes par jour pour un événement"""
        results = self.db.query(
            func.date(models.Order.created_at).label('date'),
            func.count(models.Order.id).label('orders'),
            func.sum(models.Order.amount).label('revenue')
        ).filter(
            models.Order.event_id == event_id,
            models.Order.status == "completed"
        ).group_by(
            func.date(models.Order.created_at)
        ).order_by(
            func.date(models.Order.created_at)
        ).all()
        
        return [
            {
                "date": str(r.date),
                "orders": r.orders,
                "revenue": float(r.revenue or 0) / 100
            }
            for r in results
        ]


# Dependency injection helper
def get_admin_stats_service(db: Session) -> AdminStatsService:
    """Factory pour créer un AdminStatsService"""
    return AdminStatsService(db)

