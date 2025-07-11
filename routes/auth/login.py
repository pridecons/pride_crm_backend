# routes/auth/login.py

from fastapi import APIRouter, HTTPException, Depends, status
from fastapi.security import OAuth2PasswordRequestForm
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session
from passlib.context import CryptContext
from datetime import datetime

from db.connection import get_db
from db.models import UserDetails, TokenDetails
from routes.auth.JWTSecurity import (
    create_access_token,
    create_refresh_token,
    save_refresh_token,
    revoke_refresh_token,
    verify_token,
)

router = APIRouter(
    prefix="/auth",
    tags=["auth"],
)

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class RefreshTokenRequest(BaseModel):
    refresh_token: str


@router.post("/login", response_model=TokenResponse)
def login(
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: Session = Depends(get_db),
):
    """
    Authenticate user and issue access + refresh tokens.
    Username is treated as phone_number.
    """
    user = (
        db.query(UserDetails)
        .filter(UserDetails.phone_number == form_data.username)
        .first()
    )
    if not user or not pwd_context.verify(form_data.password, user.password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Create tokens
    access_token = create_access_token({"sub": user.employee_code})
    refresh_token = create_refresh_token(user.employee_code)

    # Persist refresh token
    save_refresh_token(db, user.employee_code, refresh_token)

    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
    )


@router.post("/refresh", response_model=TokenResponse)
def refresh_token(
    body: RefreshTokenRequest,
    db: Session = Depends(get_db),
):
    """
    Given a valid refresh token, issue a new access + refresh pair.
    """
    payload = verify_token(body.refresh_token, db=db)
    if not payload or payload.get("token_type") != "refresh":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired refresh token",
        )

    token_in_db = (
        db.query(TokenDetails)
        .filter(TokenDetails.refresh_token == body.refresh_token)
        .first()
    )
    if not token_in_db:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Refresh token revoked",
        )

    user_id = payload.get("sub")
    access_token = create_access_token({"sub": user_id})
    new_refresh_token = create_refresh_token(user_id)
    save_refresh_token(db, user_id, new_refresh_token)

    return TokenResponse(
        access_token=access_token,
        refresh_token=new_refresh_token,
    )


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(
    body: RefreshTokenRequest,
    db: Session = Depends(get_db),
):
    """
    Revoke a refresh token (log the user out).
    """
    revoke_refresh_token(db, body.refresh_token)
    return JSONResponse(status_code=status.HTTP_204_NO_CONTENT)
