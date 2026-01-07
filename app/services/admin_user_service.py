"""Service pour la gestion des utilisateurs admin - Single Responsibility"""
from sqlalchemy.orm import Session
from sqlalchemy import or_
from typing import Dict, Any, List, Optional
import logging

from app.db import models
from app.core.security import get_password_hash

logger = logging.getLogger(__name__)


class AdminUserService:
    """Service dédié à la gestion des utilisateurs admin"""
    
    def __init__(self, db: Session):
        self.db = db
    
    def get_users(
        self,
        role: Optional[str] = None,
        is_active: Optional[bool] = None,
        search: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """Récupère la liste des utilisateurs avec filtres"""
        query = self.db.query(models.User)
        
        if role:
            query = query.filter(models.User.role == role)
        if is_active is not None:
            query = query.filter(models.User.is_active == is_active)
        if search:
            pattern = f"%{search}%"
            query = query.filter(
                or_(
                    models.User.username.ilike(pattern),
                    models.User.email.ilike(pattern),
                    models.User.name.ilike(pattern)
                )
            )
        
        users = query.order_by(models.User.created_at.desc()).all()
        return [self._format_user(user) for user in users]
    
    def get_user_by_id(self, user_id: str) -> Optional[models.User]:
        """Récupère un utilisateur par ID"""
        return self.db.query(models.User).filter(models.User.id == user_id).first()
    
    def get_user_by_email(self, email: str) -> Optional[models.User]:
        """Récupère un utilisateur par email"""
        return self.db.query(models.User).filter(models.User.email == email).first()
    
    def get_user_by_username(self, username: str) -> Optional[models.User]:
        """Récupère un utilisateur par username"""
        return self.db.query(models.User).filter(models.User.username == username).first()
    
    def create_user(
        self,
        username: str,
        email: str,
        password: str,
        name: str,
        role: str,
        phone: Optional[str] = None
    ) -> models.User:
        """Crée un nouvel utilisateur"""
        user = models.User(
            username=username,
            email=email,
            hashed_password=get_password_hash(password),
            name=name,
            role=role,
            phone=phone,
            is_active=True
        )
        self.db.add(user)
        self.db.commit()
        self.db.refresh(user)
        logger.info(f"✨ Utilisateur créé: {username} (role: {role})")
        return user
    
    def update_user(
        self,
        user: models.User,
        username: Optional[str] = None,
        email: Optional[str] = None,
        name: Optional[str] = None,
        role: Optional[str] = None,
        phone: Optional[str] = None,
        is_active: Optional[bool] = None
    ) -> models.User:
        """Met à jour un utilisateur"""
        if username is not None:
            user.username = username
        if email is not None:
            user.email = email
        if name is not None:
            user.name = name
        if role is not None:
            user.role = role
        if phone is not None:
            user.phone = phone
        if is_active is not None:
            user.is_active = is_active
        
        self.db.commit()
        self.db.refresh(user)
        logger.info(f"📝 Utilisateur mis à jour: {user.username}")
        return user
    
    def delete_user(self, user: models.User) -> None:
        """Supprime un utilisateur"""
        username = user.username
        self.db.delete(user)
        self.db.commit()
        logger.info(f"🗑️ Utilisateur supprimé: {username}")
    
    def format_user_response(self, user: models.User) -> Dict[str, Any]:
        """Formate un utilisateur pour la réponse API"""
        return self._format_user(user)
    
    def _format_user(self, user: models.User) -> Dict[str, Any]:
        """Formate les données d'un utilisateur"""
        return {
            "id": user.id,
            "username": user.username,
            "email": user.email,
            "name": user.name,
            "role": user.role,
            "phone": user.phone,
            "is_active": user.is_active,
            "created_at": user.created_at.isoformat() if user.created_at else None,
            "last_login": user.last_login.isoformat() if user.last_login else None
        }


# Dependency injection helper
def get_admin_user_service(db: Session) -> AdminUserService:
    """Factory pour créer un AdminUserService"""
    return AdminUserService(db)

