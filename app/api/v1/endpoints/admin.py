"""Routes d'administration pour la gestion des commandes et utilisateurs - Rate Limited"""
from fastapi import APIRouter, HTTPException, Depends, Query, Request, status
from sqlalchemy.orm import Session
from sqlalchemy import func, and_, or_
from typing import Optional, List
from datetime import datetime, date, timedelta
import logging

from app.db.database import get_db
from app.db import models
from app.api.deps import (
    require_admin,
    get_admin_order_service,
    get_admin_user_service,
    get_paypal_client
)
from app.core.rate_limiter import limiter, RATE_LIMITS
from app.services.paypal_client import PayPalPaymentClient
from app.services.email_service import send_confirmation_email
from app.services.pdf_service import generate_individual_ticket_pdfs, delete_pdf_file
from app.services.ticket_service import generate_tickets_for_order
from app.services.admin_order_service import AdminOrderService
from app.services.admin_user_service import AdminUserService
from app.services.order_formatting_service import format_pack_display, get_pack_items_for_display


# Import schemas from dedicated file
from app.schemas.admin import (
    OrderListItem, OrdersListResponse, TicketDetail, OrderDetail,
    RefundRequest, RefundResponse, ResendEmailResponse,
    EventStatsResponse, TopEventStats, GlobalStatsResponse,
    UserCreate, UserUpdate, UserResponse
)

logger = logging.getLogger(__name__)
router = APIRouter()


# ===== ENDPOINTS ORDERS =====

@router.get("/orders", response_model=OrdersListResponse)
def get_orders(
    request: Request,
    event_id: Optional[str] = Query(None, description="Filtrer par événement"),
    status: Optional[str] = Query(None, description="Filtrer par statut"),
    search: Optional[str] = Query(None, description="Rechercher par email ou order_number"),
    date_from: Optional[date] = Query(None, description="Date de début (YYYY-MM-DD)"),
    date_to: Optional[date] = Query(None, description="Date de fin (YYYY-MM-DD)"),
    page: int = Query(1, ge=1, description="Numéro de page"),
    limit: int = Query(50, ge=1, le=100, description="Résultats par page"),
    admin: models.User = Depends(require_admin),
    order_service: AdminOrderService = Depends(get_admin_order_service)
):
    """
    Liste des commandes avec filtres et pagination.
    Accessible aux admins et super_admins.
    """
    logger.info(f"Admin {admin.username} accède à la liste des commandes")
    
    # Déléguer au service (SRP)
    result = order_service.get_orders_paginated(
        event_id=event_id,
        status=status,
        search=search,
        date_from=date_from,
        date_to=date_to,
        page=page,
        limit=limit
    )
    
    return OrdersListResponse(**result)


@router.get("/orders/{order_id}", response_model=OrderDetail)
def get_order_detail(
    order_id: str,
    admin: models.User = Depends(require_admin),
    order_service: AdminOrderService = Depends(get_admin_order_service)
):
    """Détail complet d'une commande avec tickets."""
    logger.info(f"Admin {admin.username} consulte commande {order_id}")
    
    order = order_service.get_order_by_id(order_id)
    if not order:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Commande non trouvée")
    
    return OrderDetail(**order_service.format_order_detail(order))


@router.post(
    "/orders/{order_id}/refund",
    response_model=RefundResponse,
    status_code=status.HTTP_200_OK,
    responses={
        400: {"description": "Order cannot be refunded (wrong status or missing payment)"},
        404: {"description": "Order not found"},
        500: {"description": "Payment provider error"}
    }
)
async def refund_order(
    order_id: str,
    request: RefundRequest,
    db: Session = Depends(get_db),
    admin: models.User = Depends(require_admin),
    paypal_client: PayPalPaymentClient = Depends(get_paypal_client)
):
    """
    Rembourser une commande via PayPal.

    Accessible aux admins et super_admins.

    Flow:
    1. Vérifier que la commande existe et est payée
    2. Récupérer le capture_id depuis PayPal
    3. Appeler l'API PayPal pour rembourser
    4. Mettre à jour le statut de la commande
    5. Annuler les tickets associés
    6. Envoyer un email de confirmation

    Args:
        order_id: ID de la commande
        request: Montant optionnel (None = remboursement total)

    Returns:
        RefundResponse avec résultat

    Raises:
        HTTPException 404: Si la commande n'existe pas
        HTTPException 400: Si la commande ne peut pas être remboursée
        HTTPException 500: Si l'API PayPal échoue
    """
    logger.info(f"Admin {admin.username} demande remboursement commande {order_id}")

    # 1. Récupérer la commande
    order = db.query(models.Order).filter(models.Order.id == order_id).first()

    if not order:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Commande non trouvée")

    # Vérifier que la commande est payée
    if order.status != "completed":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cette commande ne peut pas être remboursée (statut: {order.status})"
        )

    # Vérifier qu'on a une référence PayPal
    if not order.paypal_order_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Aucune référence de paiement PayPal trouvée pour cette commande"
        )

    # Calculer le montant à rembourser
    refund_amount = request.amount if request.amount is not None else (order.amount / 100)

    # 2. Récupérer le capture_id depuis PayPal
    try:
        order_details = paypal_client.get_order(order.paypal_order_id)
        
        # Extraire le capture_id
        capture_id = None
        purchase_units = order_details.get("purchase_units", [])
        if purchase_units:
            payments = purchase_units[0].get("payments", {})
            captures = payments.get("captures", [])
            if captures:
                capture_id = captures[0].get("id")
        
        if not capture_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Impossible de trouver l'ID de capture PayPal pour cette commande"
            )
        
        # 3. Appeler l'API PayPal pour rembourser
        refund_result = paypal_client.create_refund(
            capture_id=capture_id,
            amount=refund_amount if request.amount is not None else None,  # None = remboursement total
            note=request.reason or f"Remboursement {order.order_number}"
        )
        logger.info(f"Remboursement PayPal réussi: {refund_result}")

    except HTTPException:
        raise  # Re-raise HTTP exceptions
    except Exception as e:
        logger.error(f"Erreur remboursement PayPal: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erreur lors du remboursement PayPal: {str(e)}"
        )

    # 4. Mettre à jour le statut de la commande ET annuler les tickets en une transaction
    try:
        order.status = "refunded"
        
        # Annuler tous les tickets associés
        for ticket in order.tickets:
            ticket.status = "cancelled"
        
        db.commit()
        logger.info(f"Commande {order.order_number} remboursée via PayPal ({refund_amount} EUR)")
    except Exception as e:
        db.rollback()
        logger.error(f"Erreur lors de la mise à jour de la commande: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Le remboursement PayPal a réussi mais la mise à jour en base a échoué"
        )

    # 5. Envoyer un email de confirmation (en arrière-plan)
    try:
        from app.services.email_service import send_refund_email
        await send_refund_email(
            to_email=order.customer_email,
            customer_name=order.customer_name,
            order=order,
            amount=refund_amount
        )
    except Exception as e:
        logger.error(f"Erreur envoi email remboursement: {e}")
        # Ne pas faire échouer le remboursement si l'email échoue

    return RefundResponse(
        success=True,
        message=f"Remboursement de {refund_amount} EUR effectué avec succès via PayPal",
        refund_amount=refund_amount,
        order_status="refunded"
    )




@router.post(
    "/orders/{order_id}/mark-paid",
    response_model=ResendEmailResponse,
    status_code=status.HTTP_200_OK,
    responses={
        400: {"description": "Order is not a pending cash reservation"},
        404: {"description": "Order not found"},
        500: {"description": "Error processing payment"}
    }
)
async def mark_cash_reservation_paid(
    order_id: str,
    db: Session = Depends(get_db),
    admin: models.User = Depends(require_admin)
):
    """
    Marquer une réservation cash comme payée.
    
    Cette action:
    1. Change le statut de "pending_cash" à "completed"
    2. Met à jour les compteurs sold_count
    3. Génère les tickets avec QR codes
    4. Envoie l'email de confirmation avec les billets
    
    Args:
        order_id: ID de la commande
        
    Returns:
        ResendEmailResponse avec résultat
        
    Raises:
        HTTPException 404: Si la commande n'existe pas
        HTTPException 400: Si la commande n'est pas une réservation cash en attente
    """
    logger.info(f"Admin {admin.username} marque réservation cash {order_id} comme payée")
    
    # 1. Récupérer la commande
    order = db.query(models.Order).filter(models.Order.id == order_id).first()
    
    if not order:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Commande non trouvée")
    
    # Vérifier que c'est une réservation cash en attente
    if order.status != "pending_cash":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cette commande n'est pas une réservation cash en attente (statut: {order.status})"
        )
    
    try:
        # 2. Mettre à jour le statut
        order.status = "completed"
        order.paid_at = datetime.utcnow()
        
        # 3. Mettre à jour les compteurs sold_count pour chaque pack
        if order.items and len(order.items) > 0:
            # Multi-pack order
            for item in order.items:
                event_pack = db.query(models.EventPack).filter(
                    models.EventPack.event_id == item.event_id,
                    models.EventPack.pack_id == item.pack_id
                ).with_for_update().first()
                
                if event_pack:
                    event_pack.sold_count = (event_pack.sold_count or 0) + item.quantity
        elif order.pack_id:
            # Legacy single-pack order
            event_pack = db.query(models.EventPack).filter(
                models.EventPack.event_id == order.event_id,
                models.EventPack.pack_id == order.pack_id
            ).with_for_update().first()
            
            if event_pack:
                event_pack.sold_count = (event_pack.sold_count or 0) + (order.quantity or 0)
        
        db.commit()
        db.refresh(order)
        
        # 4. Générer les tickets
        tickets = await generate_tickets_for_order(order, db)
        
        # 5. Générer les PDFs et envoyer l'email
        pdf_paths = await generate_individual_ticket_pdfs(tickets, order)
        
        await send_confirmation_email(
            to_email=order.customer_email,
            customer_name=order.customer_name,
            order=order,
            tickets=tickets,
            pdf_paths=pdf_paths
        )
        
        logger.info(f"Réservation cash {order.order_number} marquée payée, {len(tickets)} tickets générés")
        
        # 6. Nettoyer les PDFs après envoi réussi
        for pdf_path in pdf_paths:
            delete_pdf_file(pdf_path)
        
        return ResendEmailResponse(
            success=True,
            message=f"Paiement confirmé ! {len(tickets)} billets envoyés à {order.customer_email}"
        )
        
    except Exception as e:
        db.rollback()
        logger.error(f"Erreur lors du marquage payé: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erreur lors du traitement du paiement: {str(e)}"
        )


@router.post(
    "/orders/{order_id}/resend-email",
    response_model=ResendEmailResponse,
    status_code=status.HTTP_200_OK,
    responses={
        400: {"description": "Order not paid or no tickets found"},
        404: {"description": "Order not found"},
        500: {"description": "Email sending error"}
    }
)
async def resend_confirmation_email(
    order_id: str,
    db: Session = Depends(get_db),
    admin: models.User = Depends(require_admin)
):
    """
    Renvoyer l'email de confirmation avec les billets.

    Accessible aux admins et super_admins.

    Flow:
    1. Vérifier que la commande existe et est payée
    2. Récupérer les tickets
    3. Régénérer le PDF si nécessaire
    4. Envoyer l'email

    Args:
        order_id: ID de la commande

    Returns:
        ResendEmailResponse avec résultat

    Raises:
        HTTPException 404: Si la commande n'existe pas
        HTTPException 400: Si la commande n'est pas payée
    """
    logger.info(f"Admin {admin.username} renvoie email pour commande {order_id}")

    # 1. Récupérer la commande
    order = db.query(models.Order).filter(models.Order.id == order_id).first()

    if not order:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Commande non trouvée")

    # Vérifier que la commande est payée
    if order.status != "completed":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cette commande n'est pas payée (statut: {order.status})"
        )

    # 2. Récupérer les tickets
    tickets = order.tickets

    if not tickets:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Aucun ticket trouvé pour cette commande"
        )

    try:
        # 3. Régénérer les PDFs individuels
        pdf_paths = await generate_individual_ticket_pdfs(tickets, order)
        logger.info(f"{len(pdf_paths)} PDFs régénérés pour {order.order_number}")

        # 4. Envoyer l'email
        await send_confirmation_email(
            to_email=order.customer_email,
            customer_name=order.customer_name,
            order=order,
            tickets=tickets,
            pdf_paths=pdf_paths
        )

        logger.info(f"Email renvoyé à {order.customer_email} avec {len(pdf_paths)} billets")

        # 5. Nettoyer les PDFs après envoi réussi
        for pdf_path in pdf_paths:
            delete_pdf_file(pdf_path)

        return ResendEmailResponse(
            success=True,
            message=f"Email envoyé avec succès à {order.customer_email}"
        )

    except Exception as e:
        logger.error(f"Erreur renvoi email: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erreur lors de l'envoi de l'email: {str(e)}"
        )


@router.get("/stats", response_model=GlobalStatsResponse)
def get_global_stats(
    db: Session = Depends(get_db),
    admin: models.User = Depends(require_admin)
):
    """
    Statistiques globales de toutes les ventes.

    Accessible aux admins et super_admins.

    Retourne:
    - Revenu total
    - Nombre de commandes par statut
    - Tickets vendus / scannés
    - Top 5 événements par revenu
    """
    logger.info(f"Admin {admin.username} consulte stats globales")

    # ✅ OPTIMISATION: Subquery réutilisable (calculée une seule fois)
    orders_with_items_subquery = db.query(models.OrderItem.order_id).distinct().subquery()

    # Total des commandes par statut
    orders_by_status = db.query(
        models.Order.status,
        func.count(models.Order.id).label('count')
    ).group_by(models.Order.status).all()

    status_counts = {status: count for status, count in orders_by_status}
    total_orders = sum(status_counts.values())

    # Revenu total (commandes completed uniquement)
    total_revenue_centimes = db.query(
        func.sum(models.Order.amount)
    ).filter(models.Order.status == "completed").scalar() or 0
    total_revenue = float(total_revenue_centimes) / 100

    # ✅ OPTIMISATION: Calcul des tickets en une seule requête avec LEFT JOIN
    # Tickets multi-pack (via OrderItem)
    multipack_tickets = db.query(
        func.sum(models.OrderItem.quantity)
    ).join(models.Order).filter(
        models.Order.status == "completed"
    ).scalar() or 0

    # Tickets legacy (commandes sans OrderItem) - utilise la subquery réutilisable
    legacy_tickets = db.query(
        func.sum(models.Order.quantity)
    ).outerjoin(
        orders_with_items_subquery,
        models.Order.id == orders_with_items_subquery.c.order_id
    ).filter(
        models.Order.status == "completed",
        models.Order.quantity.isnot(None),
        orders_with_items_subquery.c.order_id.is_(None)  # Pas dans OrderItems
    ).scalar() or 0

    tickets_sold = multipack_tickets + legacy_tickets

    # Tickets scannés - utilise func.count au lieu de .count() pour éviter requête supplémentaire
    tickets_scanned = db.query(func.count(models.Ticket.id)).filter(
        models.Ticket.status == "used"
    ).scalar() or 0

    # Taux de scan
    scan_rate = (tickets_scanned / tickets_sold * 100) if tickets_sold > 0 else 0

    # Top 5 événements par revenu
    top_events_raw = db.query(
        models.Event.id,
        models.Event.title,
        models.Event.date,
        func.sum(models.Order.amount).label('revenue'),
        func.count(models.Order.id).label('orders')
    ).join(models.Order).filter(
        models.Order.status == "completed"
    ).group_by(
        models.Event.id, models.Event.title, models.Event.date
    ).order_by(func.sum(models.Order.amount).desc()).limit(5).all()

    # Calculer les tickets pour les top events en batch
    if top_events_raw:
        event_ids = [e[0] for e in top_events_raw]

        # Batch query: tickets multi-pack par événement
        multipack_by_event = dict(
            db.query(
                models.Order.event_id,
                func.sum(models.OrderItem.quantity)
            ).join(models.OrderItem).filter(
                models.Order.event_id.in_(event_ids),
                models.Order.status == "completed"
            ).group_by(models.Order.event_id).all()
        )

        # Batch query: tickets legacy par événement (avec LEFT JOIN optimisé)
        legacy_by_event = dict(
            db.query(
                models.Order.event_id,
                func.sum(models.Order.quantity)
            ).outerjoin(
                orders_with_items_subquery,
                models.Order.id == orders_with_items_subquery.c.order_id
            ).filter(
                models.Order.event_id.in_(event_ids),
                models.Order.status == "completed",
                models.Order.quantity.isnot(None),
                orders_with_items_subquery.c.order_id.is_(None)
            ).group_by(models.Order.event_id).all()
        )
    else:
        multipack_by_event = {}
        legacy_by_event = {}

    # Construire la liste des top events avec lookups de dictionnaires
    top_events = []
    for event_id, title, event_date, revenue, orders in top_events_raw:
        event_tickets_sold = (multipack_by_event.get(event_id) or 0) + (legacy_by_event.get(event_id) or 0)

        top_events.append(TopEventStats(
            event_id=str(event_id),
            event_title=title,
            event_date=event_date if event_date else "",
            revenue=float(revenue or 0) / 100,
            tickets_sold=event_tickets_sold,
            orders_count=orders or 0
        ))

    return GlobalStatsResponse(
        total_revenue=total_revenue,
        total_orders=total_orders,
        completed_orders=status_counts.get("completed", 0),
        pending_orders=status_counts.get("pending", 0),
        failed_orders=status_counts.get("failed", 0),
        refunded_orders=status_counts.get("refunded", 0),
        tickets_sold=tickets_sold,
        tickets_scanned=tickets_scanned,
        scan_rate=round(scan_rate, 2),
        top_events=top_events
    )


@router.get("/stats/{event_id}", response_model=EventStatsResponse)
def get_event_stats(
    event_id: str,
    db: Session = Depends(get_db),
    admin: models.User = Depends(require_admin)
):
    """
    Statistiques de ventes pour un événement.

    Accessible aux admins et super_admins.

    Calcule:
    - Nombre total de commandes
    - Revenu total
    - Tickets vendus / scannés
    - Répartition par statut
    - Ventes par pack
    - Évolution des ventes par jour

    Args:
        event_id: ID de l'événement

    Returns:
        EventStatsResponse avec toutes les statistiques

    Raises:
        HTTPException 404: Si l'événement n'existe pas
    """
    logger.info(f"Admin {admin.username} consulte stats événement {event_id}")

    # Vérifier que l'événement existe
    event = db.query(models.Event).filter(models.Event.id == event_id).first()
    if not event:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Événement non trouvé")

    # ✅ OPTIMISATION: Subquery réutilisable (calculée une seule fois)
    orders_with_items_subquery = db.query(models.OrderItem.order_id).distinct().subquery()

    # Compter le total de commandes (utilise func.count au lieu de .count())
    total_orders = db.query(func.count(models.Order.id)).filter(
        models.Order.event_id == event_id
    ).scalar() or 0

    # Calculer le revenu total (uniquement commandes completed)
    total_revenue_centimes = db.query(
        func.sum(models.Order.amount)
    ).filter(
        models.Order.event_id == event_id,
        models.Order.status == "completed"
    ).scalar() or 0

    total_revenue = float(total_revenue_centimes) / 100  # Convertir en EUR

    # ✅ OPTIMISATION: Tickets multi-pack
    multipack_tickets = db.query(
        func.sum(models.OrderItem.quantity)
    ).join(models.Order).filter(
        models.Order.event_id == event_id,
        models.Order.status == "completed"
    ).scalar() or 0

    # ✅ OPTIMISATION: Tickets legacy avec LEFT JOIN (réutilise la subquery)
    legacy_tickets = db.query(
        func.sum(models.Order.quantity)
    ).outerjoin(
        orders_with_items_subquery,
        models.Order.id == orders_with_items_subquery.c.order_id
    ).filter(
        models.Order.event_id == event_id,
        models.Order.status == "completed",
        models.Order.quantity.isnot(None),
        orders_with_items_subquery.c.order_id.is_(None)
    ).scalar() or 0

    tickets_sold = multipack_tickets + legacy_tickets

    # Compter les tickets scannés (utilise func.count)
    tickets_scanned = db.query(func.count(models.Ticket.id)).filter(
        models.Ticket.event_id == event_id,
        models.Ticket.status == "used"
    ).scalar() or 0

    # Calculer le taux de scan
    scan_rate = (tickets_scanned / tickets_sold * 100) if tickets_sold > 0 else 0

    # Répartition par statut
    orders_by_status_raw = db.query(
        models.Order.status,
        func.count(models.Order.id).label('count')
    ).filter(
        models.Order.event_id == event_id
    ).group_by(models.Order.status).all()

    orders_by_status = {status: count for status, count in orders_by_status_raw}

    # ✅ OPTIMISATION: Ventes par pack (multi-pack via OrderItem)
    multipack_sales = db.query(
        models.Pack.name,
        func.count(func.distinct(models.Order.id)).label('orders'),
        func.sum(models.OrderItem.quantity).label('tickets'),
        func.sum(models.OrderItem.quantity * models.OrderItem.unit_price * 100).label('revenue')
    ).join(models.OrderItem, models.Pack.id == models.OrderItem.pack_id
    ).join(models.Order).filter(
        models.Order.event_id == event_id,
        models.Order.status == "completed"
    ).group_by(models.Pack.id, models.Pack.name).all()

    # ✅ OPTIMISATION: Ventes legacy avec LEFT JOIN (réutilise la subquery)
    legacy_sales = db.query(
        models.Pack.name,
        func.count(models.Order.id).label('orders'),
        func.sum(models.Order.quantity).label('tickets'),
        func.sum(models.Order.amount).label('revenue')
    ).join(models.Order, models.Pack.id == models.Order.pack_id
    ).outerjoin(
        orders_with_items_subquery,
        models.Order.id == orders_with_items_subquery.c.order_id
    ).filter(
        models.Order.event_id == event_id,
        models.Order.status == "completed",
        orders_with_items_subquery.c.order_id.is_(None)
    ).group_by(models.Pack.id, models.Pack.name).all()

    # Fusionner les résultats par pack_name
    pack_sales_dict = {}
    for pack_name, orders, tickets, revenue in multipack_sales:
        pack_sales_dict[pack_name] = {
            "pack_name": pack_name,
            "orders": orders,
            "tickets": tickets or 0,
            "revenue": float(revenue or 0) / 100
        }

    for pack_name, orders, tickets, revenue in legacy_sales:
        if pack_name in pack_sales_dict:
            pack_sales_dict[pack_name]["orders"] += orders
            pack_sales_dict[pack_name]["tickets"] += tickets or 0
            pack_sales_dict[pack_name]["revenue"] += float(revenue or 0) / 100
        else:
            pack_sales_dict[pack_name] = {
                "pack_name": pack_name,
                "orders": orders,
                "tickets": tickets or 0,
                "revenue": float(revenue or 0) / 100
            }

    sales_by_pack = list(pack_sales_dict.values())

    # Ventes par jour (pour graphique)
    sales_by_day_raw = db.query(
        func.date(models.Order.created_at).label('day'),
        func.count(models.Order.id).label('orders'),
        func.sum(models.Order.amount).label('revenue')
    ).filter(
        models.Order.event_id == event_id,
        models.Order.status == "completed"
    ).group_by('day').order_by('day').all()

    sales_by_day = [
        {
            "date": day.isoformat() if day else None,
            "orders": orders,
            "revenue": float(revenue or 0) / 100  # Convertir en EUR
        }
        for day, orders, revenue in sales_by_day_raw
    ]

    return EventStatsResponse(
        event_id=event_id,
        event_title=event.title,
        total_orders=total_orders,
        total_revenue=total_revenue,
        tickets_sold=tickets_sold,
        tickets_scanned=tickets_scanned,
        scan_rate=round(scan_rate, 2),
        orders_by_status=orders_by_status,
        sales_by_pack=sales_by_pack,
        sales_by_day=sales_by_day
    )


# ===== ENDPOINTS USERS =====

@router.get("/users", response_model=List[UserResponse])
def get_users(
    role: Optional[str] = Query(None, description="Filtrer par rôle"),
    is_active: Optional[bool] = Query(None, description="Filtrer par statut actif"),
    admin: models.User = Depends(require_admin),
    user_service: AdminUserService = Depends(get_admin_user_service)
):
    """Liste de tous les utilisateurs. Accessible aux admins et super_admins."""
    logger.info(f"Admin {admin.username} consulte liste utilisateurs")
    
    users_data = user_service.get_users(role=role, is_active=is_active)
    return [UserResponse(**u) for u in users_data]


@router.post("/users", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
@limiter.limit(RATE_LIMITS["user_create"])  # 10 user creations per minute
def create_user(
    request: Request,  # Required for rate limiting (must be named 'request' for slowapi)
    user_data: UserCreate,
    admin: models.User = Depends(require_admin),
    user_service: AdminUserService = Depends(get_admin_user_service)
):
    """Créer un nouvel utilisateur. (Rate limited: 10/min)"""
    logger.info(f"Admin {admin.username} crée utilisateur {user_data.username}")

    # Vérifications métier
    if user_service.get_user_by_email(user_data.email):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Cet email existe déjà")
    
    if user_service.get_user_by_username(user_data.username):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Cet username existe déjà")

    if user_data.role == "super_admin" and admin.role != "super_admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Seul un super_admin peut créer un autre super_admin")

    try:
        new_user = user_service.create_user(
            username=user_data.username,
            email=user_data.email,
            password=user_data.password,
            name=user_data.name,
            role=user_data.role,
            phone=user_data.phone
        )
        return UserResponse(**user_service.format_user_response(new_user))
    except Exception as e:
        logger.error(f"❌ Error creating user: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Erreur lors de la création de l'utilisateur")


@router.put("/users/{user_id}", response_model=UserResponse)
def update_user(
    user_id: str,
    request: UserUpdate,
    admin: models.User = Depends(require_admin),
    user_service: AdminUserService = Depends(get_admin_user_service)
):
    """Modifier un utilisateur."""
    logger.info(f"Admin {admin.username} modifie utilisateur {user_id}")

    user = user_service.get_user_by_id(user_id)
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Utilisateur non trouvé")

    # Vérifications d'unicité
    if request.username and request.username != user.username:
        if user_service.get_user_by_username(request.username):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Cet username existe déjà")

    if request.email and request.email != user.email:
        if user_service.get_user_by_email(request.email):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Cet email existe déjà")

    # Vérification des permissions pour super_admin
    if request.role == "super_admin" and admin.role != "super_admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Seul un super_admin peut promouvoir un utilisateur en super_admin")

    try:
        updated_user = user_service.update_user(
            user=user,
            username=request.username,
            email=request.email,
            name=request.name,
            role=request.role,
            phone=request.phone,
            is_active=request.is_active
        )
        return UserResponse(**user_service.format_user_response(updated_user))
    except Exception as e:
        logger.error(f"❌ Error updating user {user_id}: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Erreur lors de la mise à jour de l'utilisateur")


@router.delete("/users/{user_id}")
def delete_user(
    user_id: str,
    admin: models.User = Depends(require_admin),
    user_service: AdminUserService = Depends(get_admin_user_service)
):
    """Supprimer un utilisateur."""
    logger.info(f"Admin {admin.username} supprime utilisateur {user_id}")

    if user_id == admin.id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Vous ne pouvez pas supprimer votre propre compte")

    user = user_service.get_user_by_id(user_id)
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Utilisateur non trouvé")

    try:
        username = user.username
        user_service.delete_user(user)
        return {"message": f"Utilisateur {username} supprimé avec succès"}
    except Exception as e:
        logger.error(f"❌ Error deleting user {user_id}: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Erreur lors de la suppression de l'utilisateur")


# ===== RECOVERY & MAINTENANCE =====

@router.get("/recovery/stats")
async def get_recovery_stats(
    db: Session = Depends(get_db),
    admin: models.User = Depends(require_admin)
):
    """
    Récupère les statistiques de commandes nécessitant une intervention.
    
    Returns:
        - missing_tickets: Commandes completed sans tickets générés
        - expired_pending: Commandes pending expirées à nettoyer
        - active_pending: Commandes pending en cours
    """
    from app.services.order_recovery_service import get_recovery_stats
    
    stats = await get_recovery_stats()
    return stats


@router.post("/recovery/missing-tickets")
async def recover_missing_tickets(
    db: Session = Depends(get_db),
    admin: models.User = Depends(require_admin)
):
    """
    Récupère les commandes completed dont les tickets n'ont pas été générés.
    
    Génère les tickets, le PDF et envoie l'email pour chaque commande.
    
    Returns:
        - recovered: Nombre de commandes récupérées
        - failed: Nombre d'échecs
    """
    from app.services.order_recovery_service import recover_missing_tickets
    
    logger.info(f"Admin {admin.username} lance la récupération des tickets manquants")
    
    result = await recover_missing_tickets()
    
    logger.info(f"Récupération terminée: {result['recovered']} récupérées, {result['failed']} échecs")
    
    return result


@router.post("/recovery/cleanup-expired")
async def cleanup_expired_orders(
    db: Session = Depends(get_db),
    admin: models.User = Depends(require_admin)
):
    """
    Marque comme 'expired' les commandes pending qui ont dépassé leur timeout.
    
    Returns:
        - expired: Nombre de commandes marquées comme expirées
    """
    from app.services.order_recovery_service import cleanup_expired_orders
    
    logger.info(f"Admin {admin.username} lance le nettoyage des commandes expirées")
    
    result = await cleanup_expired_orders()
    
    logger.info(f"Nettoyage terminé: {result['expired']} commandes expirées")
    
    return result


@router.get("/scheduler/status")
def get_scheduler_status(
    admin: models.User = Depends(require_admin)
):
    """
    Récupère le statut du scheduler et de ses jobs CRON.
    
    Returns:
        - running: True si le scheduler est actif
        - jobs: Liste des jobs avec leur prochain exécution
    """
    from app.services.scheduler import get_scheduler_status
    
    return get_scheduler_status()


@router.post("/scheduler/run/{job_id}")
async def run_scheduler_job(
    job_id: str,
    admin: models.User = Depends(require_admin)
):
    """
    Exécute manuellement un job du scheduler.
    
    Jobs disponibles:
    - recover_missing_tickets
    - cleanup_expired_orders
    - system_health_check
    
    Args:
        job_id: ID du job à exécuter
        
    Returns:
        Message de confirmation
    """
    from app.services.scheduler import (
        job_recover_missing_tickets,
        job_cleanup_expired_orders,
        job_health_check
    )
    
    jobs = {
        "recover_missing_tickets": job_recover_missing_tickets,
        "cleanup_expired_orders": job_cleanup_expired_orders,
        "system_health_check": job_health_check
    }
    
    if job_id not in jobs:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Job '{job_id}' non trouvé. Jobs disponibles: {list(jobs.keys())}"
        )
    
    logger.info(f"Admin {admin.username} exécute manuellement le job '{job_id}'")
    
    # Exécuter le job
    await jobs[job_id]()
    
    return {"message": f"Job '{job_id}' exécuté avec succès"}