from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_ROOT = Path(__file__).resolve().parents[2]
LOCAL_ENV_FILES = (BACKEND_ROOT / ".env", BACKEND_ROOT.parent / ".env")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=LOCAL_ENV_FILES, extra="ignore")
    openai_api_key: SecretStr | None = None
    openai_model_rules: str = ""
    openai_reasoning_effort: Literal["none", "low", "medium", "high"] | None = None
    # Web app. SQLite by default (one local file); a PostgreSQL URL works the same way.
    database_url: str = f"sqlite:///{(BACKEND_ROOT / '.data' / 'freight.db').as_posix()}"
    session_hours: int = 12
    cookie_secure: bool = False  # set True behind HTTPS in production
    plan_workers: int = 2

    @property
    def ai_configured(self) -> bool:
        return bool(
            self.openai_api_key
            and self.openai_api_key.get_secret_value()
            and self.openai_model_rules
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()
