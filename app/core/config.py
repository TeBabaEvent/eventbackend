from pydantic_settings import BaseSettings
from pydantic import ConfigDict, field_validator
from typing import Optional, Literal
import os

class Settings(BaseSettings):
    # Environment - PRODUCTION PAR DÉFAUT
    environment: Literal["development", "production", "staging"] = "development"
    
    # JWT Configuration
    secret_key: str
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 15  # ✅ Short-lived for security
    refresh_token_expire_days: int = 7  # ✅ Refresh token lifetime

    # Cookie Configuration
    cookie_secure: bool = False  # ✅ Set to True in production (HTTPS only)
    cookie_samesite: str = "lax"  # ✅ CSRF protection
    
    # MySQL Database Configuration
    mysql_host: str = "localhost"
    mysql_port: int = 3306
    mysql_user: str = "root"
    mysql_password: str = ""
    mysql_database: str = "railway"
    
    # Optionnel: URL complète de la base de données (prioritaire si fournie)
    database_url: Optional[str] = None
    
    # Server configuration
    host: str = "0.0.0.0"
    port: int = 8000
    
    # CORS - DOIT ÊTRE DÉFINI EN PRODUCTION
    cors_origins: str
    
    # Debug mode
    debug: bool = False
    
    # Migrations automatiques au démarrage (désactivées par défaut)
    auto_migrate_on_startup: bool = False

    # Mollie Payment Provider
    mollie_api_key: Optional[str] = None

    # JWT Secret Key pour QR codes (séparée de SECRET_KEY)
    jwt_secret_key: Optional[str] = None

    # URLs pour paiement (OBLIGATOIRES en production)
    base_url: str = "https://eventbackend-production-039e.up.railway.app"
    frontend_url: str = "https://www.baba.events"

    @field_validator('frontend_url', 'base_url')
    @classmethod
    def validate_urls_not_localhost_in_production(cls, v: str, info) -> str:
        """Empêcher localhost en production"""
        import os
        env = os.getenv('ENVIRONMENT', 'development')
        if env == 'production' and 'localhost' in v.lower():
            raise ValueError(
                f"⚠️  ERREUR: {info.field_name.upper()} ne peut pas contenir 'localhost' en production! "
                f"Définissez {info.field_name.upper()} avec votre URL de production."
            )
        return v

    # Gmail SMTP
    gmail_address: Optional[str] = None
    gmail_app_password: Optional[str] = None
    email_from_name: str = "BABA Event"

    model_config = ConfigDict(
        env_file=".env",
        env_file_encoding='utf-8',
        extra='ignore',  # Ignore les champs supplémentaires dans .env
        case_sensitive=False,
        # IMPORTANT : Charger depuis les variables d'environnement système en priorité
        env_nested_delimiter='__'
    )
    
    @field_validator('secret_key')
    @classmethod
    def validate_secret_key(cls, v: str) -> str:
        """Valider que la clé secrète est définie"""
        if not v or len(v) < 32:
            raise ValueError(
                "⚠️  ERREUR DE SÉCURITÉ: SECRET_KEY doit faire au moins 32 caractères! "
                "Générez une clé sécurisée avec: openssl rand -hex 32"
            )
        return v
    
    @field_validator('cors_origins')
    @classmethod
    def validate_cors_origins(cls, v: str) -> str:
        """Valider les origines CORS"""
        if not v:
            raise ValueError(
                "⚠️  ERREUR DE SÉCURITÉ: CORS_ORIGINS doit être défini en production! "
                "Ne laissez jamais CORS ouvert à tous (*) en production."
            )
        # Avertir si localhost est utilisé en production
        if "localhost" in v.lower():
            import logging
            logging.warning("⚠️ ATTENTION: CORS contient 'localhost' - êtes-vous en production?")
        return v

    @field_validator('jwt_secret_key')
    @classmethod
    def validate_jwt_secret_key(cls, v: Optional[str]) -> Optional[str]:
        """Valider la clé JWT pour les QR codes"""
        if v and len(v) < 32:
            raise ValueError(
                "⚠️  ERREUR DE SÉCURITÉ: JWT_SECRET_KEY doit faire au moins 32 caractères! "
                "Générez une clé sécurisée avec: openssl rand -hex 32"
            )
        return v

    def get_database_url(self) -> str:
        """Construire l'URL de la base de données"""
        # Priorité à DATABASE_URL si fournie (typique pour Railway, Heroku, etc.)
        if self.database_url:
            # S'assurer que l'URL utilise pymysql
            if self.database_url.startswith("mysql://"):
                return self.database_url.replace("mysql://", "mysql+pymysql://", 1)
            return self.database_url
        
        # Sinon construire depuis les composants individuels
        return f"mysql+pymysql://{self.mysql_user}:{self.mysql_password}@{self.mysql_host}:{self.mysql_port}/{self.mysql_database}"
    
    @property
    def is_production(self) -> bool:
        """Vérifier si on est en production"""
        return self.environment == "production"
    
    @property
    def is_development(self) -> bool:
        """Vérifier si on est en développement"""
        return self.environment == "development"

settings = Settings()

