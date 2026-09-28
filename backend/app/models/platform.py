"""Platform tables: demo users and the registry of config versions."""
from datetime import datetime

from sqlalchemy import DateTime, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class User(Base):
    """Four seeded demo users (migration 0004). Tokens are HMAC-derived, never stored."""
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(Text)
    role: Mapped[str] = mapped_column(String(24))  # bd_manager | bd_executive | survey_manager | survey_executive


class ConfigVersion(Base):
    """Every config version ever loaded, with a hash of its content. A version string can never
    point at two different contents — so a snapshot's `config_version` is reproducible."""
    __tablename__ = "config_versions"

    version: Mapped[str] = mapped_column(String(32), primary_key=True)
    sha256: Mapped[str] = mapped_column(String(64))
    content: Mapped[dict] = mapped_column(JSONB)
    registered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
