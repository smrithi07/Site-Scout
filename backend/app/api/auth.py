from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.auth import current_user, token_for
from app.core.db import get_db
from app.core.settings import get_settings
from app.models import User

router = APIRouter(prefix="/auth", tags=["auth"])


class UserOut(BaseModel):
    id: int
    name: str
    role: str


class DemoLogin(BaseModel):
    user_id: int


def _demo_only() -> None:
    if not get_settings().demo_auth:
        raise HTTPException(404, "Not found")


@router.get("/demo-users", response_model=list[UserOut], dependencies=[Depends(_demo_only)])
def demo_users(db: Session = Depends(get_db)):
    """The role switcher's list. Names and roles only — tokens come from /auth/demo-login."""
    return db.scalars(select(User).order_by(User.id)).all()


@router.post("/demo-login", dependencies=[Depends(_demo_only)])
def demo_login(body: DemoLogin, db: Session = Depends(get_db)) -> dict:
    user = db.get(User, body.user_id)
    if user is None:
        raise HTTPException(404, "No such demo user")
    return {"token": token_for(user.id), "user": UserOut.model_validate(user, from_attributes=True)}


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(current_user)):
    return user
