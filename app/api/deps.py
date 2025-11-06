"""Dépendances communes pour les routes API"""
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.core.security import decode_token, get_user, get_user_by_username, User

# Configuration du bearer token
security = HTTPBearer()


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: Session = Depends(get_db)
) -> User:
    """Récupérer l'utilisateur actuel à partir du token"""
    token = credentials.credentials
    token_data = decode_token(token)
    
    # Chercher d'abord par email, puis par username (pour rétrocompatibilité)
    user = get_user(db, email=token_data.email)
    if user is None and token_data.username:
        user = get_user_by_username(db, username=token_data.username)
    
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user


async def get_current_active_user(
    current_user: User = Depends(get_current_user)
) -> User:
    """Récupérer l'utilisateur actuel actif"""
    return current_user


def require_admin(current_user: User = Depends(get_current_active_user)) -> User:
    """Dépendance qui nécessite que l'utilisateur soit admin"""
    if current_user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Accès non autorisé"
        )
    return current_user

