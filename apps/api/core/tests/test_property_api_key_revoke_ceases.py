"""Property test P4 (key portion): revoke ceases subsequent activity.

The strategy creates ``N`` API keys for a fresh user (``N`` drawn from
1..5), revokes a random subset of those keys, then dispatches an
HTTP request with each plaintext through :data:`async_client`. The
property under test, drawn directly from Req 2.5, is::

    revoked_at IS NOT NULL  ⇒  HTTP 401 with error="api_key_revoked"
    revoked_at IS NULL      ⇒  HTTP 200 with the owner user payload

Revocation is performed by mutating ``ApiKey.revoked_at`` and flushing
the session, mirroring exactly what
:func:`app.api.v1.api_keys.revoke_api_key` writes; this isolates the
auth-resolver behaviour the property is interested in from the
unrelated JWT-only management surface that emits the audit row.

State management
----------------

Hypothesis re-invokes the test function once per example while sharing
the function-scoped ``db_session`` and ``async_client`` fixtures. The
``api_keys.key_prefix`` column carries a UNIQUE INDEX, and each
plaintext only contributes 18 bits of entropy to the 11-character
prefix; over 100 examples × up to 5 keys each that birthday-paradox
collision rate is high enough to cause spurious failures. Each
example therefore runs inside its own SAVEPOINT and rolls back at the
end so per-example rows do not accumulate.

# Feature: api-platform-export, Property 4: Revoke and delete cease
# subsequent activity (API key clause)
# Validates: Requirements 2.5
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import List, Tuple

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from app.core.api_key_secret import generate_plaintext
from app.core.security import hash_password
from app.models.api_key import ApiKey
from app.models.user import User


async def _seed_user(db_session, *, email: str) -> User:
    """Insert a fresh User row visible to the request handler.

    Writes go through ``flush`` rather than ``commit`` so the row lives
    inside the test's outer transaction (and the per-example savepoint)
    and is rolled back at teardown without polluting the database. The
    handler injected via ``app.dependency_overrides[get_db]`` shares
    this same session, so flushed rows are immediately readable.
    """
    user = User(
        email=email,
        hashed_password=hash_password("Test1234!"),
        display_name="P4 Tester",
    )
    db_session.add(user)
    await db_session.flush()
    return user


async def _seed_api_key(db_session, *, user: User) -> Tuple[str, ApiKey]:
    """Mint a fresh API key for ``user`` and return its plaintext + row.

    Mirrors the persistence shape produced by
    :func:`app.api.v1.api_keys.create_api_key`: a brand-new plaintext
    is generated via :func:`app.core.api_key_secret.generate_plaintext`,
    only ``key_prefix`` and ``key_hash`` are stored, and the scope list
    is populated with a single read scope so the row matches what an
    interactive user would create.
    """
    plaintext, key_prefix, key_hash = generate_plaintext("live")
    row = ApiKey(
        user_id=user.id,
        name="p4-key",
        key_prefix=key_prefix,
        key_hash=key_hash,
        scopes=["survey:read"],
    )
    db_session.add(row)
    await db_session.flush()
    return plaintext, row


# Feature: api-platform-export, Property 4: Revoke and delete cease
# subsequent activity (API key clause)
# Validates: Requirements 2.5
@given(
    n_keys=st.integers(min_value=1, max_value=5),
    revoke_mask_seed=st.integers(min_value=0, max_value=(1 << 5) - 1),
)
@settings(
    max_examples=100,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
async def test_p4_revoked_keys_yield_401_and_active_keys_succeed(
    async_client,
    db_session,
    n_keys: int,
    revoke_mask_seed: int,
) -> None:
    """For every (n_keys, subset) draw, revoked keys 401 and active keys 200.

    The bitmask drawn by ``revoke_mask_seed`` selects which of the
    ``n_keys`` rows is revoked: bit ``i`` set means key ``i`` is
    revoked. The mask is drawn from the full ``[0, 2**5 - 1]`` range
    so every example exercises one of the 32 possible subset shapes,
    including the boundary cases of "revoke none" (mask 0) and
    "revoke all" (lower ``n_keys`` bits set).

    For each plaintext the test issues a ``GET /api/v1/auth/me`` via
    :data:`async_client` and asserts:

    * Revoked keys produce HTTP 401 with body
      ``{"detail": {"error": "api_key_revoked"}}``, exactly as
      :func:`app.core.deps._resolve_api_key_principal` is documented
      to emit on the revoked-key branch.
    * Non-revoked keys produce HTTP 200 with the owner user's email,
      confirming the auth resolver still accepts the key after
      sibling keys have been revoked.

    Args:
        async_client: HTTPX async test client wired to the FastAPI app
            with a fixture-scoped DB session injected.
        db_session: Async SQLAlchemy session shared with the request
            handlers via dependency override.
        n_keys: Number of API keys to mint for the example (1-5).
        revoke_mask_seed: Bitmask selecting which keys to revoke.
    """
    # Open a savepoint so per-example rows do not accumulate in the
    # outer test transaction. Without this, ``api_keys.key_prefix``
    # UNIQUE collisions become likely after a few hundred minted keys.
    savepoint = await db_session.begin_nested()
    try:
        # Unique email per example: even though we roll the savepoint
        # back, mid-example reads from the request handler share the
        # session, so the email needs to be unambiguous within this
        # example's window of visibility.
        email = f"p4-{uuid.uuid4().hex}@example.com"
        user = await _seed_user(db_session, email=email)

        keys: List[Tuple[str, ApiKey]] = []
        for _ in range(n_keys):
            plaintext, row = await _seed_api_key(db_session, user=user)
            keys.append((plaintext, row))

        # Revoke the selected subset by mutating ``revoked_at`` and
        # flushing — this matches the on-disk effect of the production
        # ``POST /{key_id}/revoke`` route, which is the operation Req
        # 2.5 ties the 401-on-subsequent-request guarantee to.
        revoked_indices = {
            i for i in range(n_keys) if (revoke_mask_seed >> i) & 1 == 1
        }
        now = datetime.now(timezone.utc)
        for idx in revoked_indices:
            keys[idx][1].revoked_at = now
        await db_session.flush()

        # Verify each plaintext: revoked keys are rejected with the
        # documented machine code, active keys authenticate as the
        # owner. We hit ``/api/v1/auth/me`` because it is the smallest
        # endpoint that requires authentication and echoes the user's
        # email back to the test.
        for idx, (plaintext, _row) in enumerate(keys):
            response = await async_client.get(
                "/api/v1/auth/me",
                headers={"X-API-Key": plaintext},
            )
            if idx in revoked_indices:
                assert response.status_code == 401, (
                    f"revoked key idx={idx} returned "
                    f"{response.status_code}: {response.text}"
                )
                body = response.json()
                assert body["detail"]["error"] == "api_key_revoked", (
                    f"revoked key idx={idx} wrong machine code: {body!r}"
                )
            else:
                assert response.status_code == 200, (
                    f"active key idx={idx} returned "
                    f"{response.status_code}: {response.text}"
                )
                assert response.json()["email"] == email, (
                    f"active key idx={idx} resolved to wrong user: "
                    f"{response.json()!r}"
                )
    finally:
        # Roll the savepoint back unconditionally so the next example
        # starts from a clean slate. ``is_active`` guards against
        # double-rollback if the savepoint already closed (for
        # example, due to a constraint violation surfaced inside the
        # block).
        if savepoint.is_active:
            await savepoint.rollback()
