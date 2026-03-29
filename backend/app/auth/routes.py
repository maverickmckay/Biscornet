"""
Authentication API routes.
  POST /auth/register   — create account
  POST /auth/login      — get JWT token
  GET  /auth/me         — current user info
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel, EmailStr
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.auth.crud import create_user, get_user_by_email, to_dict
from app.auth.auth import verify_password, create_access_token, get_current_user

router = APIRouter(prefix="/auth", tags=["auth"])


class RegisterRequest(BaseModel):
    email: str
    name: str
    password: str


class LoginRequest(BaseModel):
    email: str
    password: str


@router.post("/register", status_code=201)
async def register(req: RegisterRequest, db: Session = Depends(get_db)):
    if len(req.password) < 8:
        raise HTTPException(400, "Password must be at least 8 characters")
    existing = get_user_by_email(db, req.email)
    if existing:
        raise HTTPException(409, "Email already registered")
    user = create_user(db, req.email, req.name, req.password)
    token = create_access_token(user.id, user.email)
    return {"token": token, "user": to_dict(user)}


@router.post("/login")
async def login(req: LoginRequest, db: Session = Depends(get_db)):
    user = get_user_by_email(db, req.email)
    if not user or not verify_password(req.password, user.hashed_password):
        raise HTTPException(401, "Invalid email or password")
    token = create_access_token(user.id, user.email)
    return {"token": token, "user": to_dict(user)}


@router.get("/me")
async def me(current_user=Depends(get_current_user)):
    return to_dict(current_user)
