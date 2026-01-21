"""Router principal API v1"""
from fastapi import APIRouter

from app.api.v1.endpoints import auth, artists, packs, events, checkout, webhooks, scan, admin, upload

api_router = APIRouter()

# Routes d'authentification
api_router.include_router(auth.router, prefix="/auth", tags=["Authentification"])

# Routes des ressources
api_router.include_router(artists.router, prefix="/artists", tags=["Artistes"])
api_router.include_router(packs.router, prefix="/packs", tags=["Packs"])
api_router.include_router(events.router, prefix="/events", tags=["Événements"])

# Routes de billetterie
api_router.include_router(checkout.router, prefix="/checkout", tags=["Paiement"])
api_router.include_router(webhooks.router, prefix="/webhooks", tags=["Webhooks"])

# Routes de scan/validation
api_router.include_router(scan.router, prefix="/scan", tags=["Scan"])

# Routes d'administration
api_router.include_router(admin.router, prefix="/admin", tags=["Administration"])

# Routes d'upload d'images
api_router.include_router(upload.router, prefix="/upload", tags=["Upload"])

