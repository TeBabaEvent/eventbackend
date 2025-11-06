#!/usr/bin/env python3
"""
Script pour appliquer les migrations de base de données manuellement.
Usage: python migrate.py
"""

import sys
from app.core.config import settings
from app.db.migrations import auto_migrate

def main():
    print("\n" + "="*60)
    print("  🔄 MIGRATION MANUELLE DE LA BASE DE DONNÉES")
    print("="*60)
    print(f"\n📍 Environnement: {settings.environment}")
    print(f"📍 Base de données: {settings.mysql_host}")
    print()
    
    try:
        auto_migrate()
        print("\n✅ Migrations appliquées avec succès !\n")
        return 0
    except Exception as e:
        print(f"\n❌ Erreur lors de l'application des migrations: {e}\n")
        print("💡 Vérifiez que:")
        print("   - La base de données est accessible")
        print("   - Les credentials sont corrects dans .env")
        print("   - Le fichier .env existe et est correctement configuré")
        print()
        return 1

if __name__ == "__main__":
    sys.exit(main())

