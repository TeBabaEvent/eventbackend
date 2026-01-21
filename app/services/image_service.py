"""
Image Service - Handles image validation, processing, and storage coordination.
Provides resize, compress, and format conversion capabilities using Pillow.
"""
import io
import logging
from typing import Literal, Tuple, Optional, Set
from fastapi import UploadFile, HTTPException, status
from PIL import Image

from app.services.storage_service import get_storage_provider, generate_unique_filename
from app.core.config import settings

logger = logging.getLogger(__name__)


class ImageValidationError(Exception):
    """Raised when image validation fails"""
    pass


class ImageProcessingError(Exception):
    """Raised when image processing fails"""
    pass


class ImageService:
    """
    Service for image processing and storage.
    Handles validation, resizing, compression, and format conversion.
    """

    # Supported image formats (MIME types)
    ALLOWED_MIME_TYPES: Set[str] = {
        'image/jpeg',
        'image/jpg',
        'image/png',
        'image/webp'
    }

    # Allowed file extensions
    ALLOWED_EXTENSIONS: Set[str] = {'jpg', 'jpeg', 'png', 'webp'}

    # Maximum file size in bytes (default 10MB)
    MAX_FILE_SIZE: int = getattr(settings, 'upload_max_size_mb', 10) * 1024 * 1024

    # Image dimension constraints
    MAX_DIMENSIONS: Tuple[int, int] = (4000, 4000)  # Max input dimensions
    MIN_DIMENSIONS: Tuple[int, int] = (100, 100)    # Min input dimensions

    # Target dimensions for different entity types
    TARGET_DIMENSIONS = {
        'event': (1920, 1080),   # 16:9 landscape for event banners
        'artist': (800, 800)     # Square for artist profiles
    }

    # Output quality
    OUTPUT_QUALITY: int = 85  # WebP quality (1-100)

    def __init__(self):
        """Initialize image service with storage provider"""
        self.storage = get_storage_provider()

    def validate_file(self, file: UploadFile) -> None:
        """
        Validate uploaded file before processing.

        Args:
            file: FastAPI UploadFile object

        Raises:
            HTTPException: If validation fails
        """
        # Check filename exists
        if not file.filename:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Nom de fichier manquant"
            )

        # Check file extension
        extension = file.filename.rsplit('.', 1)[-1].lower() if '.' in file.filename else ''
        if extension not in self.ALLOWED_EXTENSIONS:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Format non autorisé. Formats acceptés: {', '.join(sorted(self.ALLOWED_EXTENSIONS))}"
            )

        # Check MIME type
        if file.content_type and file.content_type.lower() not in self.ALLOWED_MIME_TYPES:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Type de fichier non autorisé: {file.content_type}"
            )

    def validate_file_size(self, content: bytes) -> None:
        """
        Validate file size after reading content.

        Args:
            content: File content as bytes

        Raises:
            HTTPException: If file is too large
        """
        if len(content) > self.MAX_FILE_SIZE:
            max_mb = self.MAX_FILE_SIZE // (1024 * 1024)
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail=f"Fichier trop volumineux. Maximum: {max_mb} MB"
            )

    def validate_image_dimensions(self, image: Image.Image) -> None:
        """
        Validate image dimensions.

        Args:
            image: PIL Image object

        Raises:
            HTTPException: If dimensions are invalid
        """
        width, height = image.size

        # Check minimum dimensions
        if width < self.MIN_DIMENSIONS[0] or height < self.MIN_DIMENSIONS[1]:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Image trop petite. Minimum: {self.MIN_DIMENSIONS[0]}x{self.MIN_DIMENSIONS[1]} pixels"
            )

        # Check maximum dimensions
        if width > self.MAX_DIMENSIONS[0] or height > self.MAX_DIMENSIONS[1]:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Image trop grande. Maximum: {self.MAX_DIMENSIONS[0]}x{self.MAX_DIMENSIONS[1]} pixels"
            )

    def process_image(
        self,
        image: Image.Image,
        max_size: Tuple[int, int],
        quality: int = 85
    ) -> bytes:
        """
        Process image: convert to RGB, resize, and compress as WebP.

        Args:
            image: PIL Image object
            max_size: Maximum (width, height) tuple
            quality: Output quality (1-100)

        Returns:
            Processed image as bytes in WebP format
        """
        # Convert to RGB if necessary (handles RGBA, P, LA modes)
        if image.mode in ('RGBA', 'LA', 'P'):
            # Create white background for transparency
            background = Image.new('RGB', image.size, (255, 255, 255))
            if image.mode == 'P':
                image = image.convert('RGBA')
            if image.mode in ('RGBA', 'LA'):
                # Paste with alpha channel as mask
                alpha = image.split()[-1]
                background.paste(image, mask=alpha)
            else:
                background.paste(image)
            image = background
        elif image.mode != 'RGB':
            image = image.convert('RGB')

        # Resize if larger than max dimensions (maintain aspect ratio)
        if image.width > max_size[0] or image.height > max_size[1]:
            image.thumbnail(max_size, Image.Resampling.LANCZOS)
            logger.debug(f"📐 Image resized to {image.size}")

        # Compress to WebP
        output = io.BytesIO()
        image.save(
            output,
            format='WEBP',
            quality=quality,
            method=4,  # Compression method (0-6, higher = slower but smaller)
            optimize=True
        )

        return output.getvalue()

    async def process_and_save(
        self,
        file: UploadFile,
        entity_type: Literal['event', 'artist'],
        entity_id: str,
        max_size: Optional[Tuple[int, int]] = None,
        quality: Optional[int] = None
    ) -> str:
        """
        Validate, process, and save uploaded image.

        Args:
            file: FastAPI UploadFile object
            entity_type: 'event' or 'artist'
            entity_id: ID of the entity (for filename generation)
            max_size: Optional max dimensions (uses defaults if not provided)
            quality: Optional quality (uses default if not provided)

        Returns:
            Public URL of saved image (e.g., '/uploads/events/event_xxx.webp')

        Raises:
            HTTPException: On validation or processing errors
        """
        # Validate file metadata
        self.validate_file(file)

        # Read file content
        try:
            content = await file.read()
        except Exception as e:
            logger.error(f"❌ Failed to read uploaded file: {e}")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Impossible de lire le fichier"
            )

        # Validate file size
        self.validate_file_size(content)

        # Open and validate image
        try:
            image = Image.open(io.BytesIO(content))
            image.verify()  # Verify it's a valid image

            # Re-open after verify (verify closes the file)
            image = Image.open(io.BytesIO(content))

        except Exception as e:
            logger.error(f"❌ Invalid image file: {e}")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Fichier image invalide ou corrompu"
            )

        # Validate dimensions
        self.validate_image_dimensions(image)

        # Get target dimensions
        target_size = max_size or self.TARGET_DIMENSIONS.get(entity_type, (1200, 1200))
        output_quality = quality or self.OUTPUT_QUALITY

        # Process image
        try:
            processed_content = self.process_image(image, target_size, output_quality)
            logger.info(
                f"📸 Image processed: {len(content)} → {len(processed_content)} bytes "
                f"({100 - (len(processed_content) / len(content) * 100):.1f}% reduction)"
            )

        except Exception as e:
            logger.error(f"❌ Image processing failed: {e}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Erreur lors du traitement de l'image"
            )

        # Generate filename and save
        try:
            filename = generate_unique_filename(entity_type)
            subdir = f"{entity_type}s"  # 'events' or 'artists'

            file_path = await self.storage.save(processed_content, filename, subdir)
            url = self.storage.get_url(file_path)

            logger.info(f"✨ Image saved: {url}")
            return url

        except Exception as e:
            logger.error(f"❌ Failed to save image: {e}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Erreur lors de la sauvegarde de l'image"
            )

    async def delete(self, image_url: str) -> bool:
        """
        Delete image from storage.

        Args:
            image_url: URL of image to delete (e.g., '/uploads/events/xxx.webp')

        Returns:
            True if deleted successfully, False otherwise
        """
        if not image_url:
            return False

        # Extract file path from URL
        base_url = getattr(settings, 'upload_base_url', '/uploads')
        if not image_url.startswith(base_url):
            logger.warning(f"⚠️ Cannot delete external URL: {image_url}")
            return False

        file_path = image_url[len(base_url):].lstrip('/')

        try:
            deleted = await self.storage.delete(file_path)
            if deleted:
                logger.info(f"🗑️ Image deleted: {image_url}")
            return deleted

        except Exception as e:
            logger.error(f"❌ Failed to delete image {image_url}: {e}")
            return False

    def is_local_image(self, image_url: str) -> bool:
        """
        Check if image URL points to local storage.

        Args:
            image_url: URL to check

        Returns:
            True if local storage URL, False if external
        """
        if not image_url:
            return False

        base_url = getattr(settings, 'upload_base_url', '/uploads')
        return image_url.startswith(base_url)


# Singleton instance
_image_service: Optional[ImageService] = None


def get_image_service() -> ImageService:
    """Get image service singleton"""
    global _image_service
    if _image_service is None:
        _image_service = ImageService()
    return _image_service


def reset_image_service() -> None:
    """Reset image service (useful for testing)"""
    global _image_service
    _image_service = None
