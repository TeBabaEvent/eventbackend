"""Configuration de la base de données"""
from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker

from app.core.config import settings

# Créer l'engine SQLAlchemy
engine = create_engine(
    settings.get_database_url(),
    pool_pre_ping=True,  # Vérifie la connexion avant de l'utiliser
    pool_recycle=3600,   # Recycle les connexions toutes les heures
    echo=False,          # Toujours False en production
    pool_size=5,         # Taille du pool de connexions
    max_overflow=10,     # Connexions supplémentaires si nécessaire
    connect_args={
        "connect_timeout": 30,
        "read_timeout": 30,
        "write_timeout": 30
    }
)

# Créer la session
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Base pour les modèles
Base = declarative_base()


def get_db():
    """
    Générateur de session de base de données
    À utiliser avec FastAPI Depends()
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

