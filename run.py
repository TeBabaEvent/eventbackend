"""
Script de démarrage de l'application BABA Event Backend
Lance le serveur uvicorn avec la configuration appropriée
POUR DÉVELOPPEMENT LOCAL UNIQUEMENT - En production, utilisez systemd/gunicorn
"""
import uvicorn
from app.core.config import settings

if __name__ == "__main__":
    # Ce script est pour le développement local uniquement
    if settings.is_production:
        print("⚠️ ATTENTION: Vous essayez de lancer le serveur en mode production avec run.py")
        print("⚠️ En production, utilisez systemd avec gunicorn (voir /etc/systemd/system/baba-backend.service)")
        exit(1)
    
    uvicorn.run(
        "app.main:app",
        host=settings.host,
        port=settings.port,
        reload=True  # Reload activé pour développement
    )
