"""Celery app configuration for async AI generation tasks."""

from __future__ import annotations

from celery import Celery

from ..config import settings

celery_app = Celery(
    "intelligence_survey_platform",
    broker=settings.redis_url or "redis://localhost:6379/0",
    backend=settings.redis_url or "redis://localhost:6379/0",
    include=["app.tasks.ai_tasks"],
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="Asia/Shanghai",
    enable_utc=True,
    task_track_started=True,
    task_time_limit=300,  # 5 min max per AI task
    task_soft_time_limit=240,
    worker_prefetch_multiplier=1,  # One task per worker (LLM calls are heavy)
)
