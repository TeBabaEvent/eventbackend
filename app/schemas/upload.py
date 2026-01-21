"""
Schemas for image upload endpoints.
"""
from pydantic import BaseModel


class ImageUploadResponse(BaseModel):
    """Response after successful image upload"""
    image_url: str
    message: str = "Image téléchargée avec succès"

    class Config:
        json_schema_extra = {
            "example": {
                "image_url": "/uploads/events/event_20240115_143022_a1b2c3d4.webp",
                "message": "Image téléchargée avec succès"
            }
        }


class ImageDeleteResponse(BaseModel):
    """Response after image deletion"""
    success: bool
    message: str

    class Config:
        json_schema_extra = {
            "example": {
                "success": True,
                "message": "Image supprimée avec succès"
            }
        }
