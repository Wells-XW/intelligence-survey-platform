"""Property test P22: Admin inventory completeness.

Per design.md §Property 22 the three admin inventory endpoints
(``GET /api/v1/admin/api-keys``, ``GET /api/v1/admin/webhooks``,
``GET /api/v1/admin/exports``) must return *exactly* the rows in their
corresponding tables that match the per-endpoint spec filter:

* ``/admin/api-keys`` — every ``api_keys`` row whose ``revoked_at IS
  NULL`` per Req 9.1.
* ``/admin/webhooks`` — every ``webhook_subscriptions`` row whose
  ``active`` flag is ``True`` per Req 9.2.
* ``/admin/exports`` — every ``export_jobs`` row in the table when no
  time filter is applied per Req 9.3 (the route accepts optional
  ``since``/``until`` query parameters; this property covers the
  unfiltered case).

The property holds in two directions: every row in the table that
matches the predicate must appear in the response, and every row in
the response must exist in the table. The empty-set case (no
matching rows) must return ``[]`` and HTTP 200, never a 404 or any
other error.

Strategy
--------

Hypothesis generates random states of the three tables and inserts
them directly via the test session. We then call each endpoint with
an admin JWT and assert set equality between the response row ids
and the table row ids restricted by the same predicate the endpoint
documents. We use the standard conftest ``db_session`` /
``async_client`` fixtures because the admin inventory routes are
read-only — they do not commit — so flushed-but-uncommitted rows are
visible to the route's session via the FastAPI dependency override.

We cap ``max_examples`` at 20 per the task brief because every
example writes several rows to Postgres and the property reduces to
a small enumerated state machine that does not need a long sample.
We suppress :class:`HealthCheck.function_scoped_fixture` because the
``db_session`` and ``async_client`` fixtures are intentionally
function-scoped to give Hypothesis a single shared DB transaction
across examples within one test invocation.

# Feature: api-platform-export, Property 22: Admin inventory completeness
# Validates: Requirements 9.1, 9.2, 9.3
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import List, Tuple

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from sqlalchemy import select

from app.core.api_key_secret import generate_plaintext
from app.core.security import create_access_token, hash_password
from app.core.webhook_secret_crypto import encrypt_signing_secret
from app.models.api_key import ApiKey
from app.models.export_job import ExportJob
from app.models.survey import Survey
from app.models.user import User
from app.models.webhook_subscription import WebhookSubscription


# ── Strategies ────────────────────────────────────────────────────────


# A short list (0-5 items) of booleans is sufficient: the spec filter
# for api keys is a single boolean predicate (``revoked_at IS NULL``)
# and Hypothesis already covers the empty-list and all-True / all-False
# cases inside this range.
_API_KEY_REVOKED_FLAGS = st.lists(st.booleans(), min_size=0, max_size=5)

#: Per-row ``active`` toggles for webhook subscriptions. Mirrors the
#: api-keys strategy because the admin webhook filter is also a
#: single boolean predicate.
_WEBHOOK_ACTIVE_FLAGS = st.lists(st.booleans(), min_size=0, max_size=5)

#: Per-row export status drawn from the lifecycle states design.md
#: §"Export job state machine" enumerates. The admin exports endpoint
#: returns rows of every status (filtered only by time range, not by
#: lifecycle state), so we vary the field to exercise the projection.
_EXPORT_JOB_STATUSES = st.lists(
    st.sampled_from(["queued", "running", "succeeded", "failed", "expired"]),
    min_size=0,
    max_size=5,
)


# ── Fixtures and helpers ──────────────────────────────────────────────


async def _make_admin_and_owner(db_session) -> Tuple[User, User, Survey]:
    """Provision an admin user, an owner user, and one survey.

    The admin is granted ``is_admin=True`` so the
    :func:`app.api.v1.admin._require_is_admin` gate accepts it; the
    owner is a non-admin user that owns the api keys, webhooks, and
    export jobs under test. A single survey is created because
    :class:`ExportJob` carries a non-null FK to ``surveys.id``;
    :class:`WebhookSubscription` is left scope-free
    (``survey_id=None``) so the test does not depend on RBAC plumbing
    that is not part of the property under test.

    UUID-based emails make every user unique across Hypothesis
    examples within a single test invocation. The session is
    flushed (not committed) so the rows are visible to the route
    handlers through the FastAPI dependency override but roll back
    cleanly at fixture teardown.

    Args:
        db_session: The conftest-provided async session bound to the
            test database.

    Returns:
        ``(admin_user, owner_user, survey)`` triple.
    """
    admin = User(
        id=str(uuid.uuid4()),
        email=f"p22-admin-{uuid.uuid4()}@example.test",
        hashed_password=hash_password("Test1234!"),
        display_name="P22 admin",
        is_admin=True,
    )
    owner = User(
        id=str(uuid.uuid4()),
        email=f"p22-owner-{uuid.uuid4()}@example.test",
        hashed_password=hash_password("Test1234!"),
        display_name="P22 owner",
        is_admin=False,
    )
    db_session.add_all([admin, owner])
    await db_session.flush()

    survey = Survey(
        id=str(uuid.uuid4()),
        owner_id=owner.id,
        title="P22 survey",
        json_content={},
    )
    db_session.add(survey)
    await db_session.flush()
    return admin, owner, survey


async def _insert_api_keys(
    db_session, owner: User, revoked_flags: List[bool]
) -> List[str]:
    """Insert one ``ApiKey`` row per flag and return the inserted ids.

    Each row's ``revoked_at`` is set to ``now()`` when the flag is
    ``True`` and left ``None`` when ``False`` — the predicate the
    admin endpoint filters on. The plaintext is generated through
    :func:`app.core.api_key_secret.generate_plaintext` so the
    ``key_prefix`` column's uniqueness constraint cannot collide
    across rows. ``last_used_at`` is intentionally left ``None`` to
    keep the insert minimal; the admin schema reports it verbatim.

    Args:
        db_session: Active async database session.
        owner: The user that owns the keys.
        revoked_flags: Per-row revoked toggle.

    Returns:
        List of inserted key ids in insertion order.
    """
    inserted: List[str] = []
    for revoked in revoked_flags:
        plaintext, key_prefix, key_hash = generate_plaintext("live")
        key = ApiKey(
            user_id=owner.id,
            name=f"p22-key-{uuid.uuid4().hex[:6]}",
            key_prefix=key_prefix,
            key_hash=key_hash,
            scopes=["survey:read"],
            revoked_at=datetime.now(timezone.utc) if revoked else None,
        )
        db_session.add(key)
        await db_session.flush()
        inserted.append(key.id)
        # Avoid using the same plaintext object more than once.
        del plaintext
    return inserted


async def _insert_webhooks(
    db_session, owner: User, active_flags: List[bool]
) -> List[str]:
    """Insert one ``WebhookSubscription`` row per flag.

    Mirrors :func:`_insert_api_keys`. The signing-secret column is
    populated with a fresh Fernet-wrapped placeholder via
    :func:`app.core.webhook_secret_crypto.encrypt_signing_secret`
    because the column is non-nullable, but the property under test
    ignores the field entirely. The subscription is scope-free
    (``survey_id=None``) so the property does not depend on RBAC
    plumbing that is unrelated to inventory completeness.

    Args:
        db_session: Active async database session.
        owner: The user that owns the subscriptions.
        active_flags: Per-row ``active`` toggle.

    Returns:
        List of inserted subscription ids in insertion order.
    """
    inserted: List[str] = []
    for active in active_flags:
        sub = WebhookSubscription(
            user_id=owner.id,
            survey_id=None,
            target_url="https://hooks.example.com/p22",
            event_types=["response.created"],
            signing_secret_ciphertext=encrypt_signing_secret(
                f"whsec_{uuid.uuid4().hex[:24]}"
            ),
            active=active,
        )
        db_session.add(sub)
        await db_session.flush()
        inserted.append(sub.id)
    return inserted


async def _insert_export_jobs(
    db_session,
    owner: User,
    survey: Survey,
    statuses: List[str],
) -> List[str]:
    """Insert one ``ExportJob`` row per status and return the inserted ids.

    Each row is anchored to the same survey so the ``surveys`` FK
    constraint is satisfied without growing the survey table. The
    ``format`` is fixed to ``csv`` because the admin exports
    inventory does not filter on format; it returns rows regardless
    of their materialization-format identifier.

    Args:
        db_session: Active async database session.
        owner: The user that requested the export jobs.
        survey: The source survey.
        statuses: Per-row lifecycle status drawn from
            ``{queued, running, succeeded, failed, expired}``.

    Returns:
        List of inserted export-job ids in insertion order.
    """
    inserted: List[str] = []
    for status_value in statuses:
        job = ExportJob(
            user_id=owner.id,
            survey_id=survey.id,
            format="csv",
            status=status_value,
        )
        db_session.add(job)
        await db_session.flush()
        inserted.append(job.id)
    return inserted


# ── Properties: one per admin endpoint ────────────────────────────────


# Feature: api-platform-export, Property 22: Admin inventory completeness
# Validates: Requirements 9.1
@pytest.mark.asyncio
@given(api_key_revoked_flags=_API_KEY_REVOKED_FLAGS)
@settings(
    max_examples=20,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
async def test_p22_admin_api_keys_inventory_matches_filter(
    api_key_revoked_flags: List[bool],
    async_client,
    db_session,
) -> None:
    """``/admin/api-keys`` returns exactly the non-revoked api_keys rows.

    For each Hypothesis example we add zero or more :class:`ApiKey`
    rows with random ``revoked_at`` settings, call the admin
    inventory endpoint with an admin JWT, then read back the table
    rows that satisfy the same ``revoked_at IS NULL`` predicate the
    route documents and assert set equality on the row ids. The
    empty-set case (every flag is ``True`` or the flag list is
    empty) is naturally covered by Hypothesis sampling near the
    boundary.
    """
    admin, owner, _ = await _make_admin_and_owner(db_session)
    await _insert_api_keys(db_session, owner, api_key_revoked_flags)

    admin_token = create_access_token(admin.id)
    resp = await async_client.get(
        "/api/v1/admin/api-keys",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert isinstance(body, list), (
        f"/admin/api-keys must return a JSON array; got {type(body).__name__}"
    )

    response_ids = {row["id"] for row in body}

    table_rows = (
        await db_session.execute(
            select(ApiKey).where(ApiKey.revoked_at.is_(None))
        )
    ).scalars().all()
    expected_ids = {r.id for r in table_rows}

    assert response_ids == expected_ids, (
        "Admin api-keys inventory disagreed with the api_keys table.\n"
        f"flags={api_key_revoked_flags!r}\n"
        f"response_ids={sorted(response_ids)!r}\n"
        f"expected_ids={sorted(expected_ids)!r}\n"
        f"missing_from_response={sorted(expected_ids - response_ids)!r}\n"
        f"extra_in_response={sorted(response_ids - expected_ids)!r}"
    )


# Feature: api-platform-export, Property 22: Admin inventory completeness
# Validates: Requirements 9.2
@pytest.mark.asyncio
@given(active_flags=_WEBHOOK_ACTIVE_FLAGS)
@settings(
    max_examples=20,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
async def test_p22_admin_webhooks_inventory_matches_filter(
    active_flags: List[bool],
    async_client,
    db_session,
) -> None:
    """``/admin/webhooks`` returns exactly the active webhook rows.

    For each Hypothesis example we add zero or more
    :class:`WebhookSubscription` rows with random ``active`` toggles,
    call the admin inventory endpoint, and assert the response set
    equals the table rows whose ``active`` flag is ``True``.
    """
    admin, owner, _ = await _make_admin_and_owner(db_session)
    await _insert_webhooks(db_session, owner, active_flags)

    admin_token = create_access_token(admin.id)
    resp = await async_client.get(
        "/api/v1/admin/webhooks",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert isinstance(body, list), (
        f"/admin/webhooks must return a JSON array; got {type(body).__name__}"
    )

    response_ids = {row["id"] for row in body}

    table_rows = (
        await db_session.execute(
            select(WebhookSubscription).where(
                WebhookSubscription.active.is_(True)
            )
        )
    ).scalars().all()
    expected_ids = {r.id for r in table_rows}

    assert response_ids == expected_ids, (
        "Admin webhooks inventory disagreed with the "
        "webhook_subscriptions table.\n"
        f"active_flags={active_flags!r}\n"
        f"response_ids={sorted(response_ids)!r}\n"
        f"expected_ids={sorted(expected_ids)!r}\n"
        f"missing_from_response={sorted(expected_ids - response_ids)!r}\n"
        f"extra_in_response={sorted(response_ids - expected_ids)!r}"
    )


# Feature: api-platform-export, Property 22: Admin inventory completeness
# Validates: Requirements 9.3
@pytest.mark.asyncio
@given(statuses=_EXPORT_JOB_STATUSES)
@settings(
    max_examples=20,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
async def test_p22_admin_exports_inventory_matches_table(
    statuses: List[str],
    async_client,
    db_session,
) -> None:
    """``/admin/exports`` returns every ``export_jobs`` row when unfiltered.

    The admin exports endpoint accepts optional ``since`` and
    ``until`` query parameters; this property covers the unfiltered
    case where no time bound is supplied. For each Hypothesis
    example we add zero or more :class:`ExportJob` rows of varying
    lifecycle status, call the endpoint with ``limit=500`` to lift
    the default pagination cap, and assert the response set equals
    the full ``export_jobs`` table.
    """
    admin, owner, survey = await _make_admin_and_owner(db_session)
    await _insert_export_jobs(db_session, owner, survey, statuses)

    admin_token = create_access_token(admin.id)
    resp = await async_client.get(
        "/api/v1/admin/exports?limit=500",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert isinstance(body, list), (
        f"/admin/exports must return a JSON array; got {type(body).__name__}"
    )

    response_ids = {row["id"] for row in body}

    table_rows = (
        await db_session.execute(select(ExportJob))
    ).scalars().all()
    expected_ids = {r.id for r in table_rows}

    assert response_ids == expected_ids, (
        "Admin exports inventory disagreed with the export_jobs table.\n"
        f"statuses={statuses!r}\n"
        f"response_ids={sorted(response_ids)!r}\n"
        f"expected_ids={sorted(expected_ids)!r}\n"
        f"missing_from_response={sorted(expected_ids - response_ids)!r}\n"
        f"extra_in_response={sorted(response_ids - expected_ids)!r}"
    )


# ── Empty-set unit pin ────────────────────────────────────────────────


# Feature: api-platform-export, Property 22: Admin inventory completeness
# Validates: Requirements 9.1, 9.2, 9.3
@pytest.mark.asyncio
async def test_p22_empty_set_returns_200_and_empty_list(
    async_client,
    db_session,
) -> None:
    """All three admin inventories return ``[]`` (HTTP 200) when nothing matches.

    Pins the empty-set clause of Reqs 9.1 / 9.2 / 9.3 explicitly so
    a regression that turns an empty inventory into a 404 surfaces
    here even before the property tests start exploring the
    state-space. The test inserts only an admin user (and the
    bookkeeping owner / survey rows that the helper creates) — no
    api keys, no webhook subscriptions, no export jobs — and walks
    each endpoint in turn.
    """
    admin, _owner, _survey = await _make_admin_and_owner(db_session)
    admin_token = create_access_token(admin.id)
    headers = {"Authorization": f"Bearer {admin_token}"}

    for path in (
        "/api/v1/admin/api-keys",
        "/api/v1/admin/webhooks",
        "/api/v1/admin/exports",
    ):
        resp = await async_client.get(path, headers=headers)
        assert resp.status_code == 200, (
            f"{path} should return 200 on empty match; "
            f"got {resp.status_code}: {resp.text}"
        )
        body = resp.json()
        assert body == [], (
            f"{path} should return [] on empty match; got {body!r}"
        )
