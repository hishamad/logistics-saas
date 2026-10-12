from functools import lru_cache
from pathlib import Path
from typing import Literal, Self
from urllib.parse import urlsplit

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_ROOT = Path(__file__).resolve().parents[2]
LOCAL_ENV_FILES = (BACKEND_ROOT / ".env", BACKEND_ROOT.parent / ".env")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=LOCAL_ENV_FILES, extra="ignore")
    freight_mode: Literal["demo", "production"] = "demo"
    database_url: str = "postgresql+psycopg://freight:freight_local_only@127.0.0.1:55432/freight"
    freight_allowed_origins: list[str] = ["http://localhost:3000", "http://127.0.0.1:3000"]
    openai_api_key: SecretStr | None = None
    openai_model_rules: str = ""
    openai_reasoning_effort: Literal["none", "low", "medium", "high"] | None = None
    worker_lease_seconds: int = Field(default=45, ge=15, le=300)
    public_origin: str = "http://127.0.0.1:3000"
    allowed_hosts: list[str] = ["127.0.0.1", "localhost", "[::1]", "testserver"]
    oidc_issuer: str = Field(default="", max_length=255)
    oidc_client_id: str = ""
    oidc_client_secret: SecretStr | None = None
    session_signing_key: SecretStr | None = None
    session_hours: int = Field(default=8, ge=1, le=24)
    max_request_bytes: int = Field(default=2_100_000, ge=1024, le=10_000_000)

    @model_validator(mode="after")
    def deployment_boundary(self) -> Self:
        if self.freight_mode == "production":
            origin = urlsplit(self.public_origin)
            issuer = urlsplit(self.oidc_issuer)
            if (
                origin.scheme != "https"
                or not origin.hostname
                or origin.path not in ("", "/")
                or origin.query
                or origin.fragment
                or origin.username
            ):
                raise ValueError("Production PUBLIC_ORIGIN must be an HTTPS origin without a path")
            if (
                issuer.scheme != "https"
                or not issuer.hostname
                or issuer.query
                or issuer.fragment
                or issuer.username
            ):
                raise ValueError("Production requires an HTTPS OIDC_ISSUER")
            if (
                not self.oidc_client_id
                or not self.oidc_client_secret
                or not self.oidc_client_secret.get_secret_value()
                or self.oidc_client_secret.get_secret_value().startswith("REPLACE_WITH_")
            ):
                raise ValueError("Production requires OIDC_CLIENT_ID and OIDC_CLIENT_SECRET")
            if (
                not self.session_signing_key
                or len(self.session_signing_key.get_secret_value()) < 32
                or self.session_signing_key.get_secret_value().startswith("REPLACE_WITH_")
            ):
                raise ValueError(
                    "Production SESSION_SIGNING_KEY must contain at least 32 random characters"
                )
            if "*" in self.allowed_hosts or origin.hostname not in self.allowed_hosts:
                raise ValueError(
                    "ALLOWED_HOSTS must explicitly include the public hostname; wildcards are forbidden"
                )
            if self.freight_allowed_origins != [self.public_origin.rstrip("/")]:
                raise ValueError(
                    "Production FREIGHT_ALLOWED_ORIGINS must contain only PUBLIC_ORIGIN"
                )
        return self

    @property
    def cookie_name(self) -> str:
        return "__Host-freight_session" if self.freight_mode == "production" else "freight_session"

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
