"""Utilitaires pour la génération de slugs URL-friendly"""
import re
import unicodedata
from typing import Optional
from sqlalchemy.orm import Session


def slugify(text: str) -> str:
    """
    Convertit un texte en slug URL-friendly.
    
    Exemple: "Soirée Électro à Bruxelles!" -> "soiree-electro-a-bruxelles"
    """
    if not text:
        return ""
    
    # Normaliser les caractères unicode (é -> e, etc.)
    text = unicodedata.normalize('NFKD', text)
    text = text.encode('ascii', 'ignore').decode('ascii')
    
    # Convertir en minuscules
    text = text.lower()
    
    # Remplacer les espaces et caractères spéciaux par des tirets
    text = re.sub(r'[^a-z0-9]+', '-', text)
    
    # Supprimer les tirets en début et fin
    text = text.strip('-')
    
    # Réduire les tirets multiples
    text = re.sub(r'-+', '-', text)
    
    return text


def generate_unique_slug(
    title: str,
    date: Optional[str],
    db: Session,
    event_id: Optional[str] = None
) -> str:
    """
    Génère un slug unique pour un événement.
    
    Format: {title-slug}-{date} ou {title-slug}-{date}-{n} si collision
    
    Args:
        title: Titre de l'événement
        date: Date au format YYYY-MM-DD (optionnel)
        db: Session SQLAlchemy
        event_id: ID de l'événement (pour les updates, exclure soi-même)
    
    Returns:
        Slug unique
    """
    from app.db import models
    
    # Créer le slug de base
    base_slug = slugify(title)
    
    # Ajouter la date si disponible pour plus d'unicité
    if date:
        # Format: soiree-electro-2026-01-15
        base_slug = f"{base_slug}-{date}"
    
    # Vérifier l'unicité
    slug = base_slug
    counter = 1
    
    while True:
        # Chercher un événement avec ce slug
        query = db.query(models.Event).filter(models.Event.slug == slug)
        
        # Exclure l'événement actuel si c'est une mise à jour
        if event_id:
            query = query.filter(models.Event.id != event_id)
        
        existing = query.first()
        
        if not existing:
            return slug
        
        # Collision: ajouter un compteur
        counter += 1
        slug = f"{base_slug}-{counter}"
        
        # Sécurité: éviter boucle infinie
        if counter > 100:
            # Fallback: utiliser une partie de l'UUID
            import uuid
            slug = f"{base_slug}-{str(uuid.uuid4())[:8]}"
            return slug

