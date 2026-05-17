"""Property test P2: Rotation invalidates the previous secret.

Per design.md §Property 2 (Requirements 2.4), every rotation of an
API key's secret must immediately replace the credential bound to
the row::

    rotate(key) ⇒ previous plaintext yields 401  AND  new plaintext authenticates

The Hypothesis strategy generates rotation chains for one or more
keys belonging to the same owner. After every rotation in the chain
the test asserts:

* Every plaintext that pre-dates the latest rotation yields HTTP 401
  with one of the documented machine codes ``api_key_invalid`` or
  ``api_key_revoked`` (per ``app.core.deps._resolve_api_key_principal``,
  a stale plaintext fails prefix lookup or hash verification and is
  surfaced as ``api_key_invalid``; the ``api_key_revoked`` branch is
  accepted as a permissible alternative because revocation also
  satisfies "previous secret no longer authenticates").
* The latest plaintext authenticates as the owning user with HTTP 200.

The same property holds across multiple keys in flight: rotating key
A must not affect key B's currently-active plaintext, and rotating
key A again must invalidate the plaintext from the prior rotation
of A.

Implementation choice
---------------------

Rotation is driven by mutating ``ApiKey.key_prefix`` and
``ApiKey.key_hash`` in place and flushing — this is exactly what
:func:`app.api.v1.api_keys.rotate_api_key` writes on the production
path. Going through the live ``POST /{key_id}/rotate`` route would
require committing the per-example transaction (the route calls
``db.commit()``), which would close the conftest's outer transaction
and break the next Hypothesis example. The mutation-plus-flush pattern
matches the row-level effect of the route while keeping the savepoint
abstraction the conftest provides intact.

State management
----------------

Hypothesis re-invokes the test function once per example while
sharing the function-scoped ``db_session`` and ``async_client``
fixtures. Each example runs inside a SAVEPOINT and rolls back at
the end so per-example rows (whose ``api_keys.key_prefix`` carries a
UNIQUE INDEX) do not accumulate and birthday-collide across the
@settings(max_examples=100) sweep.

# Feature: api-platform-export, Property 2: Rotation invalidates the
# previous secret (API key portion)
# Validates: Requirements 2.4
"""

from __future__ import annotations

import uuid
from typing import List, Tuple

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from app.core.api_key_secret import generate_plaintext
from app.core.security import hash_password
from app.models.api_key import ApiKey
from app.models.user import User


# ── Strategy ──────────────────────────────────────────────────────────


@st.composite
def _rotation_plans(draw: st.DrawFn) -> List[int]:
    """Generate a per-key rotation count list for 1..3 keys.

    Each integer in the returned list is the number of rotations
    performed on that key after creation, drawn from 1..4. The lower
    bound of 1 keeps every example exercising the rotation path at
    least once; the upper bound of 4 exercises chains long enough
    that several intermediate plaintexts must coexist in memory and
    each be rejected on its own.

    Hypothesis shrinks toward fewer keys and shorter chains, so a
    failing example typically reduces to a single key with a single
    rotation — which matches the minimal counter-example shape the
    property is most useful at exposing.
    """
    n_keys = draw(st.integers(min_value=1, max_value=3))
    return [
        draw(st.integers(min_value=1, max_value=4)) for _ in range(n_keys)
    ]


# ── Test helpers ──────────────────────────────────────────────────────


async def _seed_user(db_session, *, email: str) -> User:
    """Insert a fresh User row visible to the request handler.

    Writes go through ``flush`` rather than ``commit`` so the row
    lives inside the test's outer transaction (and the per-example
    savepoint) and is rolled back at teardown. The handler injected
    via ``app.dependency_overrides[get_db]`` shares this same
    session, so flushed rows are immediately readable.
    """
    user = User(
        email=email,
        hashed_password=hash_password("Test1234!"),
        display_name="P2 Tester",
    )
    db_session.add(user)
    await db_session.flush()
    return user


async def _seed_api_key(db_session, *, user: User) -> Tuple[str, ApiKey]:
    """Mint a fresh API key and return its plaintext along with the row.

    Mirrors the persistence shape produced by
    :func:`app.api.v1.api_keys.create_api_key`: a new plaintext is
    generated via :func:`app.core.api_key_secret.generate_plaintext`,
    only ``key_prefix`` and ``key_hash`` are stored, and a single
    read scope is attached so the row matches what an interactive
    user would create.
    """
    plaintext, key_prefix, key_hash = generate_plaintext("live")
    row = ApiKey(
        user_id=user.id,
        name="p2-key",
        key_prefix=key_prefix,
        key_hash=key_hash,
        scopes=["survey:read"],
    )
    db_session.add(row)
    await db_session.flush()
    return plaintext, row


async def _rotate_in_place(db_session, row: ApiKey) -> str:
    """Rotate ``row``'s secret in place and return the new plaintext.

    Reproduces the row-level effect of
    :func:`app.api.v1.api_keys.rotate_api_key`: a fresh plaintext is
    minted, ``key_prefix`` and ``key_hash`` are overwritten, and the
    change is flushed so the auth resolver can see it on the next
    request. Writing the audit row that the production path emits is
    deliberately out of scope here — Property 19 covers audit
    emission separately, and avoiding the audit write keeps this test
    focused on the credential-rotation invariant Req 2.4 talks about.
    """
    new_plaintext, new_prefix, new_hash = generate_plaintext("live")
    row.key_prefix = new_prefix
    row.key_hash = new_hash
    await db_session.flush()
    return new_plaintext


# ── Property ──────────────────────────────────────────────────────────


# Feature: api-platform-export, Property 2: Rotation invalidates the
# previous secret (API key portion)
# Validates: Requirements 2.4
@given(rotations_per_key=_rotation_plans())
@settings(
    max_examples=100,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
async def test_p2_rotation_invalidates_previous_secret(
    async_client,
    db_session,
    rotations_per_key: List[int],
) -> None:
    """Each rotation invalidates every prior plaintext for that key.

    The example mints one or more API keys for a fresh owner, then
    drives the rotation chain described by ``rotations_per_key``.
    After every rotation step the test asserts:

    * Every plaintext that pre-dates the just-completed rotation
      yields HTTP 401 with machine code ``api_key_invalid`` or
      ``api_key_revoked`` when used at ``GET /api/v1/auth/me``.
    * The latest plaintext for that key authenticates as the owning
      user (HTTP 200 with the seeded email).
    * Active plaintexts on *other* keys keep authenticating —
      rotation of key A must not collateral-damage key B.

    The endpoint under test is ``GET /api/v1/auth/me`` because it is
    the smallest authenticated endpoint that echoes the user's
    email back, which lets us verify the resolver-mapped principal
    matches the seeded user without standing up additional
    fixtures.

    Args:
        async_client: HTTPX async test client wired to the FastAPI
            app with a fixture-scoped DB session injected.
        db_session: Async SQLAlchemy session shared with the
            request handlers via dependency override.
        rotations_per_key: Number of rotations to perform on each
            generated key, in declaration order.
    """
    savepoint = await db_session.begin_nested()
    try:
        # Unique email per example so handler-side reads through the
        # shared session never collide on ``users.email``'s UNIQUE
        # constraint, even though the savepoint rolls these rows
        # back at the end of the example.
        email = f"p2-{uuid.uuid4().hex}@example.com"
        user = await _seed_user(db_session, email=email)

        # Track each key's full plaintext history: index 0 is the
        # original, the last entry is the current active plaintext.
        # ``rotation_per_key[i]`` rotations are then applied to
        # ``keys[i]``.
        keys: List[Tuple[ApiKey, List[str]]] = []
        for _ in rotations_per_key:
            plaintext, row = await _seed_api_key(db_session, user=user)
            keys.append((row, [plaintext]))

        for key_idx, n_rotations in enumerate(rotations_per_key):
            row, history = keys[key_idx]
            for _ in range(n_rotations):
                new_plaintext = await _rotate_in_place(db_session, row)
                history.append(new_plaintext)

                # Every plaintext that pre-dates this rotation must
                # now be rejected with 401 + one of the documented
                # machine codes. The auth resolver normally surfaces
                # ``api_key_invalid`` for stale plaintexts (prefix
                # mismatch or hash mismatch); ``api_key_revoked`` is
                # accepted as a permissible alternative for symmetry
                # with future implementations that may proactively
                # mark superseded rows.
                for stale_plaintext in history[:-1]:
                    response = await async_client.get(
                        "/api/v1/auth/me",
                        headers={"X-API-Key": stale_plaintext},
                    )
                    assert response.status_code == 401, (
                        f"stale plaintext after rotation #{n_rotations} "
                        f"on key {key_idx} returned "
                        f"{response.status_code}: {response.text}"
                    )
                    body = response.json()
                    err = body.get("detail", {}).get("error")
                    assert err in {"api_key_invalid", "api_key_revoked"}, (
                        f"stale plaintext yielded unexpected machine "
                        f"code {err!r}: {body!r}"
                    )

                # The fresh plaintext for the rotating key must
                # authenticate as the seeded owner.
                response = await async_client.get(
                    "/api/v1/auth/me",
                    headers={"X-API-Key": new_plaintext},
                )
                assert response.status_code == 200, (
                    f"new plaintext after rotation on key {key_idx} "
                    f"returned {response.status_code}: {response.text}"
                )
                assert response.json()["email"] == email, (
                    f"new plaintext on key {key_idx} resolved to "
                    f"wrong user: {response.json()!r}"
                )

                # Active plaintexts on every *other* key must keep
                # authenticating — rotation of one key must not
                # invalidate sibling credentials.
                for other_idx, (_other_row, other_history) in enumerate(keys):
                    if other_idx == key_idx:
                        continue
                    other_active = other_history[-1]
                    response = await async_client.get(
                        "/api/v1/auth/me",
                        headers={"X-API-Key": other_active},
                    )
                    assert response.status_code == 200, (
                        f"sibling key {other_idx} broke during rotation "
                        f"of key {key_idx}: {response.status_code} / "
                        f"{response.text}"
                    )
                    assert response.json()["email"] == email
    finally:
        # Roll the savepoint back unconditionally so the next example
        # starts from a clean slate. ``is_active`` guards against a
        # double-rollback if the savepoint already closed (for
        # example, due to a constraint violation surfaced inside the
        # block).
        if savepoint.is_active:
            await savepoint.rollback()
