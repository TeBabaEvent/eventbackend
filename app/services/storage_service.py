"""
Storage Service - Abstract interface for file storage operations.
Supports local filesystem with easy migration to cloud storage (S3, Cloudflare, etc.)
"""
import os
import logging
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Optional
import uuid
from datetime import datetime

from app.core.config import settings

logger = logging.getLogger(__name__)


class StorageProvider(ABC):
    """Abstract interface for file storage - enables easy cloud migration"""

    @abstractmethod
    async def save(self, file_content: bytes, filename: str, subdir: str) -> str:
        """
        Save file and return relative path.

        Args:
            file_content: Raw bytes of the file
            filename: Name of the file to save
            subdir: Subdirectory (e.g., 'events', 'artists')

        Returns:
            Relative path from storage root (e.g., 'events/abc123.webp')
        """
        pass

    @abstractmethod
    async def delete(self, file_path: str) -> bool:
        """
        Delete file from storage.

        Args:
            file_path: Relative path to delete

        Returns:
            True if deleted successfully, False otherwise
        """
        pass

    @abstractmethod
    def get_url(self, file_path: str) -> str:
        """
        Convert file path to public URL.

        Args:
            file_path: Relative path in storage

        Returns:
            Full URL accessible from frontend
        """
        pass

    @abstractmethod
    def exists(self, file_path: str) -> bool:
        """Check if file exists in storage"""
        pass


class LocalStorageProvider(StorageProvider):
    """Local filesystem storage implementation for OVH VPS"""

    def __init__(self, base_dir: Optional[str] = None, base_url: Optional[str] = None):
        """
        Initialize local storage provider.

        Args:
            base_dir: Base directory for uploads (default: from settings)
            base_url: Base URL for serving files (default: /uploads)
        """
        self.base_dir = Path(base_dir or getattr(settings, 'upload_dir', 'uploads'))
        self.base_url = base_url or getattr(settings, 'upload_base_url', '/uploads')

        # If relative path, make it relative to app root
        if not self.base_dir.is_absolute():
            app_root = Path(__file__).parent.parent.parent
            self.base_dir = app_root / self.base_dir

        # Ensure base directory exists
        self._ensure_directories()

        logger.info(f"📁 LocalStorageProvider initialized: {self.base_dir}")

    def _ensure_directories(self) -> None:
        """Create required directories if they don't exist"""
        subdirs = ['events', 'artists']
        for subdir in subdirs:
            dir_path = self.base_dir / subdir
            dir_path.mkdir(parents=True, exist_ok=True)
            logger.debug(f"📂 Ensured directory exists: {dir_path}")

    async def save(self, file_content: bytes, filename: str, subdir: str) -> str:
        """Save file to local filesystem"""
        # Sanitize subdir to prevent path traversal
        safe_subdir = self._sanitize_path(subdir)
        safe_filename = self._sanitize_filename(filename)

        # Target directory and file path
        target_dir = self.base_dir / safe_subdir
        target_dir.mkdir(parents=True, exist_ok=True)

        file_path = target_dir / safe_filename

        # Write file
        try:
            with open(file_path, 'wb') as f:
                f.write(file_content)

            relative_path = f"{safe_subdir}/{safe_filename}"
            logger.info(f"✅ File saved: {relative_path} ({len(file_content)} bytes)")
            return relative_path

        except IOError as e:
            logger.error(f"❌ Failed to save file: {e}")
            raise

    async def delete(self, file_path: str) -> bool:
        """Delete file from filesystem"""
        try:
            # Sanitize path
            safe_path = self._sanitize_path(file_path)
            full_path = self.base_dir / safe_path

            # Security check: ensure path is within base_dir
            if not self._is_safe_path(full_path):
                logger.warning(f"⚠️ Attempted path traversal: {file_path}")
                return False

            if full_path.exists() and full_path.is_file():
                full_path.unlink()
                logger.info(f"🗑️ File deleted: {safe_path}")
                return True
            else:
                logger.warning(f"⚠️ File not found for deletion: {safe_path}")
                return False

        except Exception as e:
            logger.error(f"❌ Failed to delete {file_path}: {e}")
            return False

    def get_url(self, file_path: str) -> str:
        """Convert file path to URL"""
        # Clean the path
        clean_path = file_path.lstrip('/')
        return f"{self.base_url}/{clean_path}"

    def exists(self, file_path: str) -> bool:
        """Check if file exists"""
        safe_path = self._sanitize_path(file_path)
        full_path = self.base_dir / safe_path
        return full_path.exists() and full_path.is_file()

    def _sanitize_path(self, path: str) -> str:
        """Sanitize path to prevent directory traversal"""
        # Remove any path traversal attempts
        safe_path = path.replace('..', '').replace('//', '/')
        safe_path = safe_path.lstrip('/')
        return safe_path

    def _sanitize_filename(self, filename: str) -> str:
        """Sanitize filename to prevent injection"""
        # Keep only safe characters
        safe_chars = set('abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_.')
        sanitized = ''.join(c if c in safe_chars else '_' for c in filename)
        return sanitized

    def _is_safe_path(self, path: Path) -> bool:
        """Check if resolved path is within base directory"""
        try:
            resolved = path.resolve()
            base_resolved = self.base_dir.resolve()
            return str(resolved).startswith(str(base_resolved))
        except Exception:
            return False


def generate_unique_filename(prefix: str, extension: str = 'webp') -> str:
    """
    Generate a unique filename for uploaded images.

    Args:
        prefix: Prefix for the filename (e.g., 'event', 'artist')
        extension: File extension (default: webp)

    Returns:
        Unique filename like 'event_20240115_143022_a1b2c3d4.webp'
    """
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    unique_id = str(uuid.uuid4())[:8]
    return f"{prefix}_{timestamp}_{unique_id}.{extension}"


# Singleton instance
_storage_provider: Optional[StorageProvider] = None


def get_storage_provider() -> StorageProvider:
    """
    Get the storage provider singleton.
    Currently returns LocalStorageProvider.
    Can be extended to return S3, Cloudflare, etc. based on config.
    """
    global _storage_provider
    if _storage_provider is None:
        _storage_provider = LocalStorageProvider()
    return _storage_provider


def reset_storage_provider() -> None:
    """Reset storage provider (useful for testing)"""
    global _storage_provider
    _storage_provider = None
