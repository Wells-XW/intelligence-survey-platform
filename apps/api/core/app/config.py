"""Application configuration loaded from environment variables."""

from typing import Dict, List, Tuple

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Application settings with defaults for local development.

    All fields use ``snake_case`` Python attribute names; Pydantic Settings
    matches them against the corresponding ``UPPER_SNAKE_CASE`` environment
    variables (e.g. ``rate_limit_default_per_minute`` reads from
    ``RATE_LIMIT_DEFAULT_PER_MINUTE``) thanks to case-insensitive resolution.
    """

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

    # Literature Search APIs (Phase 2 — Task 8)
    pubmed_api_key: str = ""
    pubmed_base_url: str = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
    semantic_scholar_api_key: str = ""
    semantic_scholar_base_url: str = "https://api.semanticscholar.org/graph/v1"
    literature_cache_ttl: int = 3600  # Redis cache TTL in seconds
    literature_max_results: int = 20  # default max results per search
    cnki_fallback_enabled: bool = False  # CNKI web scrape (fragile, best-effort)

    # ------------------------------------------------------------------
    # T15 — API Open Platform and Export Enhancement
    # ------------------------------------------------------------------
    # Per-API-key rate limit defaults (Requirement 6.5). Applied when an
    # ApiKey row has no entry in its ``rate_limit_overrides`` JSONB column.
    rate_limit_default_per_minute: int = 60
    rate_limit_default_per_hour: int = 1200
    rate_limit_default_per_day: int = 10000

    # Export pipeline storage and retention (Requirement 5.12).
    # ``export_storage_root`` is project-relative; the export worker creates
    # one subdirectory per (user_id, job_id) under this root and stores the
    # materialized file plus a temp file used by the atomic rename.
    export_storage_root: str = "storage/exports"
    export_retention_hours: int = 168  # 7 days
    export_download_token_ttl_seconds: int = 900  # 15 minutes

    # Webhook delivery worker tunables (Requirement 4.5).
    # The retry schedule is consumed by ``webhook_tasks.deliver_webhook`` and
    # indexed by the delivery row's ``attempt_count`` rather than by Celery's
    # ``self.request.retries`` so worker restarts cannot lose state.
    webhook_delivery_timeout_seconds: int = 10
    webhook_retry_schedule_seconds: Tuple[int, int, int, int, int] = (
        60,
        300,
        1800,
        7200,
        43200,
    )

    # API key hygiene (Requirement 2.9). Used by the list endpoint to compute
    # the ``inactive`` flag from ``last_used_at`` (or ``created_at`` if the
    # key has never been used).
    api_key_inactivity_threshold_days: int = 90

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


settings = Settings()
