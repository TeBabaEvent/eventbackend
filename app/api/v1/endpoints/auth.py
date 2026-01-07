"""Routes d'authentification - ✅ SECURE COOKIE-BASED AUTH + RATE LIMITED"""
import logging
from datetime import timedelta
from fastapi import APIRouter, Depends, HTTPException, status, Response, Request
from sqlalchemy.orm import Session

from app.db.database import get_db

logger = logging.getLogger(__name__)
from app.core.config import settings
from app.core.security import (
    authenticate_user,
    create_access_token,
    create_refresh_token,
    verify_refresh_token,
    User
)
from app.core.rate_limiter import limiter, RATE_LIMITS
from app.api.deps import get_current_active_user
from app.schemas.auth import LoginRequest

router = APIRouter()


@router.post(
    "/login",
    status_code=status.HTTP_200_OK,
    responses={
        401: {"description": "Invalid credentials"},
        429: {"description": "Too many login attempts"}
    }
)
@limiter.limit(RATE_LIMITS["login"])  # 5 attempts per minute - brute force protection
def login(
    request: Request,  # Required for rate limiting
    login_data: LoginRequest,
    response: Response,
    db: Session = Depends(get_db)
):
    """
    ✅ SECURE LOGIN - Sets httpOnly cookies instead of returning tokens

    Security features:
    - httpOnly cookies (prevents XSS attacks)
    - Secure flag in production (HTTPS only)
    - SameSite=lax (CSRF protection)
    - Short-lived access token (15 min)
    - Long-lived refresh token (7 days)
    - Rate limited: 5 attempts per minute per IP
    """
    # Authenticate user
    user = authenticate_user(db, login_data.email, login_data.password)
    if not user:
        logger.warning(f"🔒 Login failed for email: {login_data.email} from IP: {request.client.host if request.client else 'unknown'}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Email ou mot de passe incorrect",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    logger.info(f"✅ Login successful for user: {user.username} ({user.email})")

    # Create tokens
    access_token_expires = timedelta(minutes=settings.access_token_expire_minutes)
    access_token = create_access_token(
        data={"sub": user.email, "username": user.username},
        expires_delta=access_token_expires
    )

    refresh_token_expires = timedelta(days=settings.refresh_token_expire_days)
    refresh_token = create_refresh_token(
        data={"sub": user.email, "username": user.username},
        expires_delta=refresh_token_expires
    )

    # ✅ Set httpOnly cookies (tokens NOT in response body)
    response.set_cookie(
        key="access_token",
        value=access_token,
        httponly=True,  # ✅ JavaScript cannot access
        secure=settings.cookie_secure,  # ✅ HTTPS only in production
        samesite=settings.cookie_samesite,  # ✅ CSRF protection
        max_age=settings.access_token_expire_minutes * 60,  # seconds
        path="/"
    )

    response.set_cookie(
        key="refresh_token",
        value=refresh_token,
        httponly=True,
        secure=settings.cookie_secure,
        samesite=settings.cookie_samesite,
        max_age=settings.refresh_token_expire_days * 24 * 60 * 60,  # seconds
        path="/api/auth/refresh"  # ✅ Only sent to refresh endpoint
    )

    # ✅ Return only user data (NO TOKENS)
    return {
        "user": {
            "id": user.id,
            "email": user.email,
            "username": user.username,
            "name": user.name,
            "role": user.role
        }
    }


@router.get("/me", response_model=User)
def read_users_me(current_user: User = Depends(get_current_active_user)):
    """Récupérer les informations de l'utilisateur connecté"""
    return current_user


@router.post("/refresh")
@limiter.limit(RATE_LIMITS["refresh"])  # 30 refreshes per minute
def refresh_token(request: Request, response: Response, db: Session = Depends(get_db)):
    """
    ✅ REFRESH TOKEN ENDPOINT (Rate limited: 30/min)

    Automatically called by frontend when access token expires (401).
    Uses refresh token from httpOnly cookie to generate new access token.
    """
    # Get refresh token from cookie
    refresh_token = request.cookies.get("refresh_token")

    if not refresh_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Aucun token de rafraîchissement trouvé"
        )

    try:
        # Verify refresh token
        token_data = verify_refresh_token(refresh_token)

        # Get user from database
        from app.core.security import get_user
        user = get_user(db, email=token_data.email)

        if not user:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Utilisateur non trouvé"
            )

        # Generate new access token
        access_token_expires = timedelta(minutes=settings.access_token_expire_minutes)
        new_access_token = create_access_token(
            data={"sub": user.email, "username": user.username},
            expires_delta=access_token_expires
        )

        # ✅ Set new access token cookie
        response.set_cookie(
            key="access_token",
            value=new_access_token,
            httponly=True,
            secure=settings.cookie_secure,
            samesite=settings.cookie_samesite,
            max_age=settings.access_token_expire_minutes * 60,
            path="/"
        )

        logger.debug(f"🔄 Token refreshed for user: {user.username}")
        return {"success": True}

    except HTTPException:
        raise
    except Exception as e:
        logger.warning(f"🔒 Token refresh failed: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token de rafraîchissement invalide"
        )


@router.post("/logout")
def logout(response: Response, current_user: User = Depends(get_current_active_user)):
    """
    ✅ SECURE LOGOUT - Clears httpOnly cookies
    """
    # ✅ Clear both cookies
    response.delete_cookie(key="access_token", path="/")
    response.delete_cookie(key="refresh_token", path="/api/auth/refresh")

    logger.info(f"👋 User logged out: {current_user.username} ({current_user.email})")
    return {
        "message": "Déconnexion réussie",
        "user": current_user.email
    }

