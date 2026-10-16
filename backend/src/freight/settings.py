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
    # "production" turns on secure cookies (HTTPS only) unless cookie_secure says otherwise.
    environment: Literal["development", "production"] = "development"
    cookie_secure: bool | None = None
    plan_workers: int = 2
    # Sign-in throttling: this many failures within the window blocks the email or address.
    login_max_failures: int = 5
    login_window_minutes: int = 15
    # The built web app to serve (if present), so one server runs the whole product.
    web_dist: Path = BACKEND_ROOT.parent / "web" / "dist"

    @property
    def secure_cookies(self) -> bool:
        if self.cookie_secure is not None:
            return self.cookie_secure
        return self.environment == "production"

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
