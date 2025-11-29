"""Application FastAPI principale"""
import logging
from contextlib import asynccontextmanager
from datetime import datetime

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, HTMLResponse
from fastapi.exceptions import RequestValidationError
from sqlalchemy import text

from app.core.config import settings
from app.api.v1.router import api_router
from app.db.database import engine

# Configuration du logging
logging.basicConfig(
    level=logging.INFO if settings.is_production else logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Gestionnaire du cycle de vie de l'application"""
    # Startup
    logger.info(f"🚀 Démarrage de l'API Tebaba en mode {settings.environment}")
    logger.info(f"🌐 CORS Origins: {settings.cors_origins}")
    
    # Debug: Afficher l'URL de DB (masquée partiellement)
    db_url = settings.get_database_url()
    if "localhost" in db_url:
        logger.warning("⚠️ ATTENTION: L'app se connecte à LOCALHOST!")
        logger.warning("⚠️ Vérifiez que DATABASE_URL est bien configurée dans Railway")
    else:
        logger.info(f"📊 Connexion DB configurée (host: {settings.mysql_host if not settings.database_url else 'depuis DATABASE_URL'})")
    
    # Migrations désactivées par défaut - utilisez python migrate.py pour les appliquer
    if settings.auto_migrate_on_startup:
        logger.info("🔄 Migrations automatiques activées")
        try:
            from app.db.migrations import auto_migrate
            auto_migrate()
            logger.info("✅ Base de données initialisée avec succès")
        except Exception as e:
            logger.warning(f"⚠️ Erreur lors des migrations: {e}")
            logger.warning("⚠️ L'application démarre quand même")
    else:
        logger.info("⏭️ Migrations automatiques désactivées")
        logger.info("💡 Pour appliquer les migrations: python migrate.py")
    
    yield
    
    # Shutdown
    logger.info("🛑 Arrêt de l'API Tebaba")
    try:
        engine.dispose()
    except Exception as e:
        logger.warning(f"⚠️ Erreur lors de la fermeture de la connexion DB: {e}")


# Création de l'application FastAPI
app = FastAPI(
    title="Tebaba Backend API",
    description="API Backend pour l'application Tebaba",
    version="1.0.0",
    docs_url="/docs" if not settings.is_production else None,
    redoc_url="/redoc" if not settings.is_production else None,
    lifespan=lifespan
)


# Configuration CORS
origins = [origin.strip() for origin in settings.cors_origins.split(",") if origin.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins if origins else ["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Middleware pour logger les requêtes
@app.middleware("http")
async def log_requests(request: Request, call_next):
    """Logger toutes les requêtes HTTP"""
    start_time = datetime.now()
    
    # Log de la requête entrante
    logger.info(f"➡️  {request.method} {request.url.path}")
    
    response = await call_next(request)
    
    # Log de la réponse
    process_time = (datetime.now() - start_time).total_seconds()
    logger.info(
        f"⬅️  {request.method} {request.url.path} "
        f"- Status: {response.status_code} - Time: {process_time:.3f}s"
    )
    
    return response


# Gestionnaire d'erreurs de validation
@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    """Gérer les erreurs de validation"""
    logger.warning(f"❌ Erreur de validation sur {request.url.path}: {exc.errors()}")
    return JSONResponse(
        status_code=422,
        content={
            "detail": exc.errors(),
            "message": "Erreur de validation des données"
        }
    )


# Gestionnaire d'erreurs génériques
@app.exception_handler(Exception)
async def generic_exception_handler(request: Request, exc: Exception):
    """Gérer les erreurs non capturées"""
    logger.error(f"❌ Erreur non gérée sur {request.url.path}: {str(exc)}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content={
            "message": "Une erreur interne est survenue",
            "detail": str(exc) if settings.debug else "Erreur interne du serveur"
        }
    )


# Routes de base
@app.get("/")
async def root():
    """Route de base"""
    return {
        "message": "Bienvenue sur l'API Tebaba",
        "version": "1.0.0",
        "environment": settings.environment,
        "status": "online"
    }


@app.get("/health")
async def health_check():
    """Vérification de l'état de l'API et de la connexion à la base de données"""
    try:
        # Vérifier la connexion à la base de données
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        
        return {
            "status": "healthy",
            "environment": settings.environment,
            "database": "connected",
            "timestamp": datetime.now().isoformat()
        }
    except Exception as e:
        logger.error(f"❌ Health check échoué: {e}")
        return JSONResponse(
            status_code=503,
            content={
                "status": "unhealthy",
                "environment": settings.environment,
                "database": "disconnected",
                "error": str(e),
                "timestamp": datetime.now().isoformat()
            }
        )


# Inclure le router API v1
app.include_router(api_router, prefix="/api")


# ============================================
# OPEN GRAPH META TAGS FOR SOCIAL SHARING
# ============================================

# Translations for OG meta tags
OG_TRANSLATIONS = {
    "fr": {
        "tickets_from": "À partir de",
        "default_event": "Événement Baba Event",
        "exclusive_event": "Événement exclusif",
        "locale": "fr_FR"
    },
    "en": {
        "tickets_from": "From",
        "default_event": "Baba Event",
        "exclusive_event": "Exclusive event",
        "locale": "en_US"
    },
    "nl": {
        "tickets_from": "Vanaf",
        "default_event": "Baba Evenement",
        "exclusive_event": "Exclusief evenement",
        "locale": "nl_NL"
    },
    "sq": {
        "tickets_from": "Nga",
        "default_event": "Baba Event",
        "exclusive_event": "Event ekskluziv",
        "locale": "sq_AL"
    }
}

@app.get("/og/events/{event_id}", response_class=HTMLResponse)
async def get_event_og_meta(event_id: str, request: Request, lang: str = "fr"):
    """
    Génère une page HTML avec les meta tags OpenGraph pour le partage social.
    Facebook, Twitter et autres crawlers utilisent ces meta tags pour créer les aperçus.
    
    Args:
        event_id: ID de l'événement
        lang: Langue pour les meta tags (fr, en, nl, sq)
    """
    from sqlalchemy.orm import joinedload
    from app.db.database import SessionLocal
    from app.db import models
    
    # Validate language
    if lang not in OG_TRANSLATIONS:
        lang = "fr"
    
    translations = OG_TRANSLATIONS[lang]
    
    db = SessionLocal()
    try:
        event = db.query(models.Event).options(
            joinedload(models.Event.pack_associations).joinedload(models.EventPack.pack)
        ).filter(models.Event.id == event_id).first()
        
        if not event:
            return HTMLResponse(content="<html><head><title>Event not found</title></head><body>Event not found</body></html>", status_code=404)
        
        # Get event details based on language
        # title_translations and description_translations are JSON: {"fr": "", "en": "", "nl": "", "sq": ""}
        title_trans = event.title_translations or {}
        desc_trans = event.description_translations or {}
        
        # Get title in requested language, fallback to main title
        title = title_trans.get(lang) or title_trans.get("fr") or title_trans.get("en") or event.title or translations["default_event"]
        
        # Get description in requested language, fallback to main description
        description = desc_trans.get(lang) or desc_trans.get("fr") or desc_trans.get("en") or event.description or f"{title} - {translations['exclusive_event']}"
        
        image_url = event.image_url or "https://www.baba.events/logo.svg"
        
        # Format date
        event_date = ""
        if event.date:
            try:
                from datetime import datetime
                if isinstance(event.date, str):
                    date_obj = datetime.strptime(event.date, "%Y-%m-%d")
                else:
                    date_obj = event.date
                event_date = date_obj.strftime("%d/%m/%Y")
            except:
                event_date = str(event.date)
        
        location = f"{event.location or ''}, {event.city or ''}".strip(", ")
        
        # Get minimum price
        min_price = None
        if event.pack_associations:
            prices = [pa.pack.price for pa in event.pack_associations if pa.pack and not pa.is_soldout]
            if prices:
                min_price = min(prices)
        
        # Build description with event details (no emojis for a professional look)
        og_description = event_date if event_date else ""
        if event.time:
            og_description += f" | {event.time}"
        if location:
            og_description += f" | {location}"
        if min_price:
            og_description += f" | {translations['tickets_from']} {min_price}€"
        if not og_description:
            og_description = description[:200] if description else translations["exclusive_event"]
        
        # Frontend URL
        frontend_url = settings.cors_origins.split(",")[0].strip() if settings.cors_origins else "https://www.baba.events"
        event_url = f"{frontend_url}/events/{event_id}"
        
        # Generate HTML with meta tags
        html_content = f"""<!DOCTYPE html>
<html lang="{lang}">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    
    <!-- Primary Meta Tags -->
    <title>{title} | Baba Event</title>
    <meta name="title" content="{title} | Baba Event">
    <meta name="description" content="{og_description}">
    
    <!-- Open Graph / Facebook -->
    <meta property="og:type" content="event">
    <meta property="og:url" content="{event_url}">
    <meta property="og:title" content="{title}">
    <meta property="og:description" content="{og_description}">
    <meta property="og:image" content="{image_url}">
    <meta property="og:image:width" content="1200">
    <meta property="og:image:height" content="630">
    <meta property="og:site_name" content="Baba Event">
    <meta property="og:locale" content="{translations['locale']}">
    
    <!-- Twitter -->
    <meta name="twitter:card" content="summary_large_image">
    <meta name="twitter:url" content="{event_url}">
    <meta name="twitter:title" content="{title}">
    <meta name="twitter:description" content="{og_description}">
    <meta name="twitter:image" content="{image_url}">
    
    <!-- Redirect to the actual event page -->
    <meta http-equiv="refresh" content="0; url={event_url}">
    <link rel="canonical" href="{event_url}">
</head>
<body>
    <p>Redirection vers l'événement...</p>
    <p>Si vous n'êtes pas redirigé automatiquement, <a href="{event_url}">cliquez ici</a>.</p>
</body>
</html>"""
        
        return HTMLResponse(content=html_content)
    finally:
        db.close()


# Route admin (maintenue pour compatibilité)
@app.get("/admin/dashboard")
async def admin_dashboard():
    """Route protégée pour le dashboard admin"""
    return {"message": "Dashboard admin"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "app.main:app", 
        host=settings.host, 
        port=settings.port, 
        reload=settings.is_development  # Reload seulement en développement
    )
