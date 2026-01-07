"""Dépendances communes pour les routes API - ✅ COOKIE-BASED AUTH"""
from typing import Optional
from functools import lru_cache
from fastapi import Depends, HTTPException, status, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.core.security import decode_token, get_user, get_user_by_username, User
from app.core.config import Settings

# Configuration du bearer token (optionnel pour backwards compatibility)
security = HTTPBearer(auto_error=False)


def get_token_from_request(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security)
) -> str:
    """
    ✅ Extract token from httpOnly cookie (preferred) or Authorization header (fallback)

    Priority:
    1. access_token cookie (new secure method)
    2. Authorization header (backwards compatibility during migration)

    Args:
        request: FastAPI request object
        credentials: Optional bearer token from Authorization header

    Returns:
        JWT token string

    Raises:
        HTTPException: If no token found
    """
    # ✅ Try cookie first (new secure method)
    token = request.cookies.get("access_token")

    if token:
        return token

    # Fallback to Authorization header (backwards compatibility)
    if credentials:
        return credentials.credentials

    # No token found
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Not authenticated",
        headers={"WWW-Authenticate": "Bearer"},
    )


async def get_current_user(
    token: str = Depends(get_token_from_request),
    db: Session = Depends(get_db)
) -> User:
    """
    ✅ Récupérer l'utilisateur actuel à partir du token (cookie ou header)

    Args:
        token: JWT access token from cookie or header
        db: Database session

    Returns:
        User object

    Raises:
        HTTPException: If token invalid or user not found
    """
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
    """Dépendance qui nécessite que l'utilisateur soit admin ou super_admin"""
    if current_user.role not in ["admin", "super_admin"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Accès réservé aux administrateurs"
        )
    return current_user


def require_super_admin(current_user: User = Depends(get_current_active_user)) -> User:
    """Dépendance qui nécessite que l'utilisateur soit super_admin"""
    if current_user.role != "super_admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Accès réservé aux super administrateurs"
        )
    return current_user


def require_steward(current_user: User = Depends(get_current_active_user)) -> User:
    """Dépendance qui nécessite que l'utilisateur soit steward, admin ou super_admin"""
    if current_user.role not in ["steward", "admin", "super_admin"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Accès réservé aux stewards et administrateurs"
        )
    return current_user


# ============== SETTINGS DEPENDENCY ==============

@lru_cache()
def get_settings() -> Settings:
    """
    Retourne les settings de l'application (cached).
    
    Usage:
        @router.get("/endpoint")
        def my_endpoint(settings: Settings = Depends(get_settings)):
            return {"debug": settings.debug}
    """
    from app.core.config import settings
    return settings


# ============== MOLLIE CLIENT DEPENDENCY ==============

def get_mollie_client():
    """
    Retourne le client Mollie.
    
    Usage:
        @router.post("/payment")
        def create_payment(mollie: MolliePaymentClient = Depends(get_mollie_client)):
            payment = mollie.create_payment(...)
    """
    from app.services.mollie_client import mollie_client
    return mollie_client


# ============== ADMIN SERVICE DEPENDENCIES ==============

def get_admin_order_service(db: Session = Depends(get_db)):
    """Retourne le service de gestion des commandes admin"""
    from app.services.admin_order_service import AdminOrderService
    return AdminOrderService(db)


def get_admin_stats_service(db: Session = Depends(get_db)):
    """Retourne le service de statistiques admin"""
    from app.services.admin_stats_service import AdminStatsService
    return AdminStatsService(db)


def get_admin_user_service(db: Session = Depends(get_db)):
    """Retourne le service de gestion des utilisateurs admin"""
    from app.services.admin_user_service import AdminUserService
    return AdminUserService(db)

