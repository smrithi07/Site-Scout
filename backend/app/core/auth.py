"""Demo auth: four seeded users, bearer tokens of the form '<user_id>.<hmac>'. Deliberately
simple (docs/DESIGN.md §4), but the role checks are real and server-side: 401 for a missing or
bad token, 403 for the wrong role."""
import hashlib
import hmac
from collections.abc import Callable
from enum import StrEnum

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.settings import get_settings
from app.models import User


class Role(StrEnum):
    BD_MANAGER = "bd_manager"
    BD_EXECUTIVE = "bd_executive"
    SURVEY_MANAGER = "survey_manager"
    SURVEY_EXECUTIVE = "survey_executive"


BD_ROLES = (Role.BD_MANAGER, Role.BD_EXECUTIVE)
ALL_ROLES = tuple(Role)

_bearer = HTTPBearer(auto_error=False)


def _sign(user_id: int) -> str:
    return hmac.new(get_settings().app_secret.encode(), f"user:{user_id}".encode(), hashlib.sha256).hexdigest()[:32]


def token_for(user_id: int) -> str:
    return f"{user_id}.{_sign(user_id)}"


def _user_from_token(db: Session, token: str) -> User | None:
    uid, _, sig = token.partition(".")
    if not uid.isdigit() or not hmac.compare_digest(sig, _sign(int(uid))):
        return None
    return db.get(User, int(uid))


def current_user(creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
                 db: Session = Depends(get_db)) -> User:
    user = _user_from_token(db, creds.credentials) if creds else None
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Missing or invalid bearer token",
                            headers={"WWW-Authenticate": "Bearer"})
    return user


def require_roles(*roles: Role) -> Callable[..., User]:
    allowed = {r.value for r in roles}

    def dependency(user: User = Depends(current_user)) -> User:
        if user.role not in allowed:
            raise HTTPException(status.HTTP_403_FORBIDDEN,
                                f"Role {user.role!r} cannot do this (allowed: {', '.join(sorted(allowed))})")
        return user

    return dependency
