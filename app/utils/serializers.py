"""Fonctions de sérialisation pour convertir les modèles DB en dictionnaires"""
from app.db import models


def serialize_event(db_event: models.Event) -> dict:
    """Sérialiser un événement avec toutes ses associations"""
    
    # Sérialiser les artistes avec leurs infos de timing
    artists = []
    for assoc in db_event.artist_associations:
        artist_dict = {
            "id": assoc.artist.id,
            "name": assoc.artist.name,
            "role": assoc.artist.role,
            "role_translations": assoc.artist.role_translations,
            "description": assoc.artist.description,
            "description_translations": assoc.artist.description_translations,
            "image_url": assoc.artist.image_url,
            "events_count": assoc.artist.events_count,
            "badge": assoc.artist.badge,
            "instagram": assoc.artist.instagram,
            "created_at": assoc.artist.created_at,
            "updated_at": assoc.artist.updated_at,
            # Infos spécifiques à cet événement
            "start_time": assoc.start_time,
            "end_time": assoc.end_time,
            "order": assoc.order
        }
        artists.append(artist_dict)
    
    # Trier les artistes par ordre
    artists.sort(key=lambda x: x.get("order", 0))
    
    # Sérialiser les packs avec leur statut soldout
    packs = []
    for assoc in db_event.pack_associations:
        pack_dict = {
            "id": assoc.pack.id,
            "name": assoc.pack.name,
            "name_translations": assoc.pack.name_translations,
            "type": assoc.pack.type,
            "description": assoc.pack.description,
            "description_translations": assoc.pack.description_translations,
            "price": assoc.pack.price,
            "currency": assoc.pack.currency,
            "unit": assoc.pack.unit,
            "features": assoc.pack.features,
            "features_translations": assoc.pack.features_translations,
            "is_active": assoc.pack.is_active,
            "created_at": assoc.pack.created_at,
            "updated_at": assoc.pack.updated_at,
            # Info spécifique à cet événement
            "is_soldout": assoc.is_soldout
        }
        packs.append(pack_dict)
    
    # Retourner le dict complet de l'événement
    return {
        "id": db_event.id,
        "title": db_event.title,
        "title_translations": db_event.title_translations,
        "description": db_event.description,
        "description_translations": db_event.description_translations,
        "category": db_event.category,
        "date": db_event.date,
        "time": db_event.time,
        "location": db_event.location,
        "address": db_event.address,
        "city": db_event.city,
        "maps_embed_url": db_event.maps_embed_url,
        "image_url": db_event.image_url,
        "capacity": db_event.capacity,
        "featured": db_event.featured,
        "status": db_event.status,
        "created_at": db_event.created_at,
        "updated_at": db_event.updated_at,
        "artists": artists,
        "packs": packs
    }

