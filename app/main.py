"""Application FastAPI principale"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings
from app.api.v1.router import api_router

# Création de l'application FastAPI
app = FastAPI(
    title="Tebaba Backend API",
    description="API Backend pour l'application Tebaba",
    version="1.0.0"
)

# Configuration CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins.split(","),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Event: Initialisation de la base de données au démarrage
@app.on_event("startup")
async def startup_event():
    """Initialiser la base de données au démarrage"""
    try:
        # Migration automatique (vérification et synchronisation du schéma)
        from app.db.migrations import auto_migrate
        auto_migrate()
    except Exception as e:
        print(f"✗ Erreur lors de l'initialisation: {e}")
        raise


# Routes de base
@app.get("/")
async def root():
    """Route de base"""
    return {"message": "Bienvenue sur l'API Tebaba"}


@app.get("/health")
async def health_check():
    """Vérification de l'état de l'API"""
    return {"status": "healthy"}


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
        reload=True
    )
