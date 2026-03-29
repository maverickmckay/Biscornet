"""
User CRUD operations.
"""
from __future__ import annotations

import uuid
from typing import Optional

from sqlalchemy.orm import Session

from app.auth.models import UserRecord
from app.auth.auth import hash_password


def create_user(db: Session, email: str, name: str, password: str) -> UserRecord:
    user = UserRecord(
        id=str(uuid.uuid4()),
        email=email.lower().strip(),
        name=name.strip(),
        hashed_password=hash_password(password),
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def get_user_by_email(db: Session, email: str) -> Optional[UserRecord]:
    return db.query(UserRecord).filter(
        UserRecord.email == email.lower().strip()
    ).first()


def get_user_by_id(db: Session, user_id: str) -> Optional[UserRecord]:
    return db.query(UserRecord).filter(UserRecord.id == user_id).first()


def to_dict(user: UserRecord) -> dict:
    return {
        "id": user.id,
        "email": user.email,
        "name": user.name,
        "is_admin": user.is_admin,
    }
