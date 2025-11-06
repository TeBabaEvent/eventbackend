"""
Système de migration automatique de la base de données
Détecte et applique automatiquement les changements de schéma
"""
from sqlalchemy import inspect, text
from sqlalchemy.engine import reflection
from app.db.database import engine, Base
from app.core.config import settings


def get_existing_tables() -> set:
    """Récupérer les tables existantes dans la base de données"""
    inspector = inspect(engine)
    return set(inspector.get_table_names())


def get_model_tables() -> set:
    """Récupérer les tables définies dans les modèles SQLAlchemy"""
    return set(Base.metadata.tables.keys())


def get_table_columns(table_name: str) -> dict:
    """Récupérer les colonnes d'une table existante"""
    inspector = inspect(engine)
    columns = {}
    for column in inspector.get_columns(table_name):
        columns[column['name']] = column
    return columns


def get_model_columns(table_name: str) -> dict:
    """Récupérer les colonnes définies dans le modèle"""
    if table_name not in Base.metadata.tables:
        return {}
    
    table = Base.metadata.tables[table_name]
    columns = {}
    for column in table.columns:
        columns[column.name] = column
    return columns


def auto_migrate():
    """
    Migration automatique de la base de données
    - Crée les nouvelles tables
    - Ajoute les nouvelles colonnes
    - Supprime les tables obsolètes
    - Supprime les colonnes obsolètes
    """
    print("="*60)
    print("🔄 MIGRATION AUTOMATIQUE DE LA BASE DE DONNÉES")
    print("="*60)
    
    existing_tables = get_existing_tables()
    model_tables = get_model_tables()
    
    # 1. Créer les nouvelles tables
    new_tables = model_tables - existing_tables
    if new_tables:
        print(f"\n✨ Création de {len(new_tables)} nouvelle(s) table(s):")
        for table_name in new_tables:
            print(f"   + {table_name}")
        Base.metadata.create_all(bind=engine, tables=[
            Base.metadata.tables[t] for t in new_tables
        ])
        print("✓ Nouvelles tables créées")
    
    # 2. Supprimer les tables obsolètes
    obsolete_tables = existing_tables - model_tables
    if obsolete_tables:
        print(f"\n🗑️  Suppression de {len(obsolete_tables)} table(s) obsolète(s):")
        with engine.connect() as conn:
            conn.execute(text("SET FOREIGN_KEY_CHECKS = 0"))
            for table_name in obsolete_tables:
                print(f"   - {table_name}")
                conn.execute(text(f"DROP TABLE IF EXISTS `{table_name}`"))
            conn.execute(text("SET FOREIGN_KEY_CHECKS = 1"))
            conn.commit()
        print("✓ Tables obsolètes supprimées")
    
    # 3. Mettre à jour les tables existantes (ajouter/supprimer colonnes)
    common_tables = existing_tables & model_tables
    for table_name in common_tables:
        existing_columns = get_table_columns(table_name)
        model_columns = get_model_columns(table_name)
        
        existing_col_names = set(existing_columns.keys())
        model_col_names = set(model_columns.keys())
        
        # Ajouter les nouvelles colonnes
        new_columns = model_col_names - existing_col_names
        if new_columns:
            print(f"\n📝 Ajout de colonnes dans '{table_name}':")
            with engine.connect() as conn:
                for col_name in new_columns:
                    col = model_columns[col_name]
                    col_type = col.type.compile(engine.dialect)
                    nullable = "NULL" if col.nullable else "NOT NULL"
                    default = ""
                    
                    if col.default is not None:
                        if hasattr(col.default, 'arg'):
                            if callable(col.default.arg):
                                # Pour les defaults comme uuid.uuid4
                                default = ""
                            else:
                                # Gestion spéciale pour les BOOLEAN
                                if col.type.python_type == bool:
                                    default = f"DEFAULT {1 if col.default.arg else 0}"
                                else:
                                    default = f"DEFAULT '{col.default.arg}'"
                        else:
                            # Gestion spéciale pour les BOOLEAN
                            if col.type.python_type == bool:
                                default = f"DEFAULT {1 if col.default else 0}"
                            else:
                                default = f"DEFAULT '{col.default}'"
                    
                    print(f"   + {col_name} ({col_type})")
                    sql = f"ALTER TABLE `{table_name}` ADD COLUMN `{col_name}` {col_type} {nullable} {default}"
                    try:
                        conn.execute(text(sql))
                    except Exception as e:
                        print(f"   ⚠️  Erreur lors de l'ajout de {col_name}: {e}")
                conn.commit()
        
        # Supprimer les colonnes obsolètes
        obsolete_columns = existing_col_names - model_col_names
        if obsolete_columns:
            print(f"\n🗑️  Suppression de colonnes dans '{table_name}':")
            with engine.connect() as conn:
                for col_name in obsolete_columns:
                    print(f"   - {col_name}")
                    try:
                        conn.execute(text(f"ALTER TABLE `{table_name}` DROP COLUMN `{col_name}`"))
                    except Exception as e:
                        print(f"   ⚠️  Erreur lors de la suppression de {col_name}: {e}")
                conn.commit()
    
    print("\n" + "="*60)
    print("✅ MIGRATION TERMINÉE")
    print("="*60 + "\n")


def sync_schema():
    """
    Synchronisation simple du schéma (sans suppression)
    Plus sûr pour la production
    """
    print("="*60)
    print("🔄 SYNCHRONISATION DU SCHÉMA")
    print("="*60)
    
    # Créer ou mettre à jour les tables
    Base.metadata.create_all(bind=engine)
    
    existing_tables = get_existing_tables()
    model_tables = get_model_tables()
    
    # Ajouter uniquement les nouvelles colonnes (pas de suppression)
    common_tables = existing_tables & model_tables
    for table_name in common_tables:
        existing_columns = get_table_columns(table_name)
        model_columns = get_model_columns(table_name)
        
        existing_col_names = set(existing_columns.keys())
        model_col_names = set(model_columns.keys())
        
        # Ajouter les nouvelles colonnes
        new_columns = model_col_names - existing_col_names
        if new_columns:
            print(f"\n📝 Ajout de colonnes dans '{table_name}':")
            with engine.connect() as conn:
                for col_name in new_columns:
                    col = model_columns[col_name]
                    col_type = col.type.compile(engine.dialect)
                    nullable = "NULL" if col.nullable else "NOT NULL"
                    default = ""
                    
                    if col.default is not None:
                        if hasattr(col.default, 'arg'):
                            if callable(col.default.arg):
                                default = ""
                            else:
                                # Gestion spéciale pour les BOOLEAN
                                if col.type.python_type == bool:
                                    default = f"DEFAULT {1 if col.default.arg else 0}"
                                else:
                                    default = f"DEFAULT '{col.default.arg}'"
                    
                    print(f"   + {col_name} ({col_type})")
                    sql = f"ALTER TABLE `{table_name}` ADD COLUMN `{col_name}` {col_type} {nullable} {default}"
                    try:
                        conn.execute(text(sql))
                    except Exception as e:
                        print(f"   ⚠️  Erreur: {e}")
                conn.commit()
    
    print("\n✅ Synchronisation terminée\n")


if __name__ == "__main__":
    """Permet d'exécuter les migrations avec: python -m app.db.migrations"""
    import sys
    
    print("\n📋 Options disponibles:")
    print("  1. Migration complète (avec suppressions)")
    print("  2. Synchronisation simple (sans suppressions - recommandé)")
    
    choice = input("\n👉 Votre choix (1 ou 2, défaut=2): ").strip() or "2"
    
    try:
        if choice == "1":
            auto_migrate()
        else:
            sync_schema()
        sys.exit(0)
    except Exception as e:
        print(f"\n❌ Erreur: {e}\n")
        sys.exit(1)
