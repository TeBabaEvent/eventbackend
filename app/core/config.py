from pydantic_settings import BaseSettings
from pydantic import ConfigDict, field_validator
from typing import Optional, Literal
import os

class Settings(BaseSettings):
    # Environment
    environment: Literal["development", "production", "staging"] = "development"
    
    # JWT Configuration
    secret_key: str = "your-secret-key-here-change-this-in-production"
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 30
    
    # MySQL Database Configuration
    mysql_host: str = "localhost"
    mysql_port: int = 3306
    mysql_user: str = "root"
    mysql_password: str = ""
    mysql_database: str = "babaevent"
    
    # Optionnel: URL complète de la base de données (prioritaire si fournie)
    database_url: Optional[str] = None
    
    # Server configuration
    host: str = "0.0.0.0"
    port: int = 8000
    
    # CORS
    cors_origins: str = "http://localhost:5173,http://localhost:3000"
    
    # Debug mode
    debug: bool = False
    
    model_config = ConfigDict(
        env_file=".env",
        extra='ignore',  # Ignore les champs supplémentaires dans .env
        case_sensitive=False
    )
    
    @field_validator('secret_key')
    @classmethod
    def validate_secret_key(cls, v: str, info) -> str:
        """Valider que la clé secrète n'est pas la valeur par défaut en production"""
        if info.data.get('environment') == 'production':
            if v == "your-secret-key-here-change-this-in-production":
                raise ValueError(
                    "⚠️  ERREUR DE SÉCURITÉ: Vous devez changer SECRET_KEY en production! "
                    "Générez une clé sécurisée avec: openssl rand -hex 32"
                )
        return v
    
    @field_validator('cors_origins')
    @classmethod
    def validate_cors_origins(cls, v: str) -> str:
        """Valider les origines CORS"""
        if not v:
            return "*"
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

