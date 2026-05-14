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

    # Redis / Celery
    redis_url: str = "redis://localhost:6379/0"

    # LLM / AI (Phase 2)
    deepseek_api_key: str = ""
    deepseek_base_url: str = "https://api.deepseek.com"
    deepseek_model: str = "deepseek-chat"  # DeepSeek-V3 for structured JSON
    llm_max_tokens: int = 4096
    llm_temperature: float = 0.3  # low temp for structured JSON output
    llm_request_timeout: int = 120  # seconds, generous for reasoning models

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


settings = Settings()
