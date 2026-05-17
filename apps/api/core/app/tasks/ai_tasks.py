"""Async Celery tasks for AI generation (heavy LLM calls)."""

from __future__ import annotations

from . import celery_app


@celery_app.task(bind=True, max_retries=2, default_retry_delay=30)
def generate_survey_async(
    self,
    topic: str,
    research_question: str,
    target_population: str,
    num_items: int = 20,
    language: str = "zh",
    constructs: list[str] | None = None,
    user_id: str | None = None,
) -> dict:
    """Background task: generate a survey via LLM and return the result.

    This is the Celery-wrapped version for when we want to offload
    the LLM call from the web server process. The API also supports
    direct (non-Celery) generation for interactive SSE streaming.
    """
    import asyncio

    from ..schemas.ai_generation import SurveyGenerationRequest
    from ..services.ai_generation import AiGenerationService

    async def _run() -> dict:
        from ..database import async_session_factory

        async with async_session_factory() as db:
            service = AiGenerationService(db)
            request = SurveyGenerationRequest(
                topic=topic,
                research_question=research_question,
                target_population=target_population,
                num_items=num_items,
                language=language,
                constructs=constructs,
            )
            result = await service.generate_survey(request, user_id=user_id)
            return result.model_dump()

    try:
        return asyncio.run(_run())
    except Exception as exc:
        # Retry with exponential backoff
        raise self.retry(exc=exc, countdown=30 * (2 ** self.request.retries))
