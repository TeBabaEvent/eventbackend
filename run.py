"""
Script de démarrage de l'application Tebaba Backend
Lance le serveur uvicorn avec la configuration appropriée
"""
import uvicorn
from app.core.config import settings

if __name__ == "__main__":
    uvicorn.run(
        "app.main:app",
        host=settings.host,
        port=settings.port,
        reload=True  # Active le rechargement automatique en développement
    )
