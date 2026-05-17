"""Encrypt webhook signing secrets at rest (post-T15 fix).

Revision ID: 0012
Revises: 0011
Create Date: 2026-05-17

This migration is the schema half of the post-T15 production bug fix
that resolves the conflict between Req 3 AC3 ("store secret only as a
salted hash") and Req 4 AC3 ("HMAC-SHA256 keyed by the subscription's
current signing secret over the request body bytes"). SHA-256 is one-way
so HMAC signing requires reversible at-rest storage; the original
implementation chose plaintext, violating Property 1 (plaintext
credential exposure exactly-once).

The chosen resolution is Fernet symmetric encryption keyed by the new
``Settings.webhook_secret_encryption_key`` setting; the helper module
:mod:`app.core.webhook_secret_crypto` performs encrypt/decrypt and the
delivery worker decrypts on every signing pass.

Schema changes:
    - Rename ``webhook_subscriptions.signing_secret_hash`` to
      ``signing_secret_ciphertext``. The new column holds the Fernet
      ciphertext (base64 url-safe ASCII, ~120 chars for a typical
      webhook secret) rather than a 64-character SHA-256 hex digest.
      The old name carried "hash" in its identifier even though the
      original implementation stored plaintext; the rename to
      ``ciphertext`` reflects the new (correct) semantics.
    - Rename ``webhook_subscriptions.previous_secret_hash`` to
      ``previous_secret_ciphertext`` for the same reason.

Column-type note:
    The pre-fix columns were ``VARCHAR(64)`` because they were sized
    for a SHA-256 hex digest. Fernet tokens are longer than 64 chars,
    so this migration also widens both columns to ``VARCHAR(512)``.
    512 is comfortably larger than the ~120-char ciphertext produced
    by ``Fernet.encrypt`` over a ``whsec_<24 chars>`` plaintext, with
    headroom for any future format change.

Production-data migration (out of scope):
    For the dev environment we accept that existing
    ``signing_secret_hash`` values are invalidated by this migration:
    they were plaintext under the buggy implementation, but the
    delivery worker post-fix expects Fernet ciphertext and will fail
    decryption on legacy rows. Production environments must perform a
    custom data migration step before this migration runs:

        1. Read each row's plaintext from
           ``signing_secret_hash`` (assumed plaintext under the bug).
        2. Encrypt with :func:`app.core.webhook_secret_crypto.encrypt_signing_secret`.
        3. ``UPDATE webhook_subscriptions SET signing_secret_ciphertext = :ct``
           after the rename.

    That custom step is intentionally not included here because (a)
    the dev environment has no production data to preserve and (b)
    the access pattern requires the new encryption key to already be
    configured, which is a deployment-time concern this Alembic
    revision should not assume. The follow-up section in tasks.md
    flags the production migration as a separate work item.

Validates: post-T15 fix for Property 1 (webhook clause), Requirements
3.1, 3.4, 4.3.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers
revision: str = "0012"
down_revision: Union[str, None] = "0011"
branch_labels: Union[Sequence[str], None] = None
depends_on: Union[Sequence[str], None] = None


def upgrade() -> None:
    """Rename the two webhook signing-secret columns to reflect ciphertext storage.

    Both columns are renamed in place via ``ALTER TABLE ... RENAME COLUMN``
    so existing FKs, indices, and constraints survive the rename
    untouched. The columns are also widened to ``VARCHAR(512)`` to fit
    Fernet ciphertext, which is meaningfully longer than the 64-char
    SHA-256 hex digest the original schema sized for.

    No data-migration step runs here. Existing rows in the dev
    environment will hold legacy plaintext values that the post-fix
    delivery worker cannot decrypt; this is acceptable because the
    column has never carried real production data in the dev
    environment. Production must run a custom data-migration step
    before applying this revision (see module docstring).
    """
    op.alter_column(
        "webhook_subscriptions",
        "signing_secret_hash",
        new_column_name="signing_secret_ciphertext",
        existing_type=sa.String(64),
        type_=sa.String(512),
        existing_nullable=False,
    )
    op.alter_column(
        "webhook_subscriptions",
        "previous_secret_hash",
        new_column_name="previous_secret_ciphertext",
        existing_type=sa.String(64),
        type_=sa.String(512),
        existing_nullable=True,
    )


def downgrade() -> None:
    """Reverse the rename, restoring the legacy column names.

    Restores ``signing_secret_hash`` and ``previous_secret_hash`` and
    narrows the type back to ``VARCHAR(64)``. After downgrade, any
    Fernet ciphertext written under the upgraded schema will exceed
    the 64-char limit and the narrow operation will fail on those
    rows; the dev environment treats this as acceptable for the same
    reason ``upgrade()`` does not run a data migration.
    """
    op.alter_column(
        "webhook_subscriptions",
        "previous_secret_ciphertext",
        new_column_name="previous_secret_hash",
        existing_type=sa.String(512),
        type_=sa.String(64),
        existing_nullable=True,
    )
    op.alter_column(
        "webhook_subscriptions",
        "signing_secret_ciphertext",
        new_column_name="signing_secret_hash",
        existing_type=sa.String(512),
        type_=sa.String(64),
        existing_nullable=False,
    )
