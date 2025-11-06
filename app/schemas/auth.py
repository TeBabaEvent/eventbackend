"""Schémas d'authentification"""
from typing import Optional
from pydantic import BaseModel


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


class LoginRequest(BaseModel):
    email: str
    password: str


class LoginResponse(BaseModel):
    access_token: str
    token_type: str
    user: User

