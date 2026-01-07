"""
Service de tâches planifiées (CRON jobs)

Ce module gère les jobs périodiques pour:
- Récupérer les tickets non générés (toutes les 5 minutes)
- Nettoyer les commandes expirées (toutes les 10 minutes)
- Mettre à jour le statut des événements passés (tous les jours à 00:05)
- Vérifier l'état du système (toutes les heures)
"""
import logging
import asyncio
from datetime import date
from typing import Optional
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from apscheduler.triggers.cron import CronTrigger

from app.core.config import settings

logger = logging.getLogger(__name__)

# Instance globale du scheduler
scheduler: Optional[AsyncIOScheduler] = None


def get_scheduler() -> AsyncIOScheduler:
    """Retourne l'instance du scheduler"""
    global scheduler
    if scheduler is None:
        scheduler = AsyncIOScheduler()
    return scheduler


async def job_recover_missing_tickets():
    """
    Job: Récupérer les commandes completed sans tickets générés.
    
    Exécuté toutes les 5 minutes.
    """
    try:
        from app.services.order_recovery_service import recover_missing_tickets
        
        logger.debug("🔄 [CRON] Vérification tickets manquants...")
        result = await recover_missing_tickets()
        
        if result["recovered"] > 0 or result["failed"] > 0:
            logger.info(
                f"🔄 [CRON] Récupération: {result['recovered']} récupérées, "
                f"{result['failed']} échecs"
            )
    except Exception as e:
        logger.exception(f"❌ [CRON] Erreur récupération tickets: {e}")


async def job_cleanup_expired_orders():
    """
    Job: Marquer comme expirées les commandes pending qui ont dépassé le timeout.
    
    Exécuté toutes les 10 minutes.
    """
    try:
        from app.services.order_recovery_service import cleanup_expired_orders
        
        logger.debug("🧹 [CRON] Nettoyage commandes expirées...")
        result = await cleanup_expired_orders()
        
        if result["expired"] > 0:
            logger.info(f"🧹 [CRON] {result['expired']} commandes marquées comme expirées")
    except Exception as e:
        logger.exception(f"❌ [CRON] Erreur nettoyage expirées: {e}")


async def job_health_check():
    """
    Job: Vérification de l'état du système et statistiques.
    
    Exécuté toutes les heures.
    """
    try:
        from app.services.order_recovery_service import get_recovery_stats
        
        stats = await get_recovery_stats()
        
        # Logger uniquement si des problèmes sont détectés
        if stats["missing_tickets"] > 0:
            logger.warning(
                f"⚠️ [CRON] {stats['missing_tickets']} commandes sans tickets!"
            )
        
        if stats["expired_pending"] > 0:
            logger.info(
                f"📊 [CRON] Stats: {stats['expired_pending']} expirées à nettoyer, "
                f"{stats['active_pending']} pending actives"
            )
    except Exception as e:
        logger.exception(f"❌ [CRON] Erreur health check: {e}")


async def job_update_past_events():
    """
    Job: Met à jour le statut des événements passés.
    
    Un événement est considéré comme passé si sa date est strictement 
    antérieure à aujourd'hui.
    
    Exécuté tous les jours à 00:05.
    """
    try:
        from app.db.database import SessionLocal
        from app.db import models
        
        db = SessionLocal()
        try:
            today = date.today().isoformat()
            
            # Mettre à jour tous les événements passés en une seule requête
            updated = db.query(models.Event).filter(
                models.Event.date < today,
                models.Event.status == "upcoming"
            ).update({"status": "past"}, synchronize_session=False)
            
            db.commit()
            
            if updated > 0:
                logger.info(f"📅 [CRON] {updated} événement(s) marqué(s) comme passé(s)")
        finally:
            db.close()
            
    except Exception as e:
        logger.exception(f"❌ [CRON] Erreur mise à jour événements: {e}")


def start_scheduler():
    """
    Démarre le scheduler avec tous les jobs configurés.
    
    Jobs configurés:
    - Récupération tickets: toutes les 5 minutes
    - Nettoyage expirées: toutes les 10 minutes  
    - Health check: toutes les heures
    """
    global scheduler
    
    # Ne pas démarrer en mode test
    if settings.environment == "test":
        logger.info("⏭️ [CRON] Scheduler désactivé en mode test")
        return
    
    scheduler = get_scheduler()
    
    # Job 1: Récupérer les tickets manquants (toutes les 5 minutes)
    scheduler.add_job(
        job_recover_missing_tickets,
        trigger=IntervalTrigger(minutes=5),
        id="recover_missing_tickets",
        name="Récupérer tickets manquants",
        replace_existing=True,
        max_instances=1,  # Évite les exécutions concurrentes
    )
    
    # Job 2: Nettoyer les commandes expirées (toutes les 10 minutes)
    scheduler.add_job(
        job_cleanup_expired_orders,
        trigger=IntervalTrigger(minutes=10),
        id="cleanup_expired_orders",
        name="Nettoyer commandes expirées",
        replace_existing=True,
        max_instances=1,
    )
    
    # Job 3: Health check système (toutes les heures)
    scheduler.add_job(
        job_health_check,
        trigger=IntervalTrigger(hours=1),
        id="system_health_check",
        name="Vérification système",
        replace_existing=True,
        max_instances=1,
    )
    
    # Job 4: Mise à jour des événements passés (tous les jours à 00:05)
    scheduler.add_job(
        job_update_past_events,
        trigger=CronTrigger(hour=0, minute=5),
        id="update_past_events",
        name="Mise à jour événements passés",
        replace_existing=True,
        max_instances=1,
    )
    
    # Démarrer le scheduler
    scheduler.start()
    
    logger.info("✅ [CRON] Scheduler démarré avec 4 jobs:")
    logger.info("   📋 recover_missing_tickets: toutes les 5 minutes")
    logger.info("   🧹 cleanup_expired_orders: toutes les 10 minutes")
    logger.info("   💓 system_health_check: toutes les heures")
    logger.info("   📅 update_past_events: tous les jours à 00:05")


def stop_scheduler():
    """Arrête le scheduler proprement"""
    global scheduler
    
    if scheduler and scheduler.running:
        scheduler.shutdown(wait=False)
        logger.info("🛑 [CRON] Scheduler arrêté")


def get_scheduler_status() -> dict:
    """
    Retourne le statut du scheduler et de ses jobs.
    
    Returns:
        dict avec l'état du scheduler et la liste des jobs
    """
    global scheduler
    
    if scheduler is None:
        return {"running": False, "jobs": []}
    
    jobs = []
    for job in scheduler.get_jobs():
        jobs.append({
            "id": job.id,
            "name": job.name,
            "next_run_time": job.next_run_time.isoformat() if job.next_run_time else None,
            "trigger": str(job.trigger),
        })
    
    return {
        "running": scheduler.running,
        "jobs": jobs
    }

