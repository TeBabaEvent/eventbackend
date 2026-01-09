"""Fonctions de sécurité - JWT et hachage de mots de passe"""
from datetime import datetime, timedelta, timezone
from typing import Optional
from jose import JWTError, jwt
import bcrypt
from fastapi import HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db import models

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
    return bcrypt.checkpw(
        plain_password.encode('utf-8'),
        hashed_password.encode('utf-8')
    )


def get_password_hash(password: str) -> str:
    """Hasher le mot de passe"""
    hashed = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt())
    return hashed.decode('utf-8')


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
    """
    Créer un token d'accès JWT (short-lived)

    Args:
        data: Payload to encode in token
        expires_delta: Custom expiration time

    Returns:
        Encoded JWT access token
    """
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.now(timezone.utc) + expires_delta
    else:
        expire = datetime.now(timezone.utc) + timedelta(minutes=15)

    # Add token type for validation
    to_encode.update({
        "exp": expire,
        "type": "access",
        "iat": datetime.now(timezone.utc)
    })

    encoded_jwt = jwt.encode(to_encode, settings.secret_key, algorithm=settings.algorithm)
    return encoded_jwt


def create_refresh_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    """
    Créer un refresh token JWT (long-lived)

    Args:
        data: Payload to encode in token
        expires_delta: Custom expiration time

    Returns:
        Encoded JWT refresh token
    """
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.now(timezone.utc) + expires_delta
    else:
        expire = datetime.now(timezone.utc) + timedelta(days=7)

    # Add token type for validation
    to_encode.update({
        "exp": expire,
        "type": "refresh",
        "iat": datetime.now(timezone.utc)
    })

    encoded_jwt = jwt.encode(to_encode, settings.secret_key, algorithm=settings.algorithm)
    return encoded_jwt


def decode_token(token: str, expected_type: str = "access") -> TokenData:
    """
    Décoder et valider un token JWT

    Args:
        token: JWT token to decode
        expected_type: Expected token type ('access' or 'refresh')

    Returns:
        TokenData with user information

    Raises:
        HTTPException: If token is invalid or expired
    """
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=[settings.algorithm])

        # Validate token type
        token_type: str = payload.get("type")
        if token_type != expected_type:
            raise credentials_exception

        email: str = payload.get("sub")
        username: str = payload.get("username")

        if email is None:
            raise credentials_exception

        return TokenData(email=email, username=username)
    except JWTError:
        raise credentials_exception


def verify_refresh_token(token: str) -> TokenData:
    """
    Vérifier et décoder un refresh token

    Args:
        token: Refresh token to verify

    Returns:
        TokenData with user information

    Raises:
        HTTPException: If refresh token is invalid
    """
    return decode_token(token, expected_type="refresh")

