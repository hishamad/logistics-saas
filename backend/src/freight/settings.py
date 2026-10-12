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
