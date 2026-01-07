#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Script pour appliquer les migrations de base de données manuellement.
Usage: python migrate.py
"""

import sys
import io
from app.core.config import settings
from app.db.migrations import auto_migrate

# Fix encoding for Windows console
if sys.platform == 'win32':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

def main():
    print("\n" + "="*60)
    print("  MIGRATION MANUELLE DE LA BASE DE DONNEES")
    print("="*60)
    print(f"\nEnvironnement: {settings.environment}")
    print(f"Base de donnees: {settings.mysql_host}")
    print()

    try:
        auto_migrate()
        print("\nMigrations appliquees avec succes !\n")
        return 0
    except Exception as e:
        print(f"\nErreur lors de l'application des migrations: {e}\n")
        print("Verifiez que:")
        print("   - La base de donnees est accessible")
        print("   - Les credentials sont corrects dans .env")
        print("   - Le fichier .env existe et est correctement configure")
        print()
        return 1

if __name__ == "__main__":
    sys.exit(main())

