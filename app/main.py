"""Application FastAPI principale"""
import logging
from contextlib import asynccontextmanager
from datetime import datetime

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
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
