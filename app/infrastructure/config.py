"""Application configuration settings."""

from functools import lru_cache
from typing import List

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    # Database
    database_url: str

    # Security
    secret_key: SecretStr
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 30

    # BCB API
    bcb_api_base_url: str

    # Application
    debug: bool = False
    environment: str = "development"
    # SQLAlchemy
    sql_echo: bool = False

    # CORS
    cors_origins: List[str] = Field(default_factory=list)

    # Frontend
    frontend_url: str = "http://localhost:3000"

    # SendGrid
    sendgrid_api_key: SecretStr
    sendgrid_from_email: str
    sendgrid_from_name: str = "Blanco Finanças"

    # Mercado Pago
    mercadopago_access_token: SecretStr = SecretStr("")
    mercadopago_webhook_secret: SecretStr = SecretStr("")
    mercadopago_api_base_url: str = "https://api.mercadopago.com"
    mercadopago_webhook_tolerance_seconds: int = 300
    # URL pública para notificações por order. Se vazio, usa a URL do dashboard MP.
    mercadopago_notification_url: str = ""


@lru_cache
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings() # pyright: ignore[reportCallIssue] 


settings = get_settings()
