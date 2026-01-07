"""
Système de migration automatique de la base de données
Détecte et applique automatiquement les changements de schéma

Fonctionnalités:
- Création/suppression de tables
- Ajout/modification/suppression de colonnes
- Gestion des index
- Gestion des foreign keys
- Mode sécurisé (sans suppressions) pour production
- Rapport détaillé des changements
"""
from sqlalchemy import inspect, text
from sqlalchemy.engine import Inspector
from typing import Dict, Set, List, Tuple, Optional, Any
from dataclasses import dataclass
from datetime import datetime
import logging

from app.db.database import engine, Base
from app.core.config import settings

logger = logging.getLogger(__name__)


# ============== DATA CLASSES ==============

@dataclass
class ColumnInfo:
    """Information sur une colonne"""
    name: str
    type: str
    nullable: bool
    default: Optional[str]
    primary_key: bool = False
    autoincrement: bool = False


@dataclass
class IndexInfo:
    """Information sur un index"""
    name: str
    columns: List[str]
    unique: bool = False


@dataclass
class ForeignKeyInfo:
    """Information sur une foreign key"""
    name: str
    column: str
    referred_table: str
    referred_column: str
    ondelete: Optional[str] = None


@dataclass
class MigrationReport:
    """Rapport de migration"""
    tables_created: List[str]
    tables_dropped: List[str]
    columns_added: Dict[str, List[str]]
    columns_modified: Dict[str, List[str]]
    columns_dropped: Dict[str, List[str]]
    indexes_created: Dict[str, List[str]]
    indexes_dropped: Dict[str, List[str]]
    foreign_keys_created: Dict[str, List[str]]
    foreign_keys_dropped: Dict[str, List[str]]
    errors: List[str]
    
    def __init__(self):
        self.tables_created = []
        self.tables_dropped = []
        self.columns_added = {}
        self.columns_modified = {}
        self.columns_dropped = {}
        self.indexes_created = {}
        self.indexes_dropped = {}
        self.foreign_keys_created = {}
        self.foreign_keys_dropped = {}
        self.errors = []
    
    def has_changes(self) -> bool:
        return (
            self.tables_created or self.tables_dropped or
            self.columns_added or self.columns_modified or self.columns_dropped or
            self.indexes_created or self.indexes_dropped or
            self.foreign_keys_created or self.foreign_keys_dropped
        )
    
    def print_report(self):
        """Affiche le rapport de migration"""
        print("\n" + "=" * 60)
        print("📊 RAPPORT DE MIGRATION")
        print("=" * 60)
        
        if not self.has_changes():
            print("✅ Aucun changement détecté - Base de données à jour")
            return
        
        if self.tables_created:
            print(f"\n✨ Tables créées ({len(self.tables_created)}):")
            for t in self.tables_created:
                print(f"   + {t}")
        
        if self.tables_dropped:
            print(f"\n🗑️  Tables supprimées ({len(self.tables_dropped)}):")
            for t in self.tables_dropped:
                print(f"   - {t}")
        
        for table, cols in self.columns_added.items():
            print(f"\n📝 Colonnes ajoutées dans '{table}':")
            for c in cols:
                print(f"   + {c}")
        
        for table, cols in self.columns_modified.items():
            print(f"\n🔧 Colonnes modifiées dans '{table}':")
            for c in cols:
                print(f"   ~ {c}")
        
        for table, cols in self.columns_dropped.items():
            print(f"\n🗑️  Colonnes supprimées dans '{table}':")
            for c in cols:
                print(f"   - {c}")
        
        for table, idxs in self.indexes_created.items():
            print(f"\n🔍 Index créés dans '{table}':")
            for i in idxs:
                print(f"   + {i}")
        
        for table, idxs in self.indexes_dropped.items():
            print(f"\n🗑️  Index supprimés dans '{table}':")
            for i in idxs:
                print(f"   - {i}")
        
        for table, fks in self.foreign_keys_created.items():
            print(f"\n🔗 Foreign keys créées dans '{table}':")
            for f in fks:
                print(f"   + {f}")
        
        if self.errors:
            print(f"\n⚠️  Erreurs ({len(self.errors)}):")
            for e in self.errors:
                print(f"   ❌ {e}")
        
        print("\n" + "=" * 60)


# ============== INSPECTION FUNCTIONS ==============

def get_inspector() -> Inspector:
    """Récupère l'inspecteur SQLAlchemy"""
    return inspect(engine)


def get_existing_tables() -> Set[str]:
    """Récupère les tables existantes dans la base de données"""
    inspector = get_inspector()
    return set(inspector.get_table_names())


def get_model_tables() -> Set[str]:
    """Récupère les tables définies dans les modèles SQLAlchemy"""
    return set(Base.metadata.tables.keys())


def get_table_columns(table_name: str) -> Dict[str, ColumnInfo]:
    """Récupère les colonnes d'une table existante"""
    inspector = get_inspector()
    columns = {}
    
    try:
        pk_constraint = inspector.get_pk_constraint(table_name)
        pk_columns = set(pk_constraint.get('constrained_columns', []))
    except Exception:
        pk_columns = set()
    
    for col in inspector.get_columns(table_name):
        col_type = str(col['type'])
        columns[col['name']] = ColumnInfo(
            name=col['name'],
            type=col_type,
            nullable=col.get('nullable', True),
            default=str(col.get('default')) if col.get('default') else None,
            primary_key=col['name'] in pk_columns,
            autoincrement=col.get('autoincrement', False)
        )
    
    return columns


def get_model_columns(table_name: str) -> Dict[str, Any]:
    """Récupère les colonnes définies dans le modèle"""
    if table_name not in Base.metadata.tables:
        return {}
    
    table = Base.metadata.tables[table_name]
    columns = {}
    
    for column in table.columns:
        columns[column.name] = column
    
    return columns


def get_table_indexes(table_name: str) -> Dict[str, IndexInfo]:
    """Récupère les index d'une table existante"""
    inspector = get_inspector()
    indexes = {}
    
    try:
        for idx in inspector.get_indexes(table_name):
            indexes[idx['name']] = IndexInfo(
                name=idx['name'],
                columns=idx['column_names'],
                unique=idx.get('unique', False)
            )
    except Exception:
        pass
    
    return indexes


def get_model_indexes(table_name: str) -> Dict[str, IndexInfo]:
    """Récupère les index définis dans le modèle"""
    if table_name not in Base.metadata.tables:
        return {}
    
    table = Base.metadata.tables[table_name]
    indexes = {}
    
    for idx in table.indexes:
        indexes[idx.name] = IndexInfo(
            name=idx.name,
            columns=[c.name for c in idx.columns],
            unique=idx.unique
        )
    
    return indexes


def get_table_foreign_keys(table_name: str) -> Dict[str, ForeignKeyInfo]:
    """Récupère les foreign keys d'une table existante"""
    inspector = get_inspector()
    fks = {}
    
    try:
        for fk in inspector.get_foreign_keys(table_name):
            # Créer un nom basé sur la colonne et la table référencée
            col = fk['constrained_columns'][0] if fk['constrained_columns'] else ''
            ref_table = fk.get('referred_table', '')
            name = fk.get('name') or f"fk_{table_name}_{col}"
            
            fks[name] = ForeignKeyInfo(
                name=name,
                column=col,
                referred_table=ref_table,
                referred_column=fk['referred_columns'][0] if fk.get('referred_columns') else 'id',
                ondelete=fk.get('options', {}).get('ondelete')
            )
    except Exception:
        pass
    
    return fks


def get_model_foreign_keys(table_name: str) -> Dict[str, ForeignKeyInfo]:
    """Récupère les foreign keys définies dans le modèle"""
    if table_name not in Base.metadata.tables:
        return {}
    
    table = Base.metadata.tables[table_name]
    fks = {}
    
    for fk_constraint in table.foreign_key_constraints:
        col = list(fk_constraint.columns)[0].name if fk_constraint.columns else ''
        ref_col = list(fk_constraint.elements)[0].column.name if fk_constraint.elements else 'id'
        ref_table = list(fk_constraint.elements)[0].column.table.name if fk_constraint.elements else ''
        name = fk_constraint.name or f"fk_{table_name}_{col}"
        
        fks[name] = ForeignKeyInfo(
            name=name,
            column=col,
            referred_table=ref_table,
            referred_column=ref_col,
            ondelete=fk_constraint.ondelete
        )
    
    return fks


# ============== COLUMN TYPE MAPPING ==============

def get_mysql_type(column) -> str:
    """Convertit un type SQLAlchemy en type MySQL"""
    col_type = column.type.compile(engine.dialect)
    return col_type


def get_column_default_sql(column) -> str:
    """Génère la clause DEFAULT SQL pour une colonne"""
    if column.default is None:
        return ""
    
    if hasattr(column.default, 'arg'):
        default_val = column.default.arg
        
        # Callable (uuid.uuid4, etc.) - pas de DEFAULT SQL
        if callable(default_val):
            return ""
        
        # Boolean
        if hasattr(column.type, 'python_type') and column.type.python_type == bool:
            return f"DEFAULT {1 if default_val else 0}"
        
        # Integer
        if isinstance(default_val, (int, float)):
            return f"DEFAULT {default_val}"
        
        # String
        return f"DEFAULT '{default_val}'"
    
    return ""


def get_server_default_sql(column) -> str:
    """Génère la clause de server_default SQL"""
    if column.server_default is not None:
        return "DEFAULT CURRENT_TIMESTAMP"
    return ""


# ============== MIGRATION OPERATIONS ==============

def create_tables(tables: Set[str], report: MigrationReport):
    """Crée les nouvelles tables"""
    if not tables:
        return
    
    print(f"\n✨ Création de {len(tables)} nouvelle(s) table(s)...")
    
    try:
        # Créer les tables via SQLAlchemy (gère les dépendances automatiquement)
        Base.metadata.create_all(
            bind=engine,
            tables=[Base.metadata.tables[t] for t in tables]
        )
        report.tables_created.extend(tables)
    except Exception as e:
        report.errors.append(f"Création tables: {e}")
        logger.error(f"Erreur création tables: {e}")


def drop_tables(tables: Set[str], report: MigrationReport):
    """Supprime les tables obsolètes"""
    if not tables:
        return
    
    print(f"\n🗑️  Suppression de {len(tables)} table(s) obsolète(s)...")
    
    with engine.connect() as conn:
        # Désactiver les foreign keys temporairement
        conn.execute(text("SET FOREIGN_KEY_CHECKS = 0"))
        
        for table_name in tables:
            try:
                conn.execute(text(f"DROP TABLE IF EXISTS `{table_name}`"))
                report.tables_dropped.append(table_name)
            except Exception as e:
                report.errors.append(f"Drop table {table_name}: {e}")
                logger.error(f"Erreur drop table {table_name}: {e}")
        
        conn.execute(text("SET FOREIGN_KEY_CHECKS = 1"))
        conn.commit()


def add_column(table_name: str, column, report: MigrationReport):
    """Ajoute une colonne à une table"""
    col_name = column.name
    col_type = get_mysql_type(column)
    nullable = "NULL" if column.nullable else "NOT NULL"
    default = get_column_default_sql(column) or get_server_default_sql(column)
    
    sql = f"ALTER TABLE `{table_name}` ADD COLUMN `{col_name}` {col_type} {nullable} {default}".strip()
    
    with engine.connect() as conn:
        try:
            conn.execute(text(sql))
            conn.commit()
            
            if table_name not in report.columns_added:
                report.columns_added[table_name] = []
            report.columns_added[table_name].append(f"{col_name} ({col_type})")
            
        except Exception as e:
            # Ignorer si la colonne existe déjà
            if "Duplicate column" not in str(e):
                report.errors.append(f"Add column {table_name}.{col_name}: {e}")
                logger.error(f"Erreur add column {table_name}.{col_name}: {e}")


def modify_column(table_name: str, column, existing_col: ColumnInfo, report: MigrationReport):
    """Modifie une colonne existante"""
    col_name = column.name
    col_type = get_mysql_type(column)
    nullable = "NULL" if column.nullable else "NOT NULL"
    default = get_column_default_sql(column) or get_server_default_sql(column)
    
    sql = f"ALTER TABLE `{table_name}` MODIFY COLUMN `{col_name}` {col_type} {nullable} {default}".strip()
    
    with engine.connect() as conn:
        try:
            conn.execute(text(sql))
            conn.commit()
            
            if table_name not in report.columns_modified:
                report.columns_modified[table_name] = []
            report.columns_modified[table_name].append(
                f"{col_name}: {existing_col.type} -> {col_type}"
            )
            
        except Exception as e:
            report.errors.append(f"Modify column {table_name}.{col_name}: {e}")
            logger.error(f"Erreur modify column {table_name}.{col_name}: {e}")


def drop_column(table_name: str, col_name: str, report: MigrationReport):
    """Supprime une colonne d'une table"""
    with engine.connect() as conn:
        try:
            conn.execute(text(f"ALTER TABLE `{table_name}` DROP COLUMN `{col_name}`"))
            conn.commit()
            
            if table_name not in report.columns_dropped:
                report.columns_dropped[table_name] = []
            report.columns_dropped[table_name].append(col_name)
            
        except Exception as e:
            report.errors.append(f"Drop column {table_name}.{col_name}: {e}")
            logger.error(f"Erreur drop column {table_name}.{col_name}: {e}")


def create_index(table_name: str, idx: IndexInfo, report: MigrationReport):
    """Crée un index"""
    unique = "UNIQUE" if idx.unique else ""
    cols = ", ".join([f"`{c}`" for c in idx.columns])
    sql = f"CREATE {unique} INDEX `{idx.name}` ON `{table_name}` ({cols})"
    
    with engine.connect() as conn:
        try:
            conn.execute(text(sql))
            conn.commit()
            
            if table_name not in report.indexes_created:
                report.indexes_created[table_name] = []
            report.indexes_created[table_name].append(idx.name)
            
        except Exception as e:
            # Ignorer si l'index existe déjà
            if "Duplicate key name" not in str(e):
                report.errors.append(f"Create index {table_name}.{idx.name}: {e}")


def drop_index(table_name: str, idx_name: str, report: MigrationReport):
    """Supprime un index"""
    with engine.connect() as conn:
        try:
            conn.execute(text(f"DROP INDEX `{idx_name}` ON `{table_name}`"))
            conn.commit()
            
            if table_name not in report.indexes_dropped:
                report.indexes_dropped[table_name] = []
            report.indexes_dropped[table_name].append(idx_name)
            
        except Exception as e:
            report.errors.append(f"Drop index {table_name}.{idx_name}: {e}")


def create_foreign_key(table_name: str, fk: ForeignKeyInfo, report: MigrationReport):
    """Crée une foreign key"""
    ondelete = f"ON DELETE {fk.ondelete}" if fk.ondelete else ""
    sql = f"""
        ALTER TABLE `{table_name}` 
        ADD CONSTRAINT `{fk.name}` 
        FOREIGN KEY (`{fk.column}`) 
        REFERENCES `{fk.referred_table}` (`{fk.referred_column}`)
        {ondelete}
    """
    
    with engine.connect() as conn:
        try:
            conn.execute(text(sql))
            conn.commit()
            
            if table_name not in report.foreign_keys_created:
                report.foreign_keys_created[table_name] = []
            report.foreign_keys_created[table_name].append(
                f"{fk.name} ({fk.column} -> {fk.referred_table}.{fk.referred_column})"
            )
            
        except Exception as e:
            # Ignorer si la FK existe déjà
            if "Duplicate key name" not in str(e) and "already exists" not in str(e):
                report.errors.append(f"Create FK {table_name}.{fk.name}: {e}")


# ============== COLUMN COMPARISON ==============

def column_needs_modification(model_col, existing_col: ColumnInfo) -> bool:
    """Détermine si une colonne doit être modifiée"""
    # Comparer nullable
    if model_col.nullable != existing_col.nullable:
        return True
    
    # Comparer le type (simplification)
    model_type = get_mysql_type(model_col).upper()
    existing_type = existing_col.type.upper()
    
    # Normaliser les types pour comparaison
    type_mappings = {
        'TINYINT(1)': 'BOOL',
        'BOOLEAN': 'BOOL',
    }
    
    model_type = type_mappings.get(model_type, model_type)
    existing_type = type_mappings.get(existing_type, existing_type)
    
    # Comparer en ignorant les différences mineures (longueur varchar, etc.)
    model_base = model_type.split('(')[0]
    existing_base = existing_type.split('(')[0]
    
    if model_base != existing_base:
        return True
    
    return False


# ============== MAIN MIGRATION FUNCTIONS ==============

def auto_migrate(
    drop_tables_enabled: bool = True,
    drop_columns_enabled: bool = True,
    modify_columns_enabled: bool = True
) -> MigrationReport:
    """
    Migration automatique complète de la base de données.
    
    Args:
        drop_tables_enabled: Supprimer les tables obsolètes
        drop_columns_enabled: Supprimer les colonnes obsolètes
        modify_columns_enabled: Modifier les colonnes existantes
    
    Returns:
        MigrationReport: Rapport détaillé des changements
    """
    print("\n" + "=" * 60)
    print("🔄 MIGRATION AUTOMATIQUE DE LA BASE DE DONNÉES")
    print(f"   {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)
    
    report = MigrationReport()
    
    existing_tables = get_existing_tables()
    model_tables = get_model_tables()
    
    # 1. Créer les nouvelles tables
    new_tables = model_tables - existing_tables
    if new_tables:
        create_tables(new_tables, report)
    
    # 2. Supprimer les tables obsolètes
    if drop_tables_enabled:
        obsolete_tables = existing_tables - model_tables
        # Exclure les tables système ou gérées séparément
        system_tables = {'alembic_version', 'django_migrations'}
        obsolete_tables = obsolete_tables - system_tables
        if obsolete_tables:
            drop_tables(obsolete_tables, report)
    
    # 3. Mettre à jour les tables existantes
    common_tables = existing_tables & model_tables
    
    for table_name in common_tables:
        existing_columns = get_table_columns(table_name)
        model_columns = get_model_columns(table_name)
        
        existing_col_names = set(existing_columns.keys())
        model_col_names = set(model_columns.keys())
        
        # 3a. Ajouter les nouvelles colonnes
        new_columns = model_col_names - existing_col_names
        for col_name in new_columns:
            add_column(table_name, model_columns[col_name], report)
        
        # 3b. Modifier les colonnes existantes (nullable, type)
        if modify_columns_enabled:
            common_columns = existing_col_names & model_col_names
            for col_name in common_columns:
                model_col = model_columns[col_name]
                existing_col = existing_columns[col_name]
                
                # Ne pas modifier les clés primaires
                if existing_col.primary_key:
                    continue
                
                if column_needs_modification(model_col, existing_col):
                    modify_column(table_name, model_col, existing_col, report)
        
        # 3c. Supprimer les colonnes obsolètes
        if drop_columns_enabled:
            obsolete_columns = existing_col_names - model_col_names
            for col_name in obsolete_columns:
                drop_column(table_name, col_name, report)
    
    # 4. Gérer les index (après les colonnes pour éviter les erreurs)
    for table_name in common_tables:
        existing_indexes = get_table_indexes(table_name)
        model_indexes = get_model_indexes(table_name)
        
        # Créer les nouveaux index
        for idx_name, idx in model_indexes.items():
            if idx_name not in existing_indexes:
                create_index(table_name, idx, report)
    
    report.print_report()
    
    if report.errors:
        print(f"\n⚠️  Migration terminée avec {len(report.errors)} erreur(s)")
    else:
        print("\n✅ MIGRATION TERMINÉE AVEC SUCCÈS")
    
    print("=" * 60 + "\n")
    
    return report


def sync_schema() -> MigrationReport:
    """
    Synchronisation simple du schéma (mode sécurisé pour production).
    
    - Crée les nouvelles tables
    - Ajoute les nouvelles colonnes
    - NE supprime PAS les tables/colonnes existantes
    
    Returns:
        MigrationReport: Rapport détaillé des changements
    """
    print("\n" + "=" * 60)
    print("🔄 SYNCHRONISATION DU SCHÉMA (MODE SÉCURISÉ)")
    print(f"   {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)
    
    report = MigrationReport()
    
    # Créer ou mettre à jour les tables via SQLAlchemy
    # (ne supprime rien, ajoute uniquement)
    try:
        Base.metadata.create_all(bind=engine)
    except Exception as e:
        report.errors.append(f"create_all: {e}")
        logger.error(f"Erreur create_all: {e}")
    
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
        for col_name in new_columns:
            add_column(table_name, model_columns[col_name], report)
    
    report.print_report()
    print("\n✅ SYNCHRONISATION TERMINÉE")
    print("=" * 60 + "\n")
    
    return report


def fix_column_constraints() -> MigrationReport:
    """
    Corrige les contraintes de colonnes pour correspondre aux modèles.
    Notamment les changements de nullable, types, etc.
    
    Returns:
        MigrationReport: Rapport détaillé des changements
    """
    print("\n" + "=" * 60)
    print("🔧 CORRECTION DES CONTRAINTES DE COLONNES")
    print("=" * 60)
    
    report = MigrationReport()
    
    existing_tables = get_existing_tables()
    model_tables = get_model_tables()
    common_tables = existing_tables & model_tables
    
    for table_name in common_tables:
        existing_columns = get_table_columns(table_name)
        model_columns = get_model_columns(table_name)
        
        common_col_names = set(existing_columns.keys()) & set(model_columns.keys())
        
        for col_name in common_col_names:
            model_col = model_columns[col_name]
            existing_col = existing_columns[col_name]
            
            # Ne pas modifier les clés primaires
            if existing_col.primary_key:
                continue
            
            if column_needs_modification(model_col, existing_col):
                modify_column(table_name, model_col, existing_col, report)
    
    report.print_report()
    print("\n✅ CORRECTION TERMINÉE")
    print("=" * 60 + "\n")
    
    return report


def check_schema_diff() -> MigrationReport:
    """
    Analyse les différences entre le schéma actuel et les modèles.
    N'effectue aucune modification, affiche uniquement le rapport.
    
    Returns:
        MigrationReport: Rapport des différences détectées
    """
    print("\n" + "=" * 60)
    print("🔍 ANALYSE DES DIFFÉRENCES DE SCHÉMA")
    print(f"   {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)
    
    report = MigrationReport()
    
    existing_tables = get_existing_tables()
    model_tables = get_model_tables()
    
    # Tables à créer
    new_tables = model_tables - existing_tables
    report.tables_created = list(new_tables)
    
    # Tables à supprimer
    system_tables = {'alembic_version', 'django_migrations'}
    obsolete_tables = existing_tables - model_tables - system_tables
    report.tables_dropped = list(obsolete_tables)
    
    # Colonnes
    common_tables = existing_tables & model_tables
    
    for table_name in common_tables:
        existing_columns = get_table_columns(table_name)
        model_columns = get_model_columns(table_name)
        
        existing_col_names = set(existing_columns.keys())
        model_col_names = set(model_columns.keys())
        
        # Colonnes à ajouter
        new_cols = model_col_names - existing_col_names
        if new_cols:
            report.columns_added[table_name] = list(new_cols)
        
        # Colonnes à supprimer
        obsolete_cols = existing_col_names - model_col_names
        if obsolete_cols:
            report.columns_dropped[table_name] = list(obsolete_cols)
        
        # Colonnes à modifier
        common_cols = existing_col_names & model_col_names
        modified = []
        for col_name in common_cols:
            model_col = model_columns[col_name]
            existing_col = existing_columns[col_name]
            
            if not existing_col.primary_key and column_needs_modification(model_col, existing_col):
                modified.append(f"{col_name}: {existing_col.type} -> {get_mysql_type(model_col)}")
        
        if modified:
            report.columns_modified[table_name] = modified
        
        # Index
        existing_indexes = get_table_indexes(table_name)
        model_indexes = get_model_indexes(table_name)
        
        new_indexes = set(model_indexes.keys()) - set(existing_indexes.keys())
        if new_indexes:
            report.indexes_created[table_name] = list(new_indexes)
    
    report.print_report()
    
    if not report.has_changes():
        print("\n✅ Base de données synchronisée avec les modèles")
    else:
        print("\n⚠️  Des différences ont été détectées")
        print("   Exécutez 'auto_migrate()' pour appliquer les changements")
    
    print("=" * 60 + "\n")
    
    return report


# ============== CLI INTERFACE ==============

if __name__ == "__main__":
    """Permet d'exécuter les migrations avec: python -m app.db.migrations"""
    import sys
    
    print("\n" + "=" * 60)
    print("🔧 OUTIL DE MIGRATION DE BASE DE DONNÉES")
    print("=" * 60)
    
    print("\n📋 Options disponibles:")
    print("  1. Analyser les différences (lecture seule)")
    print("  2. Synchronisation simple (ajouts uniquement - recommandé)")
    print("  3. Corriger les contraintes de colonnes")
    print("  4. Migration complète (avec suppressions - ATTENTION)")
    print("  0. Annuler")
    
    choice = input("\n👉 Votre choix (défaut=1): ").strip() or "1"
    
    try:
        if choice == "1":
            check_schema_diff()
        elif choice == "2":
            sync_schema()
        elif choice == "3":
            fix_column_constraints()
        elif choice == "4":
            confirm = input("\n⚠️  Cela supprimera les tables/colonnes obsolètes. Confirmer? (oui/non): ")
            if confirm.lower() == "oui":
                auto_migrate()
            else:
                print("\n❌ Opération annulée")
        elif choice == "0":
            print("\n👋 Annulé")
        else:
            print("\n❌ Option invalide")
            sys.exit(1)
        
        sys.exit(0)
        
    except Exception as e:
        print(f"\n❌ Erreur: {e}")
        logger.exception("Erreur migration")
        sys.exit(1)
