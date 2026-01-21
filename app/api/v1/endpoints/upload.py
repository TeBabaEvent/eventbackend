"""
Routes pour l'upload d'images - Clean Architecture.
Endpoints dédiés par type d'entité (event, artist).
"""
import logging
from fastapi import APIRouter, Depends, HTTPException, status, Path, UploadFile, File
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.db import models
from app.schemas.upload import ImageUploadResponse, ImageDeleteResponse
from app.api.deps import require_admin
from app.services.image_service import get_image_service

logger = logging.getLogger(__name__)

router = APIRouter()


# =============================================================================
# EVENT IMAGE ENDPOINTS
# =============================================================================

@router.post(
    "/event/{event_id}/image",
    response_model=ImageUploadResponse,
    status_code=status.HTTP_200_OK,
    summary="Upload une image pour un événement",
    description="Upload et traite une image pour un événement. Admin seulement."
)
async def upload_event_image(
    event_id: str = Path(..., description="ID de l'événement (UUID)", min_length=36, max_length=36),
    file: UploadFile = File(..., description="Image à uploader (JPEG, PNG, WebP - max 10MB)"),
    db: Session = Depends(get_db),
    _: None = Depends(require_admin)
):
    """
    Upload une image pour un événement (admin seulement).

    - Valide le format et la taille du fichier
    - Redimensionne à 1920x1080 max (format 16:9)
    - Compresse en WebP
    - Supprime l'ancienne image si elle existe
    """
    # Vérifier que l'événement existe
    event = db.query(models.Event).filter(models.Event.id == event_id).first()
    if not event:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Événement non trouvé"
        )

    try:
        image_service = get_image_service()

        # Supprimer l'ancienne image si elle existe et est locale
        if event.image_url and image_service.is_local_image(event.image_url):
            await image_service.delete(event.image_url)
            logger.info(f"🔄 Old image deleted for event {event_id}")

        # Traiter et sauvegarder la nouvelle image
        image_url = await image_service.process_and_save(
            file=file,
            entity_type="event",
            entity_id=event_id,
            max_size=(1920, 1080),
            quality=85
        )

        # Mettre à jour la base de données
        event.image_url = image_url
        db.commit()

        logger.info(f"✨ Event image uploaded: {event.title} (ID: {event_id})")
        return ImageUploadResponse(image_url=image_url)

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"❌ Error uploading event image {event_id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Erreur lors du téléchargement de l'image"
        )


@router.delete(
    "/event/{event_id}/image",
    response_model=ImageDeleteResponse,
    summary="Supprimer l'image d'un événement",
    description="Supprime l'image d'un événement. Admin seulement."
)
async def delete_event_image(
    event_id: str = Path(..., description="ID de l'événement (UUID)", min_length=36, max_length=36),
    db: Session = Depends(get_db),
    _: None = Depends(require_admin)
):
    """Supprimer l'image d'un événement (admin seulement)"""
    # Vérifier que l'événement existe
    event = db.query(models.Event).filter(models.Event.id == event_id).first()
    if not event:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Événement non trouvé"
        )

    if not event.image_url:
        return ImageDeleteResponse(success=False, message="Aucune image à supprimer")

    try:
        image_service = get_image_service()

        # Supprimer le fichier si c'est une image locale
        deleted = False
        if image_service.is_local_image(event.image_url):
            deleted = await image_service.delete(event.image_url)

        # Mettre à jour la base de données
        event.image_url = None
        db.commit()

        logger.info(f"🗑️ Event image deleted: {event.title} (ID: {event_id})")
        return ImageDeleteResponse(
            success=True,
            message="Image supprimée avec succès"
        )

    except Exception as e:
        db.rollback()
        logger.error(f"❌ Error deleting event image {event_id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Erreur lors de la suppression de l'image"
        )


# =============================================================================
# ARTIST IMAGE ENDPOINTS
# =============================================================================

@router.post(
    "/artist/{artist_id}/image",
    response_model=ImageUploadResponse,
    status_code=status.HTTP_200_OK,
    summary="Upload une image pour un artiste",
    description="Upload et traite une image pour un artiste. Admin seulement."
)
async def upload_artist_image(
    artist_id: str = Path(..., description="ID de l'artiste (UUID)", min_length=36, max_length=36),
    file: UploadFile = File(..., description="Image à uploader (JPEG, PNG, WebP - max 10MB)"),
    db: Session = Depends(get_db),
    _: None = Depends(require_admin)
):
    """
    Upload une image pour un artiste (admin seulement).

    - Valide le format et la taille du fichier
    - Redimensionne à 800x800 max (format carré)
    - Compresse en WebP
    - Supprime l'ancienne image si elle existe
    """
    # Vérifier que l'artiste existe
    artist = db.query(models.Artist).filter(models.Artist.id == artist_id).first()
    if not artist:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Artiste non trouvé"
        )

    try:
        image_service = get_image_service()

        # Supprimer l'ancienne image si elle existe et est locale
        if artist.image_url and image_service.is_local_image(artist.image_url):
            await image_service.delete(artist.image_url)
            logger.info(f"🔄 Old image deleted for artist {artist_id}")

        # Traiter et sauvegarder la nouvelle image
        image_url = await image_service.process_and_save(
            file=file,
            entity_type="artist",
            entity_id=artist_id,
            max_size=(800, 800),
            quality=85
        )

        # Mettre à jour la base de données
        artist.image_url = image_url
        db.commit()

        logger.info(f"✨ Artist image uploaded: {artist.name} (ID: {artist_id})")
        return ImageUploadResponse(image_url=image_url)

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"❌ Error uploading artist image {artist_id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Erreur lors du téléchargement de l'image"
        )


@router.delete(
    "/artist/{artist_id}/image",
    response_model=ImageDeleteResponse,
    summary="Supprimer l'image d'un artiste",
    description="Supprime l'image d'un artiste. Admin seulement."
)
async def delete_artist_image(
    artist_id: str = Path(..., description="ID de l'artiste (UUID)", min_length=36, max_length=36),
    db: Session = Depends(get_db),
    _: None = Depends(require_admin)
):
    """Supprimer l'image d'un artiste (admin seulement)"""
    # Vérifier que l'artiste existe
    artist = db.query(models.Artist).filter(models.Artist.id == artist_id).first()
    if not artist:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Artiste non trouvé"
        )

    if not artist.image_url:
        return ImageDeleteResponse(success=False, message="Aucune image à supprimer")

    try:
        image_service = get_image_service()

        # Supprimer le fichier si c'est une image locale
        deleted = False
        if image_service.is_local_image(artist.image_url):
            deleted = await image_service.delete(artist.image_url)

        # Mettre à jour la base de données
        artist.image_url = None
        db.commit()

        logger.info(f"🗑️ Artist image deleted: {artist.name} (ID: {artist_id})")
        return ImageDeleteResponse(
            success=True,
            message="Image supprimée avec succès"
        )

    except Exception as e:
        db.rollback()
        logger.error(f"❌ Error deleting artist image {artist_id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Erreur lors de la suppression de l'image"
        )
