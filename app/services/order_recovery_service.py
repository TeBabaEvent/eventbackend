"""Service de récupération des commandes et nettoyage"""
import logging
from datetime import datetime, timedelta, timezone
from sqlalchemy.orm import Session
from sqlalchemy import and_

from app.db.database import SessionLocal
from app.db import models

logger = logging.getLogger(__name__)


async def recover_missing_tickets():
    """
    Récupère les commandes completed sans tickets générés.
    
    Ce job doit être exécuté périodiquement (ex: toutes les 5 minutes)
    pour s'assurer que tous les clients ayant payé reçoivent leurs tickets.
    
    Returns:
        dict: Statistiques de récupération
    """
    from app.services.ticket_service import generate_tickets_for_order
    from app.services.pdf_service import generate_individual_ticket_pdfs, delete_pdf_file
    from app.services.email_service import send_confirmation_email
    
    db = SessionLocal()
    recovered = 0
    failed = 0
    
    try:
        # Trouver les commandes completed sans tickets générés
        orders = db.query(models.Order).filter(
            and_(
                models.Order.status == "completed",
                models.Order.tickets_generated == False
            )
        ).all()
        
        if not orders:
            logger.info("Aucune commande à récupérer")
            return {"recovered": 0, "failed": 0}
        
        logger.warning(f"🔄 {len(orders)} commandes à récupérer")
        
        for order in orders:
            try:
                logger.info(f"Récupération de {order.order_number}")
                
                # 1. Générer les tickets
                tickets = await generate_tickets_for_order(order, db)
                
                # 2. Marquer comme généré
                order.tickets_generated = True
                db.commit()
                
                # 3. Générer les PDFs individuels
                pdf_paths = []
                try:
                    pdf_paths = await generate_individual_ticket_pdfs(tickets, order)
                except Exception as e:
                    logger.error(f"Erreur PDFs pour {order.order_number}: {e}")
                    pdf_paths = []
                
                # 4. Envoyer l'email
                if pdf_paths:
                    email_sent = False
                    try:
                        await send_confirmation_email(
                            to_email=order.customer_email,
                            customer_name=order.customer_name,
                            order=order,
                            tickets=tickets,
                            pdf_paths=pdf_paths
                        )
                        logger.info(f"✓ {order.order_number} récupéré avec succès")
                        email_sent = True
                    except Exception as e:
                        logger.error(f"Erreur email pour {order.order_number}: {e}")

                    # 5. Nettoyer les PDFs après envoi réussi
                    if email_sent:
                        for pdf_path in pdf_paths:
                            delete_pdf_file(pdf_path)

                recovered += 1
                
            except Exception as e:
                db.rollback()
                logger.exception(f"Erreur récupération {order.order_number}: {e}")
                failed += 1
        
        return {"recovered": recovered, "failed": failed}
    
    except Exception as e:
        db.rollback()
        logger.exception(f"Erreur globale récupération des tickets: {e}")
        raise
    finally:
        db.close()


async def cleanup_expired_orders():
    """
    Marque comme 'expired' les commandes pending qui ont dépassé leur timeout.
    
    Ce job doit être exécuté périodiquement (ex: toutes les 10 minutes).
    
    Returns:
        dict: Statistiques de nettoyage
    """
    db = SessionLocal()
    expired_count = 0
    
    try:
        now = datetime.now(timezone.utc)
        
        # Trouver les commandes pending expirées
        expired_orders = db.query(models.Order).filter(
            and_(
                models.Order.status == "pending",
                models.Order.expires_at != None,
                models.Order.expires_at < now
            )
        ).all()
        
        if not expired_orders:
            logger.debug("Aucune commande expirée à nettoyer")
            return {"expired": 0}
        
        logger.info(f"🧹 {len(expired_orders)} commandes pending expirées")
        
        for order in expired_orders:
            order.status = "expired"
            expired_count += 1
            logger.info(f"Commande {order.order_number} marquée comme expirée")
        
        db.commit()
        
        return {"expired": expired_count}
    
    except Exception as e:
        db.rollback()
        logger.exception(f"Erreur nettoyage commandes expirées: {e}")
        raise
    finally:
        db.close()


async def get_recovery_stats():
    """
    Retourne les statistiques de commandes nécessitant une récupération.
    
    Returns:
        dict: Statistiques
    """
    db = SessionLocal()
    
    try:
        # Commandes completed sans tickets
        missing_tickets = db.query(models.Order).filter(
            and_(
                models.Order.status == "completed",
                models.Order.tickets_generated == False
            )
        ).count()
        
        # Commandes pending potentiellement expirées
        now = datetime.now(timezone.utc)
        expired_pending = db.query(models.Order).filter(
            and_(
                models.Order.status == "pending",
                models.Order.expires_at != None,
                models.Order.expires_at < now
            )
        ).count()
        
        # Commandes pending actives
        active_pending = db.query(models.Order).filter(
            and_(
                models.Order.status == "pending",
                (models.Order.expires_at == None) | (models.Order.expires_at >= now)
            )
        ).count()
        
        return {
            "missing_tickets": missing_tickets,
            "expired_pending": expired_pending,
            "active_pending": active_pending
        }
        
    finally:
        db.close()

