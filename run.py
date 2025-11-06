"""
Script de démarrage de l'application Tebaba Backend
Lance le serveur uvicorn avec la configuration appropriée
POUR DÉVELOPPEMENT LOCAL UNIQUEMENT - En production, utilisez Procfile
"""
import uvicorn
from app.core.config import settings

if __name__ == "__main__":
    # Ce script est pour le développement local uniquement
    if settings.is_production:
        print("⚠️ ATTENTION: Vous essayez de lancer le serveur en mode production avec run.py")
        print("⚠️ En production, utilisez: uvicorn app.main:app --host 0.0.0.0 --port $PORT --workers 2")
        print("⚠️ Ou laissez Railway utiliser le Procfile")
        exit(1)
    
    uvicorn.run(
        "app.main:app",
        host=settings.host,
        port=settings.port,
        reload=True  # Reload activé pour développement
    )
