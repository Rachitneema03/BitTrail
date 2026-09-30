"""Minimal role-based auth for the prototype: seeded demo users + JWT bearer tokens."""
from __future__ import annotations

import hashlib
import hmac
import os
from datetime import datetime, timedelta, timezone

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import settings
from .db import get_db
from .models import User

bearer = HTTPBearer(auto_error=False)
DEMO_PASSWORD = "bittrail-demo"
# VASPs are not BitTrail users: they receive notices and reply through Sahyog (mocked via /sahyog/reply).
DEMO_USERS = [
    ("Insp. A. Sharma (demo IO)", "io@bittrail.demo", "io"),
    ("I4C Analyst (demo)", "analyst@bittrail.demo", "analyst"),
]


def hash_password(pw: str, salt: bytes | None = None) -> str:
    salt = salt or os.urandom(16)
    dk = hashlib.pbkdf2_hmac("sha256", pw.encode(), salt, 100_000)
    return salt.hex() + "$" + dk.hex()


def verify_password(pw: str, stored: str) -> bool:
    salt, dk = stored.split("$")
    return hmac.compare_digest(hash_password(pw, bytes.fromhex(salt)).split("$")[1], dk)


def make_token(user: User) -> str:
    payload = {"sub": user.id, "role": user.role, "exp": datetime.now(timezone.utc) + timedelta(hours=12)}
    return jwt.encode(payload, settings().jwt_secret, algorithm="HS256")


def seed_users(db: Session) -> None:
    for name, email, role in DEMO_USERS:
        if db.execute(select(User).where(User.email == email)).scalar():
            continue
        db.add(User(name=name, email=email, role=role, password_hash=hash_password(DEMO_PASSWORD)))
    db.commit()


def current_user(creds: HTTPAuthorizationCredentials | None = Depends(bearer), db: Session = Depends(get_db)) -> User:
    if creds is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not authenticated")
    try:
        payload = jwt.decode(creds.credentials, settings().jwt_secret, algorithms=["HS256"])
    except jwt.PyJWTError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or expired token")
    user = db.get(User, payload["sub"])
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Unknown user")
    return user


def require(*roles: str):
    def dep(user: User = Depends(current_user)) -> User:
        if user.role not in roles:
            raise HTTPException(status.HTTP_403_FORBIDDEN, f"Requires role: {', '.join(roles)}")
        return user
    return dep
