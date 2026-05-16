"""Business logic for sample distribution management.

Contains reusable functions called by API routers:
- CSV recipient parsing (supports Chinese and English column headers)
- Demographic-to-quota matching
- Recipient count recalculation
"""

from __future__ import annotations

import csv
import io
import re
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.recipient import Recipient
from ..models.quota import Quota
from ..models.sample_group import SampleGroup
from .webhook_emitter import emit_webhook_event


# ── CSV Import ──────────────────────────────────────────────────────────


def parse_csv_recipients(content: str) -> tuple[list[dict], list[str]]:
    """Parse CSV content into recipient dicts.

    Column name auto-detection:
    - ``email`` / ``邮箱`` → ``email`` field
    - ``name`` / ``姓名`` → ``name`` field
    - All other columns → ``demographics`` dict

    Args:
        content: Raw CSV file content as string.

    Returns:
        (valid_recipients, errors) — each recipient is {email, name, demographics}.
    """
    # Strip BOM if present (common in Excel exports)
    if content.startswith("﻿"):
        content = content[1:]

    reader = csv.DictReader(io.StringIO(content))
    if not reader.fieldnames:
        return [], ["CSV 文件为空或缺少列标题"]

    recipients: list[dict] = []
    errors: list[str] = []

    # Detect column name mappings (case-insensitive)
    col_map = _detect_columns(reader.fieldnames)

    for row_num, row in enumerate(reader):
        line_num = row_num + 2  # 1-based, +1 for header

        # Skip completely empty rows
        if not any(v.strip() for v in row.values() if v):
            continue

        email = _extract_value(row, col_map.get("email")).strip() or None
        name = _extract_value(row, col_map.get("name")).strip() or None

        # At least email or name is required
        if not email and not name:
            errors.append(f"第 {line_num} 行: 至少需要邮箱或姓名")
            continue

        # Validate email format if provided
        if email and not _is_valid_email(email):
            errors.append(f"第 {line_num} 行: 邮箱格式无效 ({email})")
            continue

        # Build demographics from remaining columns
        demographics: dict = {}
        for col in reader.fieldnames or []:
            if col not in col_map.values() and col not in col_map:
                val = (row.get(col) or "").strip()
                if val:
                    demographics[col.strip()] = val

        recipients.append({
            "email": email,
            "name": name,
            "demographics": demographics,
        })

    return recipients, errors


def _detect_columns(fieldnames: list[str]) -> dict[str, str]:
    """Map known column aliases to canonical names.

    Returns a dict mapping canonical key → actual column name.
    """
    canonical = {"email": "", "name": ""}
    email_aliases = {"email", "邮箱", "e-mail", "mail", "电子邮件"}
    name_aliases = {"name", "姓名", "名字", "名称", "full name", "fullname"}

    for col in fieldnames:
        col_lower = col.strip().lower()
        if col_lower in email_aliases:
            canonical["email"] = col
        elif col_lower in name_aliases:
            canonical["name"] = col

    # Fallback: if no alias matched, use direct fieldname
    if not canonical["email"]:
        for col in fieldnames:
            if col.strip().lower() in email_aliases:
                canonical["email"] = col
                break
    if not canonical["name"]:
        for col in fieldnames:
            if col.strip().lower() in name_aliases:
                canonical["name"] = col
                break

    return canonical


def _extract_value(row: dict, col_name: str | None) -> str:
    """Safely extract a value from a CSV row."""
    if not col_name:
        return ""
    return (row.get(col_name) or "").strip()


def _is_valid_email(email: str) -> bool:
    """Basic email format validation."""
    pattern = r"^[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}$"
    return bool(re.match(pattern, email))


# ── Recipient Count ──────────────────────────────────────────────────────


async def update_recipient_count(
    db: AsyncSession, sample_group_id: str
) -> int:
    """Recalculate and update ``recipient_count`` for a sample group.

    Called after any recipient creation or deletion.
    """
    result = await db.execute(
        select(func.count())
        .select_from(Recipient)
        .where(Recipient.sample_group_id == sample_group_id)
    )
    count = result.scalar() or 0

    await db.execute(
        update(SampleGroup)
        .where(SampleGroup.id == sample_group_id)
        .values(recipient_count=count)
    )
    return count


# ── Token Lookup ─────────────────────────────────────────────────────────


async def match_recipient_from_token(
    db: AsyncSession, token: str
) -> Recipient | None:
    """Look up a recipient by their unique token."""
    result = await db.execute(
        select(Recipient).where(Recipient.unique_token == token)
    )
    return result.scalar_one_or_none()


# ── Quota Matching ───────────────────────────────────────────────────────


async def update_quota_on_response(
    db: AsyncSession, recipient_id: str, survey_id: str
) -> list[str]:
    """When a recipient completes a survey, check and increment matching quotas.

    For each active quota on the survey that is not yet full, check whether
    the recipient's demographics satisfy the quota criteria. If so, increment
    ``current_count``. When that increment causes ``current_count`` to reach
    ``target_count`` for the first time, emit a ``quota.reached`` webhook
    event.

    The function does not commit; it flushes the new ``WebhookDelivery``
    rows so the caller can enqueue Celery tasks for them after committing
    the surrounding transaction. Returns the list of newly created
    ``WebhookDelivery`` ids (possibly empty).
    """
    delivery_ids: list[str] = []

    # Fetch recipient demographics
    result = await db.execute(
        select(Recipient).where(Recipient.id == recipient_id)
    )
    recipient = result.scalar_one_or_none()
    if not recipient or not recipient.demographics:
        return delivery_ids

    # Fetch active, non-full quotas for this survey
    result = await db.execute(
        select(Quota).where(
            Quota.survey_id == survey_id,
            Quota.is_active == True,
            Quota.current_count < Quota.target_count,
        )
    )
    quotas = result.scalars().all()

    for quota in quotas:
        if _demographics_match(recipient.demographics, quota.criteria):
            quota.current_count += 1
            db.add(quota)
            # Emit quota.reached on the transition into "full". The
            # database guard (current_count < target_count above)
            # ensures we only ever cross this boundary once per quota.
            if quota.current_count >= quota.target_count:
                ids = await emit_webhook_event(
                    db,
                    event_type="quota.reached",
                    survey_id=quota.survey_id,
                    payload={
                        "survey_id": quota.survey_id,
                        "quota_id": quota.id,
                        "quota_name": quota.name,
                        "dimension": quota.dimension,
                        "target_count": quota.target_count,
                        "current_count": quota.current_count,
                        "filled_at": datetime.now(timezone.utc).isoformat(),
                    },
                )
                delivery_ids.extend(ids)

    return delivery_ids


def _demographics_match(recipient_demo: dict, quota_criteria: dict) -> bool:
    """Check if recipient demographics satisfy all quota criteria key-value pairs.

    Only the keys specified in ``quota_criteria`` are checked. Extra keys
    in ``recipient_demo`` are ignored.
    """
    if not quota_criteria:
        return False
    for key, value in quota_criteria.items():
        if str(recipient_demo.get(key, "")) != str(value):
            return False
    return True


# ── Distribution Status Helpers ──────────────────────────────────────────


async def compute_distribution_counts(
    db: AsyncSession, sample_group_id: str
) -> dict[str, int]:
    """Get status counts for a sample group's recipients."""
    result = await db.execute(
        select(
            func.count().filter(Recipient.status == "pending").label("pending"),
            func.count().filter(Recipient.status == "sent").label("sent"),
            func.count().filter(Recipient.status == "opened").label("opened"),
            func.count().filter(Recipient.status == "started").label("started"),
            func.count().filter(Recipient.status == "completed").label("completed"),
        ).where(Recipient.sample_group_id == sample_group_id)
    )
    row = result.one()
    return {
        "pending": row.pending or 0,
        "sent": row.sent or 0,
        "opened": row.opened or 0,
        "started": row.started or 0,
        "completed": row.completed or 0,
    }
