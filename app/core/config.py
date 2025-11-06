from pydantic_settings import BaseSettings
from pydantic import ConfigDict
from typing import Optional

class Settings(BaseSettings):
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
    
    # Optionnel: URL complète de la base de données
    database_url: Optional[str] = None
    
    # Server configuration
    host: str = "127.0.0.1"
    port: int = 8000
    
    # CORS
    cors_origins: str = "http://localhost:5173,http://localhost:3000"
    
    model_config = ConfigDict(
        env_file=".env",
        extra='ignore'  # Ignore les champs supplémentaires dans .env
    )
    
    def get_database_url(self) -> str:
        """Construire l'URL de la base de données"""
        if self.database_url:
            return self.database_url
        return f"mysql+pymysql://{self.mysql_user}:{self.mysql_password}@{self.mysql_host}:{self.mysql_port}/{self.mysql_database}"

settings = Settings()

