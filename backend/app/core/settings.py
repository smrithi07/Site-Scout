from functools import lru_cache

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str
    sitescout_config: str = "/config/sitescout.yaml"
    cors_origins: list[str] = ["http://localhost:5173"]

    llm_provider: str = "gemini"
    llm_fallback_provider: str = "groq"
    gemini_api_key: str = ""
    gemini_model: str = ""
    groq_api_key: str = ""
    groq_model: str = ""

    # Demo auth (docs/DESIGN.md §4): tokens are HMAC(app_secret, user id). demo_auth enables the
    # role-switcher login endpoint; turn it off anywhere that isn't a demo.
    app_secret: str = Field(min_length=16)
    demo_auth: bool = True

    upload_dir: str = "/uploads"  # property photos (bind-mounted, git-ignored)

    @field_validator("database_url")
    @classmethod
    def _psycopg_driver(cls, v: str) -> str:
        """Hosts (e.g. Render) hand out postgres:// or postgresql:// URLs; SQLAlchemy needs the driver."""
        for prefix in ("postgres://", "postgresql://"):
            if v.startswith(prefix):
                return "postgresql+psycopg://" + v[len(prefix):]
        return v


@lru_cache
def get_settings() -> Settings:
    return Settings()
