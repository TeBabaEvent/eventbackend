"""Fonctions de sécurité - JWT et hachage de mots de passe"""
from datetime import datetime, timedelta
from typing import Optional
from jose import JWTError, jwt
from passlib.context import CryptContext
from fastapi import HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db import models

# Configuration du hachage des mots de passe
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# Modèles Pydantic pour l'authentification
class Token(BaseModel):
    access_token: str
    token_type: str

class TokenData(BaseModel):
    username: Optional[str] = None
    email: Optional[str] = None

class User(BaseModel):
    id: str
    username: str
    email: str
    name: Optional[str] = None
    role: str = "user"

class UserInDB(User):
    hashed_password: str


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Vérifier le mot de passe"""
    return pwd_context.verify(plain_password, hashed_password)


def get_password_hash(password: str) -> str:
    """Hasher le mot de passe"""
    return pwd_context.hash(password)


def get_user(db: Session, email: str) -> Optional[UserInDB]:
    """Récupérer un utilisateur de la base de données par email"""
    user = db.query(models.User).filter(models.User.email == email).first()
    if user:
        return UserInDB(
            id=user.id,
            username=user.username,
            email=user.email,
            name=user.name,
            role=user.role,
            hashed_password=user.hashed_password
        )
    return None


def get_user_by_username(db: Session, username: str) -> Optional[UserInDB]:
    """Récupérer un utilisateur de la base de données par username"""
    user = db.query(models.User).filter(models.User.username == username).first()
    if user:
        return UserInDB(
            id=user.id,
            username=user.username,
            email=user.email,
            name=user.name,
            role=user.role,
            hashed_password=user.hashed_password
        )
    return None


def authenticate_user(db: Session, email: str, password: str) -> Optional[UserInDB]:
    """Authentifier un utilisateur par email"""
    user = get_user(db, email)
    if not user:
        return None
    if not verify_password(password, user.hashed_password):
        return None
    return user


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    """Créer un token d'accès JWT"""
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=15)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, settings.secret_key, algorithm=settings.algorithm)
    return encoded_jwt


def decode_token(token: str) -> TokenData:
    """Décoder et valider un token JWT"""
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=[settings.algorithm])
        email: str = payload.get("sub")
        username: str = payload.get("username")
        if email is None:
            raise credentials_exception
        return TokenData(email=email, username=username)
    except JWTError:
        raise credentials_exception

