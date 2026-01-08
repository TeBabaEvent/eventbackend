#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Script unique pour générer les slugs des événements existants.
Usage: python generate_slugs.py

Ce script doit être exécuté une seule fois après la migration de la colonne slug.
"""

import sys
import io
from app.core.config import settings
from app.db.database import SessionLocal
from app.db import models
from app.utils.slugify import generate_unique_slug

# Fix encoding for Windows console
if sys.platform == 'win32':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')


def main():
    print("\n" + "="*60)
    print("  GENERATION DES SLUGS POUR LES EVENEMENTS EXISTANTS")
    print("="*60)
    print(f"\nEnvironnement: {settings.environment}")
    print()

    db = SessionLocal()
    try:
        # Récupérer tous les événements sans slug
        events_without_slug = db.query(models.Event).filter(
            (models.Event.slug == None) | (models.Event.slug == "")
        ).all()
        
        print(f"Evenements sans slug: {len(events_without_slug)}")
        
        if not events_without_slug:
            print("\nTous les evenements ont deja un slug. Rien a faire.")
            return 0
        
        for event in events_without_slug:
            # Générer un slug unique
            slug = generate_unique_slug(event.title, event.date, db, event.id)
            event.slug = slug
            print(f"  - {event.title[:40]:<40} -> {slug}")
        
        db.commit()
        print(f"\n{len(events_without_slug)} slugs generes avec succes !")
        return 0
        
    except Exception as e:
        db.rollback()
        print(f"\nErreur lors de la generation des slugs: {e}")
        return 1
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())

