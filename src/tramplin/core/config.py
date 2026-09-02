from datetime import timedelta
from enum import StrEnum
from typing import Annotated, Final, Literal

from pydantic import BeforeValidator, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

API_PREFIX: Final = "/api/v1"

JwtAlgorithm = Literal["HS256", "HS384", "HS512"]


def _parse_duration(value: object) -> object:
    """В окружении длительность удобнее писать секундами: 900 наравне с ISO 8601 (PT15M)."""
    if isinstance(value, str) and value.strip().isdigit():
        return timedelta(seconds=int(value))
    return value


Duration = Annotated[timedelta, BeforeValidator(_parse_duration)]


class Environment(StrEnum):
    LOCAL = "local"
    PRODUCTION = "production"


class DatabaseSettings(BaseSettings):
    """Отдельно от Settings: миграциям нужен только Postgres, но не секреты приложения."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    database_url: str = "postgresql+asyncpg://tramplin:tramplin@localhost:5432/tramplin"


class Settings(DatabaseSettings):
    environment: Environment = Environment.LOCAL
    redis_url: str = "redis://localhost:6379/0"
    frontend_base_url: str = "http://localhost:5173"

    jwt_secret: SecretStr
    jwt_algorithm: JwtAlgorithm = "HS256"
    jwt_issuer: str = "tramplin"
    access_token_ttl: Duration = timedelta(minutes=15)
    refresh_token_ttl: Duration = timedelta(days=30)
    refresh_token_bytes: int = 48

    github_client_id: str
    github_client_secret: SecretStr
    github_redirect_uri: str = f"http://localhost:8000{API_PREFIX}/auth/github/callback"
    oauth_state_ttl: Duration = timedelta(minutes=10)
    oauth_state_bytes: int = 32
    http_timeout: Duration = timedelta(seconds=10)

    llm_base_url: str = "https://api.openai.com/v1"
    llm_api_key: SecretStr = SecretStr("")
    llm_model: str = ""
    llm_proxy_url: str | None = None
    llm_max_tokens: int = 900
    llm_temperature: float = 0.2
    llm_timeout: Duration = timedelta(seconds=90)
    llm_retries: int = 1
    llm_history_limit: int = 10
    llm_question_max_chars: int = 2000
    llm_daily_quota: int = 50
    llm_guest_quota: int = 3
    llm_guest_ip_quota: int = 60
    # Единственный лимит, который нельзя обойти со стороны клиента.
    llm_guest_daily_total: int = 300
    guest_cookie_ttl: Duration = timedelta(days=30)

    s3_bucket: str = "tramplin"
    s3_region: str = "us-east-1"
    s3_access_key: SecretStr = SecretStr("")
    s3_secret_key: SecretStr = SecretStr("")
    s3_endpoint_url: str | None = None
    s3_public_url: str | None = None
    asset_max_bytes: int = 10 * 1024 * 1024

    @property
    def llm_enabled(self) -> bool:
        return bool(self.llm_model and self.llm_api_key.get_secret_value())

    @property
    def is_production(self) -> bool:
        return self.environment is Environment.PRODUCTION

    @property
    def s3_public_base_url(self) -> str:
        """Свой endpoint — у S3-совместимых провайдеров; у AWS адрес собирается из региона."""
        if self.s3_public_url is not None:
            return self.s3_public_url.rstrip("/")
        if self.s3_endpoint_url is not None:
            return f"{self.s3_endpoint_url.rstrip('/')}/{self.s3_bucket}"
        return f"https://{self.s3_bucket}.s3.{self.s3_region}.amazonaws.com"


def load_settings() -> Settings:
    return Settings()
