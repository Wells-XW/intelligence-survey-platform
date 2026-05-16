# Implementation Plan: API Open Platform and Export Enhancement

## Overview

This plan implements the four backend subsystems described in design.md (API key lifecycle, webhook subscriptions and delivery, multi-format async export, per-key rate limiting) on top of the existing FastAPI service at `apps/api/core/app/`. Implementation order is driven by data and runtime dependencies: each Alembic migration (0008 through 0011) lands before any code that reads from or writes to the tables it creates, the shared `Principal` auth resolver lands before any new router, and the rate limiter middleware lands after the resolver so its Redis path can key on a known `api_key.id`. The frontend admin pane is out of scope; tasks stop at the backend admin endpoints that a future React page will consume.

Code conventions honored throughout:

- Python 3.9 type hints (`Optional[X]` rather than `X | None`); `from __future__ import annotations` where it lets us avoid forward-reference strings.
- Google-style docstrings on every public function or class; type hints required on public functions.
- Tests partitioned into pure-function unit tests (no DB, no Redis), Hypothesis property-based tests with `max_examples=100` (lowered to 20 for SAV/SAS file roundtrips per design §Testing Strategy), and integration tests against local Docker Postgres + Redis.
- conventional commit messages (`feat:` / `fix:` / `test:` / `chore:`).

Property tasks reference design properties P1 through P25 and the requirements clauses they validate. Each property is its own sub-task and is placed close to the implementation it covers so a property failure surfaces as soon as the underlying code lands.

## Tasks

- [x] 1. Shared infrastructure: settings, Celery queues, audit verb registry
  - [x] 1.1 Extend `apps/api/core/app/config.py` Settings with the new tunables
    - Add `RATE_LIMIT_DEFAULT_PER_MINUTE`, `RATE_LIMIT_DEFAULT_PER_HOUR`, `RATE_LIMIT_DEFAULT_PER_DAY` (defaults 60 / 1200 / 10000).
    - Add `EXPORT_STORAGE_ROOT` (default `storage/exports`), `EXPORT_RETENTION_HOURS` (default 168), `EXPORT_DOWNLOAD_TOKEN_TTL_SECONDS` (default 900).
    - Add `WEBHOOK_DELIVERY_TIMEOUT_SECONDS` (default 10) and `WEBHOOK_RETRY_SCHEDULE_SECONDS` (tuple `(60, 300, 1800, 7200, 43200)`).
    - Add `API_KEY_INACTIVITY_THRESHOLD_DAYS` (default 90).
    - Use `Optional[X]` not `X | None`; type-hinted via Pydantic Settings.
    - _Requirements: 4.5, 5.12, 6.5, 2.9_
  - [x] 1.2 Register the `webhooks` and `exports` Celery queues
    - Update the existing Celery app factory (`apps/api/core/app/tasks/__init__.py` or its current home) to declare the two new queues with their routing keys.
    - Add worker concurrency hints in module docstrings: `webhooks` concurrency 8 prefetch 4, `exports` concurrency 2 max-tasks-per-child 50.
    - _Requirements: 4.1, 5.4_
  - [x] 1.3 Add the new audit verb constants to `apps/api/core/app/core/audit.py`
    - Define a frozen set of the new action verbs (`api_key.create`, `api_key.rotate`, `api_key.revoke`, `api_key.admin_revoke`, `webhook.subscription.create`, `.update`, `.rotate_secret`, `.delete`, `webhook.delivery.succeeded`, `webhook.delivery.failed`, `export.job.created`, `.succeeded`, `.failed`, `.expired`, `rate_limit.rejected`, `rate_limiter.backend_unavailable`).
    - Do not modify the existing `audit_logs` schema; map all extras into `details` JSONB.
    - _Requirements: 7.1, 7.2, 7.3, 7.4, 7.5, 7.8_
  - [ ]* 1.4 Unit test the audit row schema mapper
    - Verify reserved-column keys are dropped silently and the schema-compatible subset survives in `details`.
    - _Requirements: 7.9_

- [x] 2. Migration 0008 and User.is_admin + ApiKey table
  - [x] 2.1 Write Alembic revision 0008 `add_api_keys_and_admin_flag.py`
    - `down_revision = "0007"`. Adds `users.is_admin BOOLEAN NOT NULL DEFAULT false`. Creates `api_keys` table per design §Data Models 0008 with all columns and indices including the partial index `(revoked_at) WHERE revoked_at IS NULL`.
    - Provide a working `downgrade()` that drops the table and removes the column.
    - _Requirements: 2.1, 2.5, 2.8, 9.4_
  - [x] 2.2 Add the SQLAlchemy `ApiKey` model at `apps/api/core/app/models/api_key.py`
    - Mirror migration 0008 columns; relationship `user = relationship("User", back_populates="api_keys")`.
    - Add `is_admin` column to existing `User` model and the `api_keys` back-populates relationship.
    - Use Google-style class docstring describing the lifecycle states.
    - _Requirements: 2.1, 2.5_
  - [ ]* 2.3 Smoke test for migration chain integrity
    - Run alembic upgrade head against an empty test database in a fixture, assert the chain is contiguous from `0007` through `0008`.
    - _Requirements: 2.1_

- [x] 3. Component 1: Auth resolution dependency (`get_principal`)
  - [x] 3.1 Implement `Principal` dataclass and `get_principal` dependency in `apps/api/core/app/core/deps.py`
    - Frozen dataclass with `user: User`, `api_key: Optional[ApiKey]`, `scopes: FrozenSet[str]`.
    - Resolution order per design §Auth resolution flow: JWT first, then `Authorization: Bearer sk_...`, then `X-API-Key` header.
    - Reject revoked / expired keys with 401 + machine codes `api_key_revoked` / `api_key_expired`; reject when owner disabled with 401 + `owner_disabled`.
    - Best-effort `last_used_at` stamping (swallow exceptions).
    - Re-implement `get_current_user` as `principal.user` of `get_principal` so existing routers gain API-key support unchanged.
    - Add `require_scope(label: str)` helper that returns a dependency raising 403 + `insufficient_scope` for scope-missing key callers; JWT principals always pass.
    - _Requirements: 2.2, 2.6, 2.7, 8.1, 8.2, 8.3, 8.4, 8.5, 8.6_
  - [x] 3.2 Hash and validate API key plaintext in a small pure helper at `apps/api/core/app/core/api_key_secret.py`
    - `generate_plaintext(env: str) -> tuple[str, str, str]` returning `(plaintext, key_prefix, sha256_hex)`.
    - `verify(plaintext: str, expected_hash: str) -> bool` using `hmac.compare_digest`.
    - _Requirements: 2.3_
  - [ ]* 3.3 Property test P5: Expired credential rejection
    - **Property 5: Expired credential rejection**
    - Hypothesis strategy generates `ApiKey` rows with `expires_at` drawn from the past and from the future; assert past keys yield 401 + `api_key_expired` and future keys authenticate.
    - `@settings(max_examples=100)`.
    - **Validates: Requirements 2.6**
  - [ ]* 3.4 Property test P7: Authentication and authorization composition
    - **Property 7: Authentication and authorization composition**
    - Strategy generates `(jwt_validity, api_key_validity, scopes, rbac_role, required_role, required_scope)` tuples; reference predicate is implemented in the test as the spec from design §Property 7; assert `get_principal` plus `require_scope` plus `check_survey_permission` agrees with the predicate on every example.
    - `@settings(max_examples=100)`.
    - **Validates: Requirements 2.2, 2.7, 8.1, 8.2, 8.3, 8.4, 8.5, 8.6**

- [x] 4. Component 2: API Key service routes
  - [x] 4.1 Implement `apps/api/core/app/api/v1/api_keys.py`
    - Routes: `POST /` (create), `GET /` (list own), `POST /{key_id}/rotate`, `POST /{key_id}/revoke`, `DELETE /{key_id}`.
    - All routes depend on JWT only (deny `principal.api_key is not None`) per Req 8 AC5.
    - Validate `scopes` against the fixed enum from design §Component 2; allow `admin:*` / `audit:read` only when caller `is_admin`.
    - On create / rotate, return plaintext exactly once and emit the matching audit verb.
    - List endpoint computes the `inactive` flag by comparing `last_used_at` (or `created_at`) against `API_KEY_INACTIVITY_THRESHOLD_DAYS`.
    - Hard delete only when `revoked_at IS NOT NULL` and audit retention is satisfied (gate with a single helper); otherwise 409.
    - _Requirements: 2.1, 2.4, 2.5, 2.8, 2.9_
  - [x] 4.2 Wire Pydantic schemas at `apps/api/core/app/schemas/api_key.py`
    - `ApiKeyCreateIn`, `ApiKeyCreateOut` (with `plaintext` field), `ApiKeyOut` (no plaintext, no hash), `ApiKeyRotateOut`.
    - Add OpenAPI examples on every schema (request and response) per Property 24.
    - _Requirements: 1.4, 2.3, 2.8_
  - [ ]* 4.3 Property test P1: Plaintext exposure exactly-once (API key portion)
    - **Property 1: Plaintext credential exposure is exactly-once**
    - Strategy creates and rotates random keys, scans every other API response body and every column read of `api_keys` and every `audit_logs.details`; asserts the plaintext appears nowhere outside the original create and rotate response bodies.
    - `@settings(max_examples=100)`.
    - **Validates: Requirements 2.1, 2.3, 2.8**
  - [ ]* 4.4 Property test P2: Rotation invalidates the previous secret (API key portion)
    - **Property 2: Rotation invalidates the previous secret**
    - Strategy generates rotation sequences; assert post-rotation requests with the previous plaintext yield 401 and with the new plaintext authenticate.
    - `@settings(max_examples=100)`.
    - **Validates: Requirements 2.4**
  - [ ]* 4.5 Property test P4 (key portion): revoke ceases activity
    - **Property 4: Revoke and delete cease subsequent activity (API key clause)**
    - Strategy revokes random subsets of created keys; assert all subsequent requests yield 401.
    - `@settings(max_examples=100)`.
    - **Validates: Requirements 2.5**
  - [ ]* 4.6 Property test P6: Inactive flag predicate
    - **Property 6: Inactive flag predicate**
    - Strategy generates `(last_used_at, created_at, threshold)` triples (some `last_used_at == None`); assert the list endpoint's `inactive` flag equals `(now - coalesce(last_used_at, created_at)) >= threshold`.
    - `@settings(max_examples=100)`.
    - **Validates: Requirements 2.9**
  - [ ]* 4.7 Property test P19 (api_key portion): audit emission for terminal transitions
    - **Property 19: Audit emission for terminal transitions (api_key verbs)**
    - Strategy creates / rotates / revokes / admin-revokes random keys; assert exactly one audit row per transition with the matching verb, actor, resource_type=`api_key`, resource_id=key id.
    - `@settings(max_examples=100)`.
    - **Validates: Requirements 7.1, 9.4**

- [x] 5. Checkpoint: API key path complete end-to-end
  - Ensure all tests pass, ask the user if questions arise.

- [x] 6. Migration 0009 + webhook models
  - [x] 6.1 Write Alembic revision 0009 `add_webhook_subscriptions_and_deliveries.py`
    - `down_revision = "0008"`. Creates `webhook_subscriptions` and `webhook_deliveries` per design §Data Models 0009 with all indices.
    - Provide a working `downgrade()` dropping both tables.
    - _Requirements: 3.1, 3.6, 3.7, 4.1, 4.9_
  - [x] 6.2 Add SQLAlchemy models at `apps/api/core/app/models/webhook_subscription.py` and `apps/api/core/app/models/webhook_delivery.py`
    - Mirror migration 0009 columns; cross-relationships; Google-style docstrings.
    - _Requirements: 3.1, 4.1_

- [x] 7. Component 3 + Component 4: Webhook subscription routes and HMAC signer
  - [x] 7.1 Implement HMAC signer module at `apps/api/core/app/core/webhook_signing.py`
    - Pure functions: `canonical_body_bytes(payload: dict) -> bytes` using `json.dumps(..., ensure_ascii=False, separators=(",", ":"))` then `.encode("utf-8")`; `sign(secret: str, body_bytes: bytes) -> str` returning `sha256=<hex>`; `build_delivery_headers(event_type, delivery_id, signature_header) -> dict`.
    - No I/O, no dependency on settings — pure for unit and property tests.
    - _Requirements: 4.2, 4.3_
  - [x] 7.2 Implement subscription routes at `apps/api/core/app/api/v1/webhooks.py`
    - `POST /`, `GET /`, `PATCH /{sub_id}`, `POST /{sub_id}/rotate-secret`, `DELETE /{sub_id}`, `GET /{sub_id}/deliveries`, `POST /{sub_id}/deliveries/{delivery_id}/redeliver`.
    - Validate target URL is HTTPS scheme (400 + `webhook_url_must_be_https`).
    - Validate every event type is in the supported set (400 + `webhook_event_unsupported`).
    - Return signing secret plaintext exactly once on create / rotate; persist hash plus `previous_secret_hash` during the rotation invalidation window.
    - Delete stops new dispatches but retains delivery history.
    - Manual redelivery preserves `payload` byte-for-byte and creates a new delivery row.
    - Pydantic schemas at `apps/api/core/app/schemas/webhook.py` with OpenAPI examples on every shape.
    - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7, 4.10_
  - [x] 7.3 Implement domain event emitter `emit_webhook_event` at `apps/api/core/app/services/webhook_emitter.py`
    - Query active subscriptions matching `(event_type, owner has viewer permission on survey_id)`.
    - Insert one `WebhookDelivery` per match in status `pending` inside the caller's DB transaction; enqueue Celery `deliver_webhook(delivery_id)` after commit.
    - Wire emitter into the existing handlers per design §Component 3: `app/api/v1/responses.py` (response.created, response.completed), `app/services/sample_service.py` (quota.reached), `app/api/v1/distribution.py` (distribution.sent).
    - _Requirements: 4.1_
  - [ ]* 7.4 Property test P1 (webhook portion): plaintext exposure exactly-once for signing secret
    - **Property 1: Plaintext credential exposure is exactly-once (webhook clause)**
    - `@settings(max_examples=100)`.
    - **Validates: Requirements 3.1, 3.4**
  - [ ]* 7.5 Property test P9: Webhook request construction
    - **Property 9: Webhook request construction**
    - Hypothesis strategy generates random payload dicts, secrets, event types, delivery IDs; assert the request constructed by the signer plus header builder carries all five required headers and the signature equals the stdlib reference.
    - `@settings(max_examples=100)`.
    - **Validates: Requirements 4.2, 4.3**
  - [ ]* 7.6 Property test P11: Manual redelivery preserves payload bytes
    - **Property 11: Manual redelivery preserves payload bytes**
    - `@settings(max_examples=100)`.
    - **Validates: Requirements 4.10**
  - [ ]* 7.7 Property test P19 (webhook subscription portion)
    - **Property 19: Audit emission for terminal transitions (webhook subscription verbs)**
    - `@settings(max_examples=100)`.
    - **Validates: Requirements 7.2**

- [x] 8. Component 5: Webhook delivery worker
  - [x] 8.1 Implement `apps/api/core/app/tasks/webhook_tasks.py`
    - Single Celery task `deliver_webhook(delivery_id: str)` on queue `webhooks`.
    - Loads the delivery and subscription, computes the signature via `webhook_signing.sign`, performs `httpx.AsyncClient(timeout=10).post(...)`, classifies the outcome.
    - Retry schedule `[60, 300, 1800, 7200, 43200]` driven by row's `attempt_count`, not by Celery `self.request.retries`. On enqueue failure, mark `failed_permanent` immediately.
    - Emit `webhook.delivery.succeeded` or `webhook.delivery.failed` audit row on terminal states.
    - Add a Celery beat reconciler that scans `pending` deliveries older than 60 seconds and re-enqueues them.
    - During the rotation dual-window the worker signs only with the new secret; receiver-side dual acceptance is a property of the verifier, not the platform.
    - _Requirements: 4.4, 4.5, 4.6, 4.7, 4.8, 3.5_
  - [x] 8.2 Add a previous-secret invalidation Celery task
    - At-least-once retry; clears `previous_secret_hash` once invalidation completes.
    - _Requirements: 3.5_
  - [ ]* 8.3 Property test P3: Webhook signature dual-window during invalidation failure
    - **Property 3: Webhook signature dual-window during invalidation failure**
    - Strategy simulates rotation followed by invalidation failures of varying counts; assert receiver-simulator verifies both secrets while `previous_secret_hash` is non-null and only the new one once it is null.
    - `@settings(max_examples=100)`.
    - **Validates: Requirements 3.5**
  - [ ]* 8.4 Property test P4 (webhook portion): delete ceases dispatch
    - **Property 4: Revoke and delete cease subsequent activity (webhook clause)**
    - Strategy deletes random subsets of subscriptions, then emits matching events; assert zero new `WebhookDelivery` rows for deleted subs.
    - `@settings(max_examples=100)`.
    - **Validates: Requirements 3.6**
  - [ ]* 8.5 Property test P8: Webhook routing fan-out
    - **Property 8: Webhook routing fan-out**
    - Strategy generates random subscription sets and an emitted event; assert the count of newly created delivery rows equals the count of subscriptions matching `(active, event_types contains e, owner has viewer)`.
    - `@settings(max_examples=100)`.
    - **Validates: Requirements 4.1**
  - [ ]* 8.6 Property test P10: Webhook delivery state machine
    - **Property 10: Webhook delivery state machine**
    - Strategy generates random sequences over `{success_2xx, network_error, timeout, http_4xx, http_5xx, enqueue_failure}`; mock `httpx.post` and the Celery enqueue path; assert final status, `attempt_count`, `next_attempt_at`, and audit emission match the reference state machine on each sequence.
    - Use `CELERY_TASK_ALWAYS_EAGER=True` and `fakeredis` to keep iterations cheap.
    - `@settings(max_examples=100)`.
    - **Validates: Requirements 4.4, 4.5, 4.6, 4.7, 4.8**
  - [ ]* 8.7 Property test P19 (webhook delivery portion)
    - **Property 19: Audit emission for terminal transitions (webhook delivery verbs)**
    - `@settings(max_examples=100)`.
    - **Validates: Requirements 7.3**

- [x] 9. Checkpoint: Webhook delivery path complete end-to-end
  - Ensure all tests pass, ask the user if questions arise.

- [x] 10. Migration 0010 + export job model
  - [x] 10.1 Write Alembic revision 0010 `add_export_jobs.py`
    - `down_revision = "0009"`. Creates `export_jobs` per design §Data Models 0010 with all indices including `(expires_at) WHERE status='succeeded'`.
    - Provide a working `downgrade()`.
    - _Requirements: 5.1, 5.4, 5.12_
  - [x] 10.2 Add SQLAlchemy `ExportJob` model at `apps/api/core/app/models/export_job.py`
    - Google-style docstring; type hints on relationship accessors.
    - _Requirements: 5.1_

- [x] 11. Component 6 + Component 7 + Component 8: Export service, worker, signed download
  - [x] 11.1 Implement format detection and producer modules at `apps/api/core/app/services/export_formats/`
    - Module per format: `csv_producer.py`, `xlsx_producer.py`, `json_producer.py`, `sav_producer.py`, `sas_producer.py`.
    - Top-level `SUPPORTED_FORMATS: FrozenSet[str]` initialized to `{"csv", "xlsx", "json"}` and conditionally extended when `pyreadstat` imports cleanly.
    - Each producer takes `(survey, responses, output_path)` and writes deterministic output per design §Component 7 (UTF-8 BOM for CSV, single-sheet XLSX with header, JSON array of objects, `pyreadstat` variable and value labels for SAV/SAS).
    - Question canonical order computed once per job from `survey.json_content`.
    - _Requirements: 5.5, 5.6, 5.7, 5.8_
  - [x] 11.2 Implement export routes at `apps/api/core/app/api/v1/exports.py`
    - `POST /` creates a job (400 + `export_format_unsupported` for non-member formats).
    - `GET /{job_id}` returns status; includes `download_url` only when `status == succeeded`.
    - `GET /{job_id}/download?token=<jwt>` validates the signed token (`purpose=="export_download"`, `jti==job_id`, `exp` in future) and serves via `FileResponse`. Also accepts JWT or `export:read` API key auth (no token) for programmatic download per Req 5 AC11.
    - `GET /` lists caller's jobs, paginated.
    - Pydantic schemas at `apps/api/core/app/schemas/export.py` with OpenAPI examples on every shape.
    - _Requirements: 5.1, 5.2, 5.3, 5.10, 5.11_
  - [x] 11.3 Implement signed download token helpers at `apps/api/core/app/core/export_download_token.py`
    - `issue(user_id, job_id, ttl) -> str`, `verify(token, job_id) -> bool` (HS256 with the existing `JWT_SECRET`, `purpose="export_download"` namespacing).
    - Pure functions; no DB.
    - _Requirements: 5.10_
  - [x] 11.4 Implement export worker at `apps/api/core/app/tasks/export_tasks.py`
    - Single Celery task `materialize_export(job_id: str)` on queue `exports`.
    - Transitions: `queued → running → {succeeded, failed}`. Streams responses in id order, writes to a temp file, atomically renames on success, unlinks the temp file on exception (no partial output retained).
    - Records `storage_path` and `byte_size` on success; truncates `error_message` to 1000 chars on failure.
    - Emits `export.job.succeeded` or `export.job.failed` audit row on terminal states.
    - _Requirements: 5.4, 5.9, 5.10_
  - [x] 11.5 Implement retention sweeper Celery beat job
    - Runs hourly; finds jobs with `status='succeeded' AND completed_at < now - retention_window`, deletes the on-disk file, updates row to `expired`, emits `export.job.expired` audit row.
    - _Requirements: 5.12_
  - [ ]* 11.6 Property test P12: Export format admission
    - **Property 12: Export format admission**
    - Hypothesis strategy generates random format strings; assert membership in the runtime supported set is exactly equivalent to the create endpoint's accept / reject decision (with `export_format_unsupported` on reject).
    - `@settings(max_examples=100)`.
    - **Validates: Requirements 5.1, 5.2, 5.3**
  - [ ]* 11.7 Property test P13: Export job lifecycle convergence
    - **Property 13: Export job lifecycle convergence**
    - Strategy generates random sequences of worker outcomes plus retention sweeps; assert monotone status lattice, `started_at <= completed_at`, file existence matches `status`, no partial files survive `failed`.
    - `@settings(max_examples=100)`.
    - **Validates: Requirements 5.4, 5.9, 5.12**
  - [ ]* 11.8 Property test P14: Export format structural invariants (CSV / XLSX / JSON)
    - **Property 14: Export format structural invariants (textual formats)**
    - Strategy generates small random surveys (SurveyJS-shaped schemas) and response lists keyed against them; assert the CSV BOM and header order, XLSX single sheet and dimensions, JSON list-of-objects with subset keys.
    - `@settings(max_examples=100)`.
    - **Validates: Requirements 5.5, 5.6, 5.7**
  - [ ]* 11.9 Property test P14: Export format structural invariants (SAV / SAS7BDAT)
    - **Property 14: Export format structural invariants (binary formats)**
    - Strategy as in P14 textual; round-trip via `pyreadstat`; assert variable label and value label maps. `pyreadstat` write-and-read is slow, so use `@settings(max_examples=20)` per design §Testing Strategy.
    - Skip when `pyreadstat` is not importable.
    - **Validates: Requirements 5.8**
  - [ ]* 11.10 Property test P15: Export download authorization
    - **Property 15: Export download authorization**
    - Strategy generates random `(job_status, caller, token validity)` tuples; assert the response code matches the design predicate (200 only when status=succeeded AND one of the three accepted auth paths holds).
    - `@settings(max_examples=100)`.
    - **Validates: Requirements 5.10, 5.11**
  - [ ]* 11.11 Property test P19 (export portion)
    - **Property 19: Audit emission for terminal transitions (export verbs)**
    - `@settings(max_examples=100)`.
    - **Validates: Requirements 7.4**

- [x] 12. Checkpoint: Export path complete end-to-end
  - Ensure all tests pass, ask the user if questions arise.

- [x] 13. Component 9: Per-API-key rate limiter middleware
  - [x] 13.1 Implement Lua-script-based limiter at `apps/api/core/app/middleware/rate_limit.py`
    - Replace the existing in-memory limiter. Three fixed-window counters per request keyed by `(api_key_id, window_label, window_start_epoch)` with TTLs 70 s / 4000 s / 90000 s.
    - Single Lua script per request: `INCR` each window key and `EXPIRE` only when the new value is `1`; return all three counts in one round trip.
    - Add `X-RateLimit-Limit`, `X-RateLimit-Remaining`, `X-RateLimit-Reset` to every successful response; add `Retry-After` to every 429.
    - Quota lookup: read `ApiKey.rate_limit_overrides` once during auth resolution to avoid an extra Redis round trip.
    - JWT-authenticated requests bypass the per-key counter path.
    - On `redis.ConnectionError` / timeout (`socket_timeout=1.0`), return 503 + `rate_limiter.backend_unavailable` and emit the matching audit row.
    - _Requirements: 6.1, 6.2, 6.3, 6.4, 6.5, 6.6, 6.7_
  - [ ]* 13.2 Property test P16: Rate-limit decision predicate
    - **Property 16: Rate-limit decision predicate**
    - Strategy generates `(Lm, Lh, Ld)` quotas and post-increment `(Cm, Ch, Cd)` counts; assert allow / deny equals `Cm > Lm OR Ch > Lh OR Cd > Ld`, that the headers on allow match the spec, and that `Retry-After` on deny equals `min(reset(w) - now)` over the exceeded windows.
    - Use `fakeredis` for speed. `@settings(max_examples=100)`.
    - **Validates: Requirements 6.1, 6.2, 6.3, 6.4**
  - [ ]* 13.3 Property test P17: Effective quota composition
    - **Property 17: Effective quota composition**
    - `@settings(max_examples=100)`.
    - **Validates: Requirements 6.5, 6.6**
  - [ ]* 13.4 Property test P18: Rate-limit fail-closed on Redis outage
    - **Property 18: Rate-limit fail-closed on Redis outage**
    - Strategy simulates `redis.ConnectionError` / timeout at random points during the limiter call; assert HTTP 503 with the spec body, the route handler is not invoked, and exactly one `rate_limiter.backend_unavailable` audit row is appended.
    - `@settings(max_examples=100)`.
    - **Validates: Requirements 6.7**
  - [ ]* 13.5 Property test P19 (rate-limit portion)
    - **Property 19: Audit emission for terminal transitions (rate-limit verbs)**
    - `@settings(max_examples=100)`.
    - **Validates: Requirements 7.5**

- [x] 14. Migration 0011 (composite indices) and audit query support
  - [x] 14.1 Write Alembic revision 0011 `add_api_platform_indices.py`
    - `down_revision = "0010"`. Adds `(audit_logs.action, audit_logs.created_at DESC)` and `(webhook_deliveries.subscription_id, webhook_deliveries.status)` composite indices.
    - Provide a working `downgrade()`.
    - _Requirements: 7.7, 4.9_
  - [x] 14.2 Implement audit query helper at `apps/api/core/app/services/audit_query.py`
    - Filter by any combination of `actor_user_id`, `resource_id` (api_key or subscription), time range, action verb; ordered by `created_at DESC`.
    - Used by the admin audit-logs endpoint.
    - _Requirements: 7.7_
  - [ ]* 14.3 Property test P20: Audit log query equivalence
    - **Property 20: Audit log query equivalence**
    - Strategy generates random audit row sets and random filter combinations; assert endpoint output equals in-memory filter modulo pagination and ordering.
    - `@settings(max_examples=100)`.
    - **Validates: Requirements 7.7**
  - [ ]* 14.4 Property test P21: Audit row schema conformance
    - **Property 21: Audit row schema conformance**
    - Strategy generates arbitrary `details` dicts including reserved-column collisions; assert persisted row has only allowed columns and that conflicting keys are dropped silently.
    - `@settings(max_examples=100)`.
    - **Validates: Requirements 7.8, 7.9**

- [x] 15. Component 11: Admin endpoints
  - [x] 15.1 Implement `apps/api/core/app/api/v1/admin.py`
    - Routes: `GET /api-keys`, `POST /api-keys/{key_id}/revoke`, `GET /webhooks`, `GET /exports`, `GET /audit-logs`.
    - Each route wires `Depends(get_principal)` plus `require_scope("admin:read" | "admin:write" | "audit:read")`.
    - The admin revoke path emits `api_key.admin_revoke` (note the distinct verb) with the administrator identity in `details`.
    - The api-keys inventory carries a 30-day request count derived from summing Redis day-window counters at query time; report `null` when keys have already expired.
    - The webhooks inventory carries a 30-day failure count derived from `webhook_deliveries`.
    - Pydantic schemas at `apps/api/core/app/schemas/admin.py` with OpenAPI examples on every shape.
    - _Requirements: 9.1, 9.2, 9.3, 9.4_
  - [ ]* 15.2 Property test P22: Admin inventory completeness
    - **Property 22: Admin inventory completeness**
    - Strategy generates random states of the three tables; assert each endpoint returns exactly the spec-filtered rows including the empty-list case.
    - `@settings(max_examples=100)`.
    - **Validates: Requirements 9.1, 9.2, 9.3**

- [x] 16. Component 12: API documentation
  - [x] 16.1 Configure FastAPI app for documentation routes
    - In `apps/api/core/app/main.py`, set `openapi_url="/api/v1/openapi.json"`, `docs_url="/api/v1/docs"`, `redoc_url="/api/v1/redoc"` on the `FastAPI(...)` constructor.
    - Inject `BearerAuth` (HTTP bearer / JWT) and `ApiKeyAuth` (apiKey in header `X-API-Key`) into `app.openapi_schema` after schema generation; annotate every route depending on `get_principal` so OpenAPI lists both as accepted.
    - Set `include_in_schema=False` on `app/api/v1/health.py` and any internal-only debug routers.
    - _Requirements: 1.1, 1.2, 1.3, 1.5, 1.7_
  - [x] 16.2 Backfill summaries, descriptions, and examples on existing public routers
    - One-time pass: fill in `summary=`, `description=`, and at least one example response (and request body where applicable) on every existing public router so Property 24 holds across the whole app.
    - All new routers in this feature must already comply by construction.
    - _Requirements: 1.4_
  - [x] 16.3 Add the integration usage guide
    - Create `apps/api/core/app/static/integration-guide.md` with four worked examples (auth, list surveys, register a webhook, start an export) in cURL plus one of {Python (`httpx`), JavaScript (`fetch`)}.
    - Link from the FastAPI `description=` so it is reachable from the Swagger UI page.
    - _Requirements: 1.6_
  - [ ]* 16.4 Property test P24: Universal documentation annotation
    - **Property 24: Universal documentation annotation**
    - Iterate over all routes with `include_in_schema == True`; assert non-empty `summary`, non-empty `description`, at least one example response, and at least one example request body where applicable.
    - `@settings(max_examples=100)` (the strategy is over the route set; one Hypothesis assertion per route is sufficient).
    - **Validates: Requirements 1.4**
  - [ ]* 16.5 Property test P25: Universal internal-route exclusion
    - **Property 25: Universal internal-route exclusion**
    - For every route with `include_in_schema == False`, assert the path is absent from the generated OpenAPI document.
    - `@settings(max_examples=100)`.
    - **Validates: Requirements 1.7**

- [x] 17. Compliance integration verification
  - [x] 17.1 Wire the new audit verbs into the existing T10 compliance export query
    - Confirm the existing T10 compliance export at the existing module location selects rows by time range only (no verb whitelist); add a smoke check if any whitelist exists, and update it to include the new verbs.
    - _Requirements: 9.5_
  - [ ]* 17.2 Property test P23: Compliance export inclusion
    - **Property 23: Compliance export inclusion**
    - Strategy generates random `(time range, audit row sets)` pairs whose verbs span the new set; assert all in-range rows appear in the compliance export output.
    - `@settings(max_examples=100)`.
    - **Validates: Requirements 9.5**

- [ ] 18. Integration tests against local Docker Postgres + Redis
  - [ ]* 18.1 Migration chain integration test
    - Boot a clean test database, run `alembic upgrade head`, assert the chain `0007 → 0008 → 0009 → 0010 → 0011` applies cleanly and downgrades cleanly.
    - _Requirements: 2.1, 3.1, 5.1, 7.7_
  - [ ]* 18.2 Documentation route integration test
    - Boot the FastAPI test client; assert `GET /api/v1/openapi.json` returns valid OpenAPI 3.x JSON, `GET /api/v1/docs` returns Swagger HTML, `GET /api/v1/redoc` returns ReDoc HTML, and the integration guide is reachable from the Swagger page.
    - _Requirements: 1.1, 1.2, 1.3, 1.5, 1.6_
  - [ ]* 18.3 Dual-auth wiring integration test
    - Hit one survey-scoped GET with JWT only, with API key only, with both, and with neither; assert the resolved principal and HTTP status match the design table.
    - _Requirements: 8.1, 8.2, 8.3_
  - [ ]* 18.4 Celery worker boot integration test
    - Boot the `webhooks` and `exports` workers; enqueue one trivial task per queue; assert each is consumed and acknowledged.
    - _Requirements: 4.1, 5.4_
  - [ ]* 18.5 Audit schema conformance integration test
    - Append one audit row per new verb against the live `audit_logs` table; assert no migration error and that all 16 verbs round-trip cleanly.
    - _Requirements: 7.8_
  - [ ]* 18.6 `pyreadstat` import smoke test
    - In the export worker's environment, assert `pyreadstat` imports cleanly and `SUPPORTED_FORMATS` includes `sav` and `sas7bdat`.
    - _Requirements: 5.2_

- [x] 19. Final checkpoint: Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Sub-tasks marked with `*` are optional and can be skipped for a faster MVP, but the property tests are the primary instrument that maps the implementation back to the design's correctness properties P1 through P25, so skipping them weakens the verification story significantly.
- Each property test sits next to the implementation it covers so a property failure surfaces immediately when the underlying code lands. Property 19 is split into per-component sub-tasks (4.7, 7.7, 8.7, 11.11, 13.5) so each parent task carries its own audit-emission guarantee rather than deferring it to a single late test.
- Migrations are sequenced strictly: 0008 lands before any code reads `api_keys`; 0009 lands before subscription routes; 0010 lands before the export worker; 0011 lands at the end because its composite indices accelerate query paths that only exist after admin endpoints are wired.
- Hypothesis settings: `max_examples=100` for every property except Property 14's SAV/SAS7BDAT roundtrip which uses `max_examples=20` because `pyreadstat` write-then-read is meaningfully slower than the textual formats.
- Frontend admin pane is out of scope per the user's instruction; the admin endpoints are implemented and tested but no React page is built. A future spec may add the UI consuming these endpoints.
- Commit messages follow conventional commits, e.g. `feat(api-keys): add Principal dependency and require_scope helper`, `feat(webhooks): implement HMAC signer and delivery worker`, `test(exports): property tests P12–P15`.

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1", "1.2", "1.3", "1.4"] },
    { "id": 1, "tasks": ["2.1", "2.3"] },
    { "id": 2, "tasks": ["2.2"] },
    { "id": 3, "tasks": ["3.1", "3.2"] },
    { "id": 4, "tasks": ["3.3", "3.4", "4.1", "4.2", "6.1"] },
    { "id": 5, "tasks": ["4.3", "4.4", "4.5", "4.6", "4.7", "6.2", "10.1"] },
    { "id": 6, "tasks": ["7.1", "7.2", "7.3", "10.2"] },
    { "id": 7, "tasks": ["7.4", "7.5", "7.6", "7.7", "8.1", "8.2", "11.1", "11.3"] },
    { "id": 8, "tasks": ["8.3", "8.4", "8.5", "8.6", "8.7", "11.2", "11.4", "11.5"] },
    { "id": 9, "tasks": ["11.6", "11.7", "11.8", "11.9", "11.10", "11.11", "13.1"] },
    { "id": 10, "tasks": ["13.2", "13.3", "13.4", "13.5", "14.1"] },
    { "id": 11, "tasks": ["14.2", "15.1", "16.1", "16.3", "17.1"] },
    { "id": 12, "tasks": ["14.3", "14.4", "15.2", "16.2", "16.4", "16.5", "17.2"] },
    { "id": 13, "tasks": ["18.1", "18.2", "18.3", "18.4", "18.5", "18.6"] }
  ]
}
```
