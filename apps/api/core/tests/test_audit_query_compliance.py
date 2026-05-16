"""Smoke checks for the T10 compliance export wiring (Task 17.1, Req 9.5).

These tests are import-only: they exercise the verb-registry contract that
keeps the T10 PIPL/GDPR audit-log export and the T15 API Open Platform
audit verbs in sync. They do not touch the database.

The contract being protected:

1. :mod:`app.services.audit_query` (the compliance export entry point)
   selects rows by time range only — no verb whitelist is applied by
   default, so every T15 verb in the requested window appears in the
   export.
2. The module-level ``_COMPLIANCE_EXPORT_VERB_WHITELIST`` sentinel
   documents that contract. If a future change introduces a whitelist,
   it must remain a superset of
   :data:`app.core.audit.API_PLATFORM_VERBS`.
"""

from __future__ import annotations

import inspect

from app.core.audit import API_PLATFORM_VERBS
from app.services import audit_query


def test_api_platform_verbs_are_complete_for_req_9_5() -> None:
    """The T15 verb set must cover every category called out in Req 9.5.

    Req 9 AC5 enumerates: API key lifecycle, webhook subscription
    configuration, webhook delivery outcomes, export job lifecycle, and
    rate-limit rejection events. Each category must contribute at least
    one verb to :data:`API_PLATFORM_VERBS` so the time-range-only
    compliance export actually surfaces them.
    """
    expected_prefixes = (
        "api_key.",
        "webhook.subscription.",
        "webhook.delivery.",
        "export.job.",
        "rate_limit.",
    )
    for prefix in expected_prefixes:
        assert any(v.startswith(prefix) for v in API_PLATFORM_VERBS), (
            f"API_PLATFORM_VERBS is missing any verb with prefix {prefix!r} "
            "required by Req 9.5"
        )


def test_compliance_export_has_no_default_verb_whitelist() -> None:
    """The T10 compliance export must not silently filter out new verbs.

    The sentinel :attr:`_COMPLIANCE_EXPORT_VERB_WHITELIST` is the explicit
    anchor of the time-range-only contract. ``None`` means "every verb in
    the window is exported" — that is the intended state per design §10.
    """
    assert audit_query._COMPLIANCE_EXPORT_VERB_WHITELIST is None, (
        "T10 compliance export gained a verb whitelist; review Req 9.5 "
        "and ensure all API_PLATFORM_VERBS remain included."
    )


def test_compliance_export_whitelist_would_cover_t15_verbs() -> None:
    """If a whitelist is ever introduced, it must include every T15 verb.

    Today the sentinel is ``None`` (no whitelist), so this test simulates
    the future case: any non-``None`` whitelist must be a superset of
    :data:`API_PLATFORM_VERBS`. This mirrors the inline assertion that
    runs at import time in :mod:`app.services.audit_query`.
    """
    whitelist = audit_query._COMPLIANCE_EXPORT_VERB_WHITELIST
    if whitelist is None:
        # Default state — exercised by the import-time assertion in the
        # module itself; nothing else to check here.
        return
    missing = API_PLATFORM_VERBS - whitelist
    assert not missing, (
        f"Compliance export whitelist is missing T15 verbs: {sorted(missing)} "
        "(Req 9.5)."
    )


def test_query_audit_logs_signature_supports_time_range_only() -> None:
    """The compliance export caller must be able to pass time range only.

    Specifically, ``query_audit_logs`` must accept ``since`` and ``until``
    as keyword-only parameters and must NOT require a verb filter. Calling
    it with only ``since`` and ``until`` (and no ``action``/``actions``)
    is the canonical T10 compliance export invocation.
    """
    sig = inspect.signature(audit_query.query_audit_logs)
    params = sig.parameters

    for name in ("since", "until", "action", "actions"):
        assert name in params, f"query_audit_logs is missing parameter {name!r}"
        assert params[name].default is None, (
            f"query_audit_logs parameter {name!r} must default to None so "
            "callers can omit it; the compliance export relies on this."
        )
