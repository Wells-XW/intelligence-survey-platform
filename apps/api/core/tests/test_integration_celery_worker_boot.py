"""Task 18.4 — Celery worker boot integration test.

Verifies that the Celery app declared in :mod:`app.tasks` exposes the
queue topology and the task surface that the API platform's webhook
delivery worker (Component 5) and export materialization worker
(Component 7) require to boot. The test does not start a worker
subprocess; instead it inspects the in-process ``celery_app`` object
after triggering Celery's loader so all ``include=`` modules are
imported. That gives the same registration state a freshly booted
``celery -A app.tasks worker`` would observe, while staying fully
hermetic (no broker, no Postgres, no subprocess).

Validates: Requirements 4.1, 5.4
"""

from __future__ import annotations

from typing import Iterable, Set

import pytest


# ── Constants drawn from the design and config modules ───────────────

#: Queue names that must be registered. ``celery`` is the historical
#: default queue; ``webhooks`` and ``exports`` are the queues introduced
#: by Tasks 1.2 / 8.1 / 7.x for the API Open Platform.
EXPECTED_QUEUES: Set[str] = {"celery", "webhooks", "exports"}

#: Webhook delivery worker tasks (Component 5). Each name is the
#: fully-qualified task name that ``celery_app.send_task(...)`` calls
#: into and that the worker registers via ``@celery_app.task(name=...)``.
WEBHOOK_TASK_NAMES: Set[str] = {
    "app.tasks.webhook_tasks.deliver_webhook",
    "app.tasks.webhook_tasks.reconcile_pending_deliveries",
    "app.tasks.webhook_tasks.invalidate_previous_secret",
}

#: Export materialization worker tasks (Component 7). The retention
#: sweeper (``sweep_expired_exports``) is intended to run on Celery
#: beat hourly per design §Component 7.
EXPORT_TASK_NAMES: Set[str] = {
    "app.tasks.export_tasks.materialize_export",
    "app.tasks.export_tasks.sweep_expired_exports",
}

#: Mapping from task name to the queue the operator expects the worker
#: to consume it on. ``task_routes`` is the declarative source of truth
#: so a worker booted with ``--queues=webhooks,exports`` knows where
#: each task lives without inspecting every dispatch site.
EXPECTED_ROUTING: dict = {
    **{name: "webhooks" for name in WEBHOOK_TASK_NAMES},
    **{name: "exports" for name in EXPORT_TASK_NAMES},
}


# ── Fixtures ──────────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def celery_app():
    """Import the Celery app and force-load every ``include=`` module.

    A bare ``from app.tasks import celery_app`` only runs the
    ``app/tasks/__init__.py`` body; the per-task modules listed in
    ``include=`` are imported lazily by Celery's loader on worker
    boot. We mirror that boot step here by calling
    :meth:`Celery.loader.import_default_modules`, which is exactly
    what a real worker invokes during its startup phase. The result
    is an app object whose ``tasks`` registry contains every
    decorated task, just as a freshly booted worker would see.
    """
    from app.tasks import celery_app as app

    app.loader.import_default_modules()
    return app


# ── Helpers ───────────────────────────────────────────────────────────


def _registered_queue_names(app) -> Set[str]:
    """Return the set of queue names registered on the app.

    Reads :attr:`celery_app.conf.task_queues`, which is a tuple of
    :class:`kombu.Queue` instances configured by the app factory. Each
    ``Queue`` exposes a ``name`` attribute used by the worker to bind
    consumers.

    Args:
        app: The Celery app under test.

    Returns:
        The set of queue names declared on the app.
    """
    queues: Iterable = app.conf.task_queues or ()
    return {q.name for q in queues}


def _registered_task_names(app) -> Set[str]:
    """Return the set of non-internal task names registered on the app.

    Filters out Celery's own bookkeeping tasks (which all start with
    ``celery.``, e.g. ``celery.chord``, ``celery.chunks``) so the
    assertion compares only application-level tasks.

    Args:
        app: The Celery app under test.

    Returns:
        Application task names registered on the app.
    """
    return {
        name for name in app.tasks if not name.startswith("celery.")
    }


def _routed_queue_for(app, task_name: str) -> str:
    """Resolve the queue routing for a single task name.

    Calls Celery's :meth:`amqp.AMQP.router.route` so the resolution
    matches what an outbound :meth:`Celery.send_task` would use. The
    router consults ``task_routes`` first, then falls back to the
    task's per-class ``queue`` attribute, then to
    ``task_default_queue``.

    Args:
        app: The Celery app under test.
        task_name: Fully qualified task name to route.

    Returns:
        The queue name the router would dispatch ``task_name`` to.
    """
    route = app.amqp.router.route({}, task_name)
    queue_obj = route.get("queue")
    # ``queue`` may be a Queue instance (when declared via ``task_queues``)
    # or a plain string (when only a routing key is provided). Both
    # carry the queue name, just on different attributes.
    if queue_obj is None:
        return app.conf.task_default_queue
    name = getattr(queue_obj, "name", None)
    return name if name is not None else str(queue_obj)


# ── Tests ─────────────────────────────────────────────────────────────


def test_celery_app_imports(celery_app) -> None:
    """The shared Celery app loads with the expected name.

    Boot-time wiring lives in ``app.tasks.__init__`` and the worker
    addresses the app by its main name (``celery -A app.tasks``).
    Asserting the app is non-null and named matches the expectation
    that the deployed entry point resolves to the same object.
    """
    assert celery_app is not None
    assert celery_app.main == "intelligence_survey_platform"


def test_webhooks_queue_registered(celery_app) -> None:
    """The ``webhooks`` queue is declared on the app.

    Component 5 of the API platform requires a dedicated queue for
    outbound webhook delivery so the I/O-bound HTTPS POSTs can run on
    a worker tuned with ``--prefetch-multiplier=4`` without sharing
    bandwidth with CPU-heavy AI generation tasks.
    """
    assert "webhooks" in _registered_queue_names(celery_app)


def test_exports_queue_registered(celery_app) -> None:
    """The ``exports`` queue is declared on the app.

    Component 7 of the API platform requires a dedicated queue for
    multi-format export materialization so the CPU- and memory-heavy
    pyreadstat / openpyxl jobs run on a worker recycled every 50
    tasks via ``--max-tasks-per-child=50``.
    """
    assert "exports" in _registered_queue_names(celery_app)


def test_all_expected_queues_registered(celery_app) -> None:
    """All three queues — celery / webhooks / exports — coexist.

    The historical ``celery`` queue keeps the already-deployed AI
    worker alive without a flag change (see module docstring of
    :mod:`app.tasks`). A regression that drops it would silently
    park existing AI tasks.
    """
    assert EXPECTED_QUEUES.issubset(_registered_queue_names(celery_app))


def test_webhook_tasks_registered(celery_app) -> None:
    """Every webhook delivery task name is registered on the app.

    A worker booted with ``--queues=webhooks`` resolves task names
    against ``celery_app.tasks``; if a name is missing the worker
    rejects the message with ``NotRegistered`` and the row stays
    ``pending`` until the reconciler eventually marks it failed.
    """
    registered = _registered_task_names(celery_app)
    missing = WEBHOOK_TASK_NAMES - registered
    assert not missing, (
        f"Expected webhook tasks not registered on celery_app: "
        f"{sorted(missing)}"
    )


def test_export_tasks_registered(celery_app) -> None:
    """Materialize and sweeper tasks are both registered on the app.

    The materialize task drives ``queued → running → terminal``; the
    sweeper drives ``succeeded → expired``. Both belong on the
    ``exports`` queue and a worker booted on that queue must be able
    to resolve both names.
    """
    registered = _registered_task_names(celery_app)
    missing = EXPORT_TASK_NAMES - registered
    assert not missing, (
        f"Expected export tasks not registered on celery_app: "
        f"{sorted(missing)}"
    )


def test_task_routing_matches_queue(celery_app) -> None:
    """Every webhook / export task routes to its declared queue.

    The router consults ``task_routes`` first; the call-site
    ``queue=`` arguments are a redundant safety belt. Asserting via
    :meth:`amqp.router.route` ensures the declarative configuration
    is the source of truth and that a future call site that forgets
    the explicit ``queue=`` would still land on the right worker.
    """
    mismatches = []
    for task_name, expected_queue in EXPECTED_ROUTING.items():
        actual = _routed_queue_for(celery_app, task_name)
        if actual != expected_queue:
            mismatches.append(
                f"{task_name}: routed to {actual!r}, expected "
                f"{expected_queue!r}"
            )
    assert not mismatches, "Task routing mismatch:\n" + "\n".join(
        mismatches
    )
