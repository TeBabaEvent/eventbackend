"""Router principal API v1"""
from fastapi import APIRouter

from app.api.v1.endpoints import auth, artists, packs, events

api_router = APIRouter()

# Routes d'authentification
api_router.include_router(auth.router, prefix="/auth", tags=["Authentification"])

# Routes des ressources
api_router.include_router(artists.router, prefix="/artists", tags=["Artistes"])
api_router.include_router(packs.router, prefix="/packs", tags=["Packs"])
api_router.include_router(events.router, prefix="/events", tags=["Événements"])

