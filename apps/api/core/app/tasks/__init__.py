"""Celery application factory for the Intelligence Survey Platform.

This module declares the shared :data:`celery_app` instance plus the queue
topology used by every async worker in the platform.

Queues:
    celery:
        The historical default queue. Carries existing AI generation tasks
        (see :mod:`app.tasks.ai_tasks`). Kept as the default queue so the
        already-deployed ``celery-worker`` container does not need a queue
        flag change to keep functioning.
    webhooks:
        Outbound webhook delivery jobs (see T15 design Component 5).
        Routing key ``webhooks``.
    exports:
        Multi-format export materialization jobs (see T15 design
        Component 7). Routing key ``exports``.

Operator concurrency hints (set via worker CLI flags, not here):
    * ``webhooks`` queue: ``--concurrency=8 --prefetch-multiplier=4``.
        Webhook delivery is I/O bound (HTTPS POST with 10 s timeout); a
        higher prefetch lets one slow target URL not stall sibling
        deliveries on the same worker. Equivalent to::

            celery -A app.tasks worker --queues=webhooks \\
                --concurrency=8 --prefetch-multiplier=4

    * ``exports`` queue: ``--concurrency=2 --max-tasks-per-child=50``.
        Export materialization is CPU- and memory-bound (especially for
        SPSS / SAS via ``pyreadstat`` which has long-running memory
        growth). Recycling the worker process every 50 tasks bounds RSS.
        Equivalent to::

            celery -A app.tasks worker --queues=exports \\
                --concurrency=2 --max-tasks-per-child=50

These flags are command-line guidance for ``docker-compose.yml`` /
deployment manifests, not runtime configuration on the app object.
"""

from __future__ import annotations

from celery import Celery
from kombu import Queue

from ..config import settings

celery_app = Celery(
    "intelligence_survey_platform",
    broker=settings.redis_url or "redis://localhost:6379/0",
    backend=settings.redis_url or "redis://localhost:6379/0",
    include=[
        "app.tasks.ai_tasks",
        "app.tasks.webhook_tasks",
        "app.tasks.export_tasks",
    ],
)

# Declare the queue topology. Routing keys mirror queue names by convention so
# `task.apply_async(queue="webhooks")` routes correctly without an explicit
# `routing_key=` argument at the call site.
celery_app.conf.task_queues = (
    Queue("celery", routing_key="celery"),
    Queue("webhooks", routing_key="webhooks"),
    Queue("exports", routing_key="exports"),
)

# Declarative task→queue routing. Call sites still pass ``queue=`` explicitly
# for clarity, but ``task_routes`` is the source of truth so a worker booted
# with ``celery -A app.tasks worker --queues=webhooks,exports`` knows which
# tasks belong on which queue without inspecting every dispatch site. Each
# entry maps a fully qualified task name to a routing dict.
celery_app.conf.task_routes = {
    "app.tasks.webhook_tasks.deliver_webhook": {"queue": "webhooks"},
    "app.tasks.webhook_tasks.reconcile_pending_deliveries": {
        "queue": "webhooks"
    },
    "app.tasks.webhook_tasks.invalidate_previous_secret": {
        "queue": "webhooks"
    },
    "app.tasks.export_tasks.materialize_export": {"queue": "exports"},
    "app.tasks.export_tasks.sweep_expired_exports": {"queue": "exports"},
}

celery_app.conf.update(
    task_default_queue="celery",
    task_default_routing_key="celery",
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
