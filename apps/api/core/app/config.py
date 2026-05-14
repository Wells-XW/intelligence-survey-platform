"""Application configuration loaded from environment variables."""

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Application settings with defaults for local development."""

    # Database
    database_url: str = "postgresql+asyncpg://survey:survey@localhost:5432/survey_db"

    # API
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    cors_origins: str = "http://localhost:5173"

    # JWT Auth
    jwt_secret: str = "dev-secret-change-me"
    jwt_algorithm: str = "HS256"
    jwt_access_token_expire_minutes: int = 15
    jwt_refresh_token_expire_days: int = 7

    # PIPL Region: cn | eu | global
    pipl_region: str = "cn"

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


settings = Settings()
