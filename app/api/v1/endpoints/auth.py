"""Routes d'authentification"""
from datetime import timedelta
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.core.config import settings
from app.core.security import authenticate_user, create_access_token, User
from app.api.deps import get_current_active_user
from app.schemas.auth import LoginRequest, LoginResponse

router = APIRouter()


@router.post("/login", response_model=LoginResponse)
async def login(login_data: LoginRequest, db: Session = Depends(get_db)):
    """Connexion utilisateur par email"""
    user = authenticate_user(db, login_data.email, login_data.password)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Email ou mot de passe incorrect",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    access_token_expires = timedelta(minutes=settings.access_token_expire_minutes)
    access_token = create_access_token(
        data={"sub": user.email, "username": user.username}, 
        expires_delta=access_token_expires
    )
    
    # Retourner le token et les infos utilisateur
    return {
        "access_token": access_token, 
        "token_type": "bearer",
        "user": {
            "id": user.id,
            "email": user.email,
            "username": user.username,
            "name": user.name,
            "role": user.role
        }
    }


@router.get("/me", response_model=User)
async def read_users_me(current_user: User = Depends(get_current_active_user)):
    """Récupérer les informations de l'utilisateur connecté"""
    return current_user


@router.post("/logout")
async def logout(current_user: User = Depends(get_current_active_user)):
    """Déconnexion utilisateur"""
    # Avec JWT stateless, on log simplement la déconnexion
    # Pour une blacklist de tokens, il faudrait stocker le token en DB avec une expiration
    return {
        "message": "Déconnexion réussie",
        "user": current_user.email
    }

