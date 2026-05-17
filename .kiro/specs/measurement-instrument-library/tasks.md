# Implementation Plan: Measurement Instrument Library (T-Measurement)

## Overview

This plan converts `design.md` into a sequence of code-generation tasks that
deliver T-Measurement as a new module inside the existing FastAPI monorepo at
`apps/api/core/` plus three React surfaces under
`apps/web/src/features/measurement/`. Tasks are grouped under 16 build-order
phases that mirror the design's component dependency chain: schema first, then
the cross-cutting Rights_Tier_Gate and audit-field plumbing, then the seven
pipeline components in DAG order (Ingestion → Item_Extractor →
Standardization → Pretty_Printer + Round-Trip → Concept_Tagger →
Review_Queue → Item_Store/Recommendation), then the AI Survey Designer
extension, then frontend surfaces, then Snapshot_Service / milestone
dashboard, then the researcher-contributor flow, then compliance and
observability, then test suites (26 Hypothesis property tests + 5 named
compliance tests + perf + e2e), then docs.

The platform's existing infrastructure is reused unchanged: T10 `audit_logs`
schema, `app/core/auth.py::get_principal` and `require_scope`, the AI router
in `app/core/ai_router.py` (extended only via a thin wrapper
`route_for_rights_tier`), the existing webhook emitter, Garage object
storage, Postgres 16, Redis 7, and Elasticsearch 9.x with the IK plugin.

## Tasks

- [ ] 1. Database migrations, ORM models, and core constants
  - [ ] 1.1 Implement `apps/api/core/app/core/measurement_versions.py`
    - Define `EXTRACTION_VERSION_CURRENT`, `NORM_VERSION_CURRENT`, `THRESHOLD_VERSION_CURRENT`, `CONCEPT_ONTOLOGY_REVISION_CURRENT` as `Final` constants seeded to `"v1.0.0"` / `"ontology_2027_06_01"`
    - Export a `MEASUREMENT_AUDIT_FIELDS` tuple naming the five mandatory audit fields for reuse by the audit-field guard
    - _Requirements: 9.5, 9.6, 9.13_

  - [ ] 1.2 Extend `apps/api/core/app/core/audit.py` and `apps/api/core/app/core/auth.py`
    - Add `MEASUREMENT_VERBS: FrozenSet[str]` containing every audit verb listed in design §"Audit_Log extension" (ingestion, OCR, extract, standardize, tag, roundtrip, review, snapshot, sync, rights-tier, audit-field-guard, milestone, contributor — 35+ verbs)
    - Register `measurement:read`, `measurement:contribute`, `measurement:review` in the canonical scope enum used by `require_scope`
    - _Requirements: 7.11, 7.12, 9.12_

  - [ ] 1.3 Extend `apps/api/core/app/config.py::Settings`
    - Add `local_only_providers: list[str]`, `local_only_provider_hosts: list[str]`, `rights_tier_registry: dict[str, RightsTier]`, `measurement_library_source_path: str` (default `/mnt/onedrive/measurement-corpus`), `ocr_engine_for_language: dict[str, str]`, `recommendation_cutoff_default: float` (default `0.60`), `measurement_es_index: str` (default `measurement_items_v1`)
    - _Requirements: 4.5, 4.10, 9.10, 9.11, 10.7, 10.8_

  - [ ] 1.4 Implement Alembic migration `apps/api/core/alembic/versions/0012_add_measurement_core.py`
    - Add `users.is_librarian BOOLEAN NOT NULL DEFAULT FALSE`
    - Create tables `source_questionnaires`, `raw_items`, `standardized_items`, `item_options` with every column, type, length, check constraint, and index named in design §"Data Models"
    - Create plpgsql triggers `measurement_propagate_rights_tier_raw` (BEFORE INSERT on `raw_items`), `measurement_propagate_rights_tier_std` (BEFORE INSERT on `standardized_items`), and `enforce_measurement_audit_fields` (BEFORE INSERT|UPDATE on all four tables) that raise `audit_field_missing: <field_name>` when any of the five mandatory audit fields is NULL or empty
    - Provide a clean `downgrade()` that drops triggers before tables
    - _Requirements: 9.4, 9.5, 9.6, 1.2, 2.2, 3.1, 3.2_

  - [ ] 1.5 Implement Alembic migration `apps/api/core/alembic/versions/0013_add_measurement_concept_ontology_and_tags.py`
    - Activate `pgvector` extension if not already enabled
    - Create `concept_ontology`, `concept_ontology_revisions`, `concept_tags`, `validated_scales`, `validated_scale_links`
    - Add `standardized_items.embedding VECTOR(1024)` column
    - Indexes per design (`(concept_id, confidence DESC)`, UNIQUE `(standardized_item_id, concept_id)`, etc.)
    - _Requirements: 4.1, 4.2, 4.3, 4.4, 4.6, 4.8_

  - [ ] 1.6 Implement Alembic migration `apps/api/core/alembic/versions/0014_add_measurement_review_history_snapshots.py`
    - Create tables `item_history`, `library_snapshots` (with regex CHECK on `snapshot_id`), `review_queue_entries` with all design columns and indexes
    - Create a per-day uniqueness index on `library_snapshots(date_trunc('day', created_at))` to support the 999/day limit guard
    - _Requirements: 6.3, 6.6, 9.13, 9.14_

  - [ ] 1.7 Implement Alembic migration `apps/api/core/alembic/versions/0015_add_measurement_indexes_and_es_sync_backlog.py`
    - Add composite indexes for review queue filters (`review_queue_entries(status, priority DESC, created_at)`, `(assigned_reviewer_id, status)`)
    - Add `standardized_items` GIN index on `stem_text` using `pg_trgm` and IVFFlat index on `embedding` (`vector_cosine_ops`, `lists=100`)
    - Add partial composite index on `audit_logs(action, created_at DESC)` filtered to measurement and rights_tier verbs
    - _Requirements: 6.7, 7.13, 7.14, 9.15_

  - [ ] 1.8 Implement SQLAlchemy ORM models under `apps/api/core/app/models/measurement/`
    - One module per design table: `source_questionnaire.py`, `raw_item.py`, `standardized_item.py`, `item_option.py`, `item_history.py`, `concept_ontology.py`, `concept_ontology_revision.py`, `concept_tag.py`, `validated_scale.py`, `validated_scale_link.py`, `library_snapshot.py`, `review_queue_entry.py`
    - Each model declares the five mandatory audit-field columns with `nullable=False`
    - Re-export from `apps/api/core/app/models/measurement/__init__.py`
    - _Requirements: 1.2, 2.2, 3.1, 3.2, 9.4, 9.5_

  - [ ] 1.9 Implement Pydantic v2 schemas under `apps/api/core/app/schemas/measurement/`
    - Modules per design layout: `ingestion.py`, `raw_item.py`, `standardized_item.py`, `review_queue.py`, `search.py`, `dashboard.py`, `contribute.py`
    - Include `IngestionMeta`, `ConfirmMetaPayload`, `ContribMeta`, `ItemEdits`, `SearchFilters`, `FindSimilarRequest`, `StandardizedItemView` (matching the TypeScript-style shape in design §"Standardized item CRUD"), `ReviewQueueFilters`, `ReviewQueueEntryView`, `LibrarySnapshotCreate`, `MilestoneEvalResponse`
    - _Requirements: 1.2, 3.1, 6.1, 7.6, 7.9_

- [ ] 2. Audit-field plumbing and Rights_Tier_Gate
  - [ ] 2.1 Implement `apps/api/core/app/services/measurement/audit_emitter.py`
    - `emit_measurement_audit(action, resource_type, resource_id, principal, details, rights_tier, ...)` delegating to `app.core.audit.log_audit`, always populating `details.{data_snapshot_id, extraction_version, norm_version, threshold_version, trace_id, rights_tier}`
    - `write_with_audit_field_guard(db, sql_callable)` that catches the `enforce_measurement_audit_fields` SQL exception, emits `audit_field.missing` with the offending field, then re-raises HTTP 500 `audit_field_missing`
    - Forbid raw `log_audit(...)` from measurement code via a module-level convention assertion (CI-checked)
    - _Requirements: 9.5, 9.6, 9.12_

  - [ ] 2.2 Implement `apps/api/core/app/services/measurement/rights_tier_gate.py`
    - `RightsTierGate.classify_intake(librarian, registry)` implementing the design's decision rule (R3 fail-closed; max-restrictive on conflict)
    - `RightsTierGate.egress_redact(payload, source_tier, caller_entitlement, channel)` implementing the redact-or-block matrix from design §"Enforcement point 3"
    - `RightsTierGate.select_ai_lane(source_tier, task, has_chinese)` returning `RouteDecision` with `ModelTarget.LOCAL_QWEN` for R2/R3
    - `EgressChannel` enum and `_restrictiveness_rank` helper
    - _Requirements: 9.1, 9.2, 9.3, 9.7, 9.8, 9.9, 9.10_
    - _Properties: 20, 21_

  - [ ] 2.3 Implement `apps/api/core/app/middleware/rights_tier_egress.py`
    - FastAPI response middleware that walks `__measurement_payload__: True` responses, looks up source `rights_tier` per item, applies `egress_redact`, sets `redaction_applied=True` on view objects, emits `rights_tier.r2_text_redacted` / `rights_tier.r3_outbound_blocked` audit events
    - Reads `request.state.egress_channel` (set by routers) to pick the right matrix row
    - Register the middleware in `apps/api/core/app/main.py` immediately after the auth middleware
    - _Requirements: 9.7, 9.9, 8.5, 8.6_
    - _Properties: 21_

  - [ ] 2.4 Implement Celery `MeasurementTask` base class in `apps/api/core/app/tasks/measurement_tasks.py`
    - Reads `X-Trace-Id`, `X-Snapshot-Id`, `X-Extraction-Version`, `X-Norm-Version`, `X-Threshold-Version` from `request.headers`
    - Binds them into a `task_context: ContextVar[MeasurementTaskContext]` accessed by all measurement services
    - Implements an httpx event hook used by R2/R3 tasks that rejects outbound HTTP calls whose host is not in `Settings.local_only_provider_hosts` and whose body contains a length≥8 verbatim span from any task-context R2/R3 item
    - _Requirements: 9.5, 9.6, 9.10_

  - [ ] 2.5 Implement `Rights_Tier_Gate` Celery pre-task hook
    - Wire `select_ai_lane` into the AI-using tasks so any non-`local_only` lane decision for R2/R3 raises `RightsTierEgressBlocked` before transmission and emits `rights_tier.r3_egress_blocked`
    - Implement `awaiting_local_provider` status transition path used by Concept_Tagger when no `local_only` provider is reachable, and a beat job `retry_awaiting_local_provider` that polls health and re-enqueues
    - _Requirements: 9.8, 9.10, 9.11_
    - _Properties: 12, 21_

- [ ] 3. Ingestion_Service and OCR
  - [ ] 3.1 Implement `apps/api/core/app/services/measurement/ingestion_service.py::IngestionService.accept_batch`
    - Multipart parse, per-file SHA-256, format and size validation (1..50 files, ≤200 MB each), Garage upload keyed by hash, dedup against non-`deleted` rows, batch-level rollback on any rejection
    - Emits `questionnaire_already_ingested` (409), `questionnaire_format_unsupported` (415), `questionnaire_payload_oversize` (413) per design error catalog
    - Calls `RightsTierGate.classify_intake` before commit
    - _Requirements: 1.1, 1.3, 1.4, 1.10, 9.1, 9.2, 9.3_
    - _Properties: 1, 2, 20_

  - [ ] 3.2 Implement metadata-confirmation flow on `IngestionService`
    - `confirm_metadata(sq_id, payload, principal)` and `clear_ocr_flag(sq_id, principal)` methods with status guards
    - Filename + first-three-pages candidate inference for missing metadata producing up to 3 ranked candidates per field
    - Celery beat job `expire_awaiting_metadata` running nightly that transitions `awaiting_metadata_confirmation` rows older than 14 calendar days to `metadata_expired` and emits `measurement.ingest.metadata_expired`
    - _Requirements: 1.7, 1.8, 1.9, 1.12_
    - _Properties: 4_

  - [ ] 3.3 Implement `apps/api/core/app/services/measurement/ocr_service.py`
    - Engine selection driven by `Settings.ocr_engine_for_language` (PaddleOCR for `zh`, Tesseract for `en`)
    - Records engine id, version, mean confidence, per-page histogram with 0.05 bin width, runtime ms, completion timestamp
    - 600 s wall-clock cap; on timeout or unrecoverable engine error transitions to `ocr_failed`, captures failure category and engine error string truncated to 1000 chars, retains the original file
    - Below 0.80 mean confidence transitions to `ocr_low_confidence`, surfaces histogram to Review_Queue, blocks downstream extraction until cleared
    - _Requirements: 1.5, 1.6, 1.7, 1.11_
    - _Properties: 3_

  - [ ] 3.4 Implement Celery tasks `ingest_questionnaire` and `run_ocr` in `apps/api/core/app/tasks/measurement_tasks.py`
    - `ingest_questionnaire(sq_id, trace_id, snapshot_id)` routes into OCR when a PDF lacks ≥5% text-layer coverage, otherwise straight into `extract_items`
    - `run_ocr` consumes `OcrService.run` and writes outputs to Garage alongside the original
    - Retry budgets per design table (3/30s/2m/10m for ingest; 1 attempt for OCR)
    - _Requirements: 1.5, 1.6, 1.11_
    - _Properties: 3_

  - [ ] 3.5 Implement `apps/api/core/app/api/v1/measurement/ingest.py` router
    - `POST /api/v1/measurement/ingest`, `POST /api/v1/measurement/ingest/{sq_id}/confirm-metadata`, `POST /api/v1/measurement/ingest/{sq_id}/clear-ocr-flag` per design endpoint catalog
    - Sets `request.state.egress_channel = EgressChannel.SEARCH_RESPONSE` only on responses that include redacted item content (most ingest responses do not)
    - Includes `details.trace_id` in every error envelope
    - Mount under the existing `/api/v1` aggregator
    - _Requirements: 1.1, 1.3, 1.4, 1.7, 1.8, 1.10_
    - _Properties: 1, 4_

  - [ ] 3.6 Implement `apps/api/core/app/api/v1/measurement/questionnaires.py` router
    - `GET /api/v1/measurement/questionnaires` with filters and pagination, `GET /api/v1/measurement/questionnaires/{sq_id}` with rights-tier-driven nested-item redaction, `PATCH /api/v1/measurement/questionnaires/{sq_id}` (librarian), `DELETE /api/v1/measurement/questionnaires/{sq_id}` (soft-delete)
    - Reads also expose `GET /api/v1/measurement/raw-items/{raw_item_id}` (librarian-only, no redaction)
    - _Requirements: 1.2, 7.11, 7.12, 9.7, 9.9_

- [ ] 4. Item_Extractor
  - [ ] 4.1 Implement question-type classifier in `apps/api/core/app/services/measurement/item_extractor.py`
    - Regex anchors for `□ 1`, `( ) 1`, ordered lists, Likert scales `非常不同意…非常同意`, `Strongly disagree…Strongly agree`, ranking lists `1.__ 2.__`, matrix headers, branching keywords
    - Confidence aggregator producing a single `(question_type, confidence)` tuple plus up to five alternatives
    - Hooks into the AI fallback (task 4.4) when confidence < 0.80
    - _Requirements: 2.3, 2.7_
    - _Properties: 6_

  - [ ] 4.2 Implement `ItemExtractor.extract` and `extract_single_from_text`
    - Ordered Raw_Item emission keyed by ascending source character offset
    - Byte-for-byte preservation of stem and option labels (NFC unchanged, no whitespace normalization, no character-width folding)
    - Capture `source_page`, `(source_offset_start, source_offset_end)`, ordinal, matrix grouping id (identical across sub-questions of the same matrix)
    - Skip_Logic structured capture; verbatim retention of unresolved references with status `extraction_uncertain`
    - On catastrophic parse failure: emit failure record (category + halt offset), persist no partial rows, leave the source status at `ready_for_extraction`
    - On success: record `type_counts` for all eight question types (zero counts retained), `review_queue_count`, `duration_ms`
    - _Requirements: 2.1, 2.2, 2.4, 2.5, 2.6, 2.8, 2.9, 2.10_
    - _Properties: 5, 6, 7, 11_

  - [ ] 4.3 Implement AI fallback classification path
    - Routes through `route_for_rights_tier` (task 7.1) when regex confidence < 0.80
    - Stores up to five alternatives with confidences in `raw_items.question_type_alternatives`
    - Marks the row `extraction_uncertain` and enqueues review without aborting the rest of the job
    - _Requirements: 2.7_
    - _Properties: 11_

  - [ ] 4.4 Implement Celery task `extract_items(sq_id, trace_id, snapshot_id, extraction_version)`
    - 2-attempt retry budget (30 s, 2 min); idempotency key `(sq_id, extraction_version)`
    - Emits `measurement.extract.completed` on success, `measurement.extract.failed` on failure
    - Hands off to `standardize_items` on success
    - _Requirements: 2.1, 2.10_
    - _Properties: 5, 11_

- [ ] 5. Standardization_Service
  - [ ] 5.1 Implement `apps/api/core/app/services/measurement/standardization_service.py::standardize`
    - Canonical mapping for stem (≤2000 chars), option list (≤50), Likert anchors and points (2..11), scoring direction (`low_to_high`/`high_to_low`), language ISO 639-1
    - Status transitions: produce `standardized` on full mapping, `standardization_incomplete` with `unmapped_fields[]` on missing canonical fields, retain every successfully mapped field unchanged
    - _Requirements: 3.1, 3.3, 3.7_
    - _Properties: 9, 11_

  - [ ] 5.2 Implement option canonical-code preservation and version increment
    - For new instrument families set `version=1`; for approved edits set `version=max_approved+1`
    - Each option row carries both `(source_code, source_label)` and `(canonical_code, canonical_label)` even when equal
    - Canonical codes are stable across versions of the same `instrument_family_id`
    - _Requirements: 3.2, 3.4, 3.5_
    - _Properties: 9, 10_

  - [ ] 5.3 Implement Provenance_Record assembly
    - Persist `standardized_items.provenance` JSONB with source questionnaire id, source page, extraction job id, `extraction_version`, `norm_version`, `concept_ontology_revision`, `trace_id`, `data_snapshot_id`, contributor citation when applicable
    - Verify the five mandatory audit fields present and non-empty before commit (delegates to audit-field guard)
    - Equivalence helper `StandardizationService.equivalent(a, b)` re-using `canonical_equiv`
    - _Requirements: 3.6, 9.4, 9.5_
    - _Properties: 9, 20_

  - [ ] 5.4 Implement Celery task `standardize_items(extraction_job_id, trace_id, snapshot_id, norm_version)`
    - Drives `standardize` per Raw_Item, persists Standardized_Items, hands off to `tag_concepts` and `roundtrip_check`
    - On librarian rejection (Review_Queue path) sets status `rejected`, retains provenance and unmapped_fields unchanged
    - _Requirements: 3.7, 3.8, 3.9_
    - _Properties: 10, 11_

- [ ] 6. Pretty_Printer and Round-Trip checker
  - [ ] 6.1 Implement `apps/api/core/app/services/measurement/pretty_printer.py`
    - `_render_plain_text`, `_render_markdown`, `_render_html` backends (all consume the same canonical view object)
    - `PrettyFormat` enum, `PrettyPrinterValidationError` carrying the offending field/parameter name
    - Wire format spec is locked by string-snapshot tests under `tests/measurement/snapshots/`
    - HTML backend emits a fragment `<form><fieldset><label><input>` with no page chrome
    - Reject unknown formats and missing required fields without producing any rendering
    - _Requirements: 5.1, 5.2, 5.3_
    - _Properties: 13_

  - [ ] 6.2 Implement `apps/api/core/app/services/measurement/roundtrip.py::canonical_equiv`
    - Predicate plus helpers `_stem_equiv` (NFC + trim + collapse internal whitespace), `_options_equiv` (ordered, matching canonical_code/label), `_anchors_equiv` (both-absent treated equal), `_skip_logic_equiv` (ordered source-condition-target tuples)
    - Pure functions, no I/O, no DB access — suitable for direct unit and property tests
    - _Requirements: 5.4_
    - _Properties: 8_

  - [ ] 6.3 Implement `RoundTripChecker.check` and Celery task `roundtrip_check(item_id, trace_id, snapshot_id, norm_version)`
    - Renders each of `plain_text`, `markdown`, `html`; re-parses each through `Item_Extractor.extract_single_from_text` then `Standardization_Service.standardize` at the same `norm_version`
    - Hard 5 s per-item wall-clock budget enforced inside the task
    - On any format failure: persist `roundtrip_failures = [{fmt, diverging_fields, component, error_category}, ...]`, transition to `round_trip_failed`, leave every other field unchanged, enqueue Review_Queue
    - 2-attempt retry budget; idempotency key `(item_id, norm_version)`
    - _Requirements: 5.4, 5.5, 5.6, 5.7_
    - _Properties: 8, 11_

  - [ ] 6.4 Wire approval gate so `pending_review` is only reachable after round-trip passes
    - The Celery DAG transitions `standardized → roundtrip_checking → pending_review` on pass; `→ round_trip_failed` on any failure
    - The Review_Queue surfaces `round_trip_failed` rows alongside the diverging-fields summary
    - _Requirements: 5.5, 5.6, 6.1_
    - _Properties: 8_

- [ ] 7. Concept_Tagger
  - [ ] 7.1 Implement `route_for_rights_tier` wrapper in `apps/api/core/app/services/measurement/concept_tagger.py`
    - Forces `ModelTarget.LOCAL_QWEN` for R2/R3 source tier
    - Otherwise delegates to existing `app.core.ai_router.route_request`
    - Returns a `RouteDecision` carrying chosen `target`, `model_name`, `reasoning`
    - _Requirements: 4.5, 4.10, 9.10_
    - _Properties: 12, 21_

  - [ ] 7.2 Implement `ConceptTagger.tag` core flow
    - Build the structured prompt from design (system prompt + per-item user template)
    - Call AI router via `route_for_rights_tier`; parse JSON response against the schema defined in design §"AI Integration"
    - Validate every returned `slug` against the active `concept_ontology_revisions.concept_set`; discard unknown slugs and increment `tagging_error_warnings.unknown_tag_count`; never abort on unknown tags
    - Stamp `concept_ontology_revision` and `threshold_version` on the Standardized_Item at analysis time
    - Persist 1..5 valid `concept_tags` rows with `confidence` rounded to four decimals, `model_id`, `model_version`, `analyzed_at`
    - _Requirements: 4.1, 4.2, 4.6, 4.8_
    - _Properties: 12_

  - [ ] 7.3 Implement Validated_Scale matching
    - Compute item embedding via BAAI/bge-m3 for R0/R1 or local Qwen3 for R2/R3, cache to `standardized_items.embedding`
    - Take cosine top-10 candidates from `validated_scales` filtered by language and `expected_question_type`
    - Pass top-10 to LLM in the prompt's `validated_scale_summary` block; persist at most one `validated_scale_links` row when the per-scale `match_threshold` is met; otherwise leave the link empty and capture up to five runner-up scales sorted by descending score
    - _Requirements: 4.3, 4.4_
    - _Properties: 12_

  - [ ] 7.4 Implement Celery task `tag_concepts(item_id, trace_id, snapshot_id, ontology_revision, threshold_version)`
    - 3-attempt retry with exponential backoff (5 s, 30 s, 2 min)
    - On budget exhaustion: status `tagging_failed`, persist last error reason ≤1000 chars without overwriting prior successful tags, enqueue Review_Queue within 30 s
    - On no `local_only` provider for R2/R3: hold task at `awaiting_local_provider`, emit `rights_tier.no_local_provider`, refuse remote fallback
    - Routes through `measurement-ai` Celery queue
    - _Requirements: 4.7, 9.10, 9.11_
    - _Properties: 11, 12_

- [ ] 8. Review_Queue
  - [ ] 8.1 Implement `apps/api/core/app/services/measurement/review_queue_service.py`
    - `list(filters, principal, db)` with the seven filter dimensions (survey_program, wave, question_type, status, concept_tag, extraction_job_id, assigned_to_me) returning a paginated `ReviewQueuePage`
    - `approve(entry_id, edits, principal, db)`, `reject(entry_id, reason, principal, db)`, `merge(entry_id, winner_id, duplicate_id, principal, db)`, `claim`, `edit_without_approve`
    - Approve increments version by one when any field is edited; appends `item_history` rows with `change_kind` and prior values; emits `measurement.review.approve|reject|edit|merge`
    - Reject blocks empty/whitespace-only reasons with HTTP 400 `review_reason_required`
    - Merge atomically redirects every reference (skip_logic targets, recommendation_provenance source_item_id) from duplicate to winner inside one DB transaction; on any unresolvable reference aborts and returns 409 `merge_unresolved_references` listing them; both items keep pre-merge status
    - _Requirements: 6.2, 6.3, 6.4, 6.5, 6.6, 6.9_
    - _Properties: 10, 14_

  - [ ] 8.2 Implement Celery task `enqueue_review(item_id, trace_id, snapshot_id)`
    - Triggers from every upstream failure path: `extraction_uncertain`, `standardization_incomplete`, `tagging_failed`, `round_trip_failed`, `ocr_low_confidence`, `pending_librarian_review`
    - Inserts a `review_queue_entries` row with `reason`, default priority, status `open`
    - 3-attempt retry budget; idempotent on `(item_id, snapshot_id)`
    - _Requirements: 6.1_
    - _Properties: 14_

  - [ ] 8.3 Implement `apps/api/core/app/api/v1/measurement/review_queue.py` router
    - `GET /api/v1/measurement/review-queue` (list with filters), `GET /api/v1/measurement/review-queue/{entry_id}` (detail with source-page rendering URL and AI tags)
    - `POST /.../claim`, `POST /.../approve`, `POST /.../reject`, `POST /.../merge`, `POST /.../edit-without-approve`
    - `Idempotency-Key` header reuses the existing platform middleware
    - Filter response budget enforced by index design (target p95 ≤ 2 s for 10 000 entries)
    - _Requirements: 6.1, 6.7_
    - _Properties: 14, 15_

  - [ ] 8.4 Implement librarian item endpoints in `apps/api/core/app/api/v1/measurement/items.py`
    - `GET /api/v1/measurement/items/{item_id}` (rights-tier-redacted), `GET /api/v1/measurement/items/{item_id}/history`, `PATCH /api/v1/measurement/items/{item_id}` (new version on field change), `POST /api/v1/measurement/items/{item_id}/withdraw`
    - All mutations go through `write_with_audit_field_guard`
    - Excludes non-`approved` items from non-librarian responses
    - _Requirements: 6.3, 6.5, 6.8, 11.6_
    - _Properties: 10, 16_

- [ ] 9. Item_Store and Recommendation_Service
  - [ ] 9.1 Provision Elasticsearch index `measurement_items_v1`
    - Index template under `apps/api/core/app/services/measurement/es_template.json` with `zh_smart`/`zh_max`/`en_stem` analyzers and `embedding` dense_vector(1024) cosine similarity per design mapping
    - Idempotent template installer in `apps/api/core/app/services/measurement/search_service.py::ensure_index` invoked at app startup
    - _Requirements: 7.2_
    - _Properties: 16_

  - [ ] 9.2 Implement `apps/api/core/app/services/measurement/search_service.py`
    - Build ES query with multi-match across `stem_text_zh`/`stem_text_en` lanes, structured filters for `concept_tag`, `validated_scale_id`, `survey_program`, `wave`, `language`, `question_type`, `rights_tier`
    - 800 ms ES timeout, facet aggregation on the four facet keys, pagination with `total/page/page_size`
    - Excludes non-`approved` items by index-time invariant (only approved rows are upserted)
    - _Requirements: 7.6, 7.8, 7.13, 6.8_
    - _Properties: 16, 17_

  - [ ] 9.3 Implement `apps/api/core/app/services/measurement/recommendation_service.py::find_similar`
    - Item-id path: read `standardized_items.embedding`, run pgvector cosine top-k against approved items
    - Candidate-stem path: embed via BAAI/bge-m3 (R0/R1) or local Qwen3 (R2/R3 / unknown), then pgvector cosine top-k
    - Return up to `top_k` items ordered by descending similarity, deterministic ordering for identical inputs within the same `concept_ontology_revision`
    - Stamp `concept_ontology_revision` on the response payload
    - Validation: `top_k ∈ [1, 50]` (default 20), `candidate_stem` length ∈ [1, 2000], unknown item_id → 404
    - _Requirements: 7.9, 7.10, 7.14_
    - _Properties: 17_

  - [ ] 9.4 Implement Celery task `sync_to_elasticsearch(item_id, op, trace_id, snapshot_id)`
    - 3 attempts within 5 minutes per design retry budget
    - On exhaustion: append `(item_id, op)` to Redis list `measurement:es_sync_backlog`, emit `search_index.sync_failed`, surface backlog count to dashboard
    - Triggered after PG commit on item creation, edit-approval, and any transition into or out of `approved`
    - _Requirements: 7.3, 7.4, 7.5_
    - _Properties: 16, 18_

  - [ ] 9.5 Implement Celery beat task `retry_es_sync_backlog`
    - Hourly drain of `measurement:es_sync_backlog` with the same retry semantics
    - Emits `measurement.sync.upserted` / `measurement.sync.removed` per drained operation
    - Surfaces `measurement_es_sync_backlog` gauge metric
    - _Requirements: 7.5_
    - _Properties: 18_

  - [ ] 9.6 Implement search and find-similar routers
    - `apps/api/core/app/api/v1/measurement/search.py` exposing `POST /api/v1/measurement/search` and `POST /api/v1/measurement/find-similar`
    - Validation per design (q ≤ 1024 chars, page_size ∈ [1, 100], page ≥ 1, top_k ∈ [1, 50], candidate_stem ∈ [1, 2000]) returning 400 `search_invalid_parameter` / `find_similar_invalid_parameter` or 404 `find_similar_unknown_item` per error catalog
    - Sets `request.state.egress_channel = SEARCH_RESPONSE` or `FIND_SIMILAR_RESPONSE` so the egress middleware applies the correct redaction
    - Accepts both JWT and API_Key auth; requires `measurement:read`
    - _Requirements: 7.6, 7.7, 7.9, 7.10, 7.11, 7.12_
    - _Properties: 17_

- [ ] 10. AI Survey Designer integration
  - [ ] 10.1 Add a `Validated Items` tab to `apps/web/src/features/survey-designer/`
    - New components `ValidatedItemsTab.tsx`, `ConstructQueryInput.tsx`, `RecommendationCard.tsx`, `AcceptItemConfirmDialog.tsx`
    - New TanStack Query hook `useRecommendForConstruct(query)` calling `POST /api/v1/measurement/search` with `q=construct, page_size=10`
    - Renders up to 10 cards with confidence chip, citation block, and `Accept Item` button
    - _Requirements: 8.1, 8.5_
    - _Properties: 19_

  - [ ] 10.2 Implement accept-item flow
    - On click, copy stem, options, anchors, and Question_Type byte-for-byte verbatim into the draft survey
    - Attach a citation reference (originating Standardized_Item id, version, `accepted_at`) and set provenance marker `verbatim_from`
    - `useAcceptRecommendation(draftSurveyId, itemId)` hook handles the writeback to `useSurveyDesignerStore`
    - _Requirements: 8.2_
    - _Properties: 19_

  - [ ] 10.3 Implement provenance-marker transition
    - Extend `useSurveyDesignerStore` with `recommendationProvenance: Record<DraftItemId, {source_item_id, version, provenance, accepted_at}>`
    - On any subsequent edit of the copied stem/options/anchors/Question_Type, transition the marker from `verbatim_from` to `adapted_from` while preserving the citation reference
    - _Requirements: 8.3_
    - _Properties: 19_

  - [ ] 10.4 Implement `CitationsAppendixRenderer` and below-threshold notice
    - On survey export, append a Citations Appendix listing every item with `verbatim_from` or `adapted_from` provenance: originating item id, Survey_Program, Wave, source page; missing fields render the literal string `"unavailable"` rather than being omitted
    - When no recommendation result meets `Settings.recommendation_cutoff_default`, the panel displays the no-validated-items notice and disables auto-AI-drafted items unless the researcher activates the explicitly labelled `Draft AI item instead` control
    - _Requirements: 8.4, 8.7_
    - _Properties: 19_

- [ ] 11. Frontend librarian and researcher surfaces
  - [ ] 11.1 Wire routes and shared API hooks under `apps/web/src/features/measurement/`
    - Register routes in `apps/web/src/app/routes.tsx`: `/measurement/library`, `/measurement/library/upload`, `/measurement/library/questionnaires/:sq_id`, `/measurement/library/review`, `/measurement/library/review/:entry_id`, `/measurement/items/:item_id`, `/measurement/items/:item_id/lineage`
    - Add TanStack Query hooks under `apps/web/src/features/measurement/api/` (useIngestBatch, useConfirmMetadata, useClearOcrFlag, useQuestionnaireList, useQuestionnaireDetail, useReviewQueue, useReviewQueueEntry, useApproveReviewEntry, useRejectReviewEntry, useMergeReviewEntries, useClaimReviewEntry, useDashboard, useMilestoneEvaluate, useItemDetail, useItemHistory, useFindSimilar, useSearch)
    - _Requirements: 1.1, 6.1, 6.7, 7.6, 7.9, 7.13, 7.14, 10.5_

  - [ ] 11.2 Implement librarian upload console
    - `LibraryUploadPage.tsx`, `UploadDropzone.tsx` with batch limits (1..50 files, ≤200 MB) and per-file metadata fields
    - `OcrConfidencePanel.tsx` rendering the per-page histogram from `source_questionnaires.ocr_confidence_histogram`
    - `MetadataConfirmationDialog.tsx` surfacing up to three ranked candidates per field, gated on `awaiting_metadata_confirmation`
    - `useUploadBatchStore` (Zustand) for in-flight batch state
    - _Requirements: 1.1, 1.7, 1.9_
    - _Properties: 1, 4_

  - [ ] 11.3 Implement librarian dashboard page
    - `LibraryDashboardPage.tsx` with three `MilestoneCards` mapping `initial_coverage`, `initial_quality`, `initial_tagging` from `GET /api/v1/measurement/dashboard`
    - Per-program count widgets, ES sync backlog count, OCR low-confidence count, metadata-expired count, stale-data warning when `last_refresh_at` is older than 48 h
    - _Requirements: 10.2, 10.3, 10.4, 10.5, 10.6, 7.5_
    - _Properties: 24, 25_

  - [ ] 11.4 Implement Review_Queue list page
    - `ReviewQueuePage.tsx` with virtualized `ReviewQueueTable.tsx` and `ReviewQueueFilters.tsx` covering the seven filter dimensions
    - `useMeasurementLibrarianStore` (Zustand, `sessionStorage`-persisted) for filter state and last-claimed entry id
    - Infinite-scroll backed by paginated `useReviewQueue(filters)`; UI feedback within 3 s of queue load
    - _Requirements: 6.1, 6.7, 6.8_
    - _Properties: 14, 15_

  - [ ] 11.5 Implement Review_Queue detail page
    - `ReviewQueueDetailPage.tsx` with `ItemReviewSplitPane.tsx` (left: `SourcePagePreview.tsx` rendering the source page image; right: `StandardizedItemEditor.tsx` bound to `ItemEdits`)
    - Toolbar actions Approve / Edit-without-Approve / Reject (with required reason) / Merge / Claim wired to mutation hooks
    - `ConceptTagPills.tsx` displaying assigned tags with confidence chips; `LineageTimeline.tsx` summarizing ingest → extract → tag → roundtrip history
    - _Requirements: 6.1, 6.2, 6.3, 6.4, 6.5, 6.6, 6.9_
    - _Properties: 14_

  - [ ] 11.6 Implement researcher item-detail and lineage pages
    - `ItemDetailPage.tsx` rendering `StandardizedItemView` with redacted-vs-verbatim modes driven by `redaction_applied`
    - `CitationBlock.tsx` formatted BibTeX-friendly with Survey_Program + Wave + page + contributor citation
    - `SimilarItemsPanel.tsx` calling `useFindSimilar(itemId, topK=10)`
    - `ItemLineagePage.tsx` reusing `LineageTimeline` with researcher-facing role badges hiding librarian identity
    - _Requirements: 7.6, 7.9, 8.6, 11.7_
    - _Properties: 17, 21, 19_

- [ ] 12. Snapshot_Service and milestone dashboard
  - [ ] 12.1 Implement `apps/api/core/app/services/measurement/snapshot_service.py`
    - `begin_snapshot(label, principal, db)` issues `snapshot_YYYYMMDD_NNN` ids monotonically per UTC date in 001..999; rejects 1000th-of-day with HTTP 409 `snapshot_daily_limit_exceeded` and emits `snapshot.daily_limit_exceeded`
    - `attach_to_versions(snapshot_id, item_ids, db)` stamps the snapshot id on every Standardized_Item version derived from it before they become queryable
    - Emits `measurement.snapshot.created` with the five mandatory audit fields
    - _Requirements: 9.13, 9.14_
    - _Properties: 22_

  - [ ] 12.2 Implement Celery beat task `milestone_dashboard_refresh`
    - Hourly schedule under the platform's existing Celery beat configuration
    - Computes `initial_coverage`, `initial_quality`, `initial_tagging` predicates per design (named programs CGSS/CFPS/CHARLS/CLHLS/CHIP/CHFS/CHNS/CSS/CLDS/CLASS/CTUS/EASS/ISSP/GSS/WVS), 90 % approved threshold, 80 % tagged-with-confidence-≥0.60 threshold
    - Records `last_refresh_at`; emits `milestone.dashboard_refresh_stale` once per stale window when the previous successful refresh is older than 48 h
    - On unreachable source path classifies all three milestones as `evaluation_blocked` and emits `milestone.source_path_unreachable` without mutating any prior classification
    - _Requirements: 10.1, 10.2, 10.3, 10.4, 10.5, 10.6, 10.8_
    - _Properties: 24, 25_

  - [ ] 12.3 Implement Celery beat task `onedrive_corpus_walker(snapshot_id)`
    - Walks `Settings.measurement_library_source_path`, breadth-first per Survey_Program (named 15 + any extras per Req 10.7)
    - Uses SHA-256 dedup against non-`deleted` `source_questionnaires` rows (reuses Req 1.3 logic)
    - Looks up `rights_tier` per program from `Settings.rights_tier_registry`, falls through to R3 fail-closed for unknowns
    - Enqueues `ingest_questionnaire` for each new file
    - _Requirements: 10.7, 10.8, 9.3_

  - [ ] 12.4 Implement `apps/api/core/app/api/v1/measurement/dashboard.py` router
    - `GET /api/v1/measurement/dashboard`, `POST /api/v1/measurement/dashboard/refresh` (admin), `GET /api/v1/measurement/milestones`, `POST /api/v1/measurement/milestones/evaluate` (admin)
    - Response shape per design §"Librarian dashboard"
    - _Requirements: 10.5, 10.6, 10.8_

- [ ] 13. Researcher-contributor flow
  - [ ] 13.1 Implement `IngestionService.contributor_upload`
    - Caps file size at 25 MB; validates citation (1..1000 chars) and license declaration against the platform's supported license list
    - Auto-sets `rights_tier=R0` for open-redistribution licenses, `rights_tier=R1` for internal-use-only licenses
    - Persists `contributor_user_id`, `contributor_citation`, `contributor_license`; runs the same DAG as librarian uploads but routes resulting items to status `pending_librarian_review` and surfaces them to Review_Queue within 5 minutes
    - Returns 400 `contributor_payload_invalid` with `details.field` for every failure mode
    - _Requirements: 11.1, 11.2, 11.3, 11.5_
    - _Properties: 26_

  - [ ] 13.2 Implement `IngestionService.contributor_delete`
    - Deletes the source file from Garage within 24 h
    - Transitions every derived Standardized_Item to status `withdrawn_by_contributor`, excludes them from Recommendation_Service responses
    - Retains all `audit_logs` rows referencing those items unchanged
    - Preserves item references inside surveys that were already published before the deletion request without re-administering them
    - Notifies the contributor on librarian rejection within 1 h via the existing `apps/api/core/app/services/notification.py` helper
    - _Requirements: 11.4, 11.6_
    - _Properties: 26_

  - [ ] 13.3 Implement `apps/api/core/app/api/v1/measurement/contribute.py` router
    - `POST /api/v1/measurement/contribute` (multipart upload + citation + license), `DELETE /api/v1/measurement/contribute/{sq_id}` (owner-scoped)
    - 24-hour file removal scheduled as a Celery countdown task; status update is synchronous
    - Includes contributor citation in every downstream Standardized_Item API response
    - _Requirements: 11.1, 11.2, 11.5, 11.6, 11.7_
    - _Properties: 26, 19_

- [ ] 14. Compliance and observability
  - [ ] 14.1 Wire Prometheus metrics and structured logs
    - Counters and histograms named in design §"Observability" (`measurement_ingest_total`, `measurement_ocr_duration_seconds`, `measurement_extract_duration_seconds`, `measurement_extract_uncertain_total`, `measurement_standardize_incomplete_total`, `measurement_tag_attempts_total`, `measurement_roundtrip_failure_total`, `measurement_review_queue_depth`, `measurement_search_request_duration_seconds`, `measurement_es_sync_backlog`, `measurement_es_sync_lag_seconds`, `measurement_rights_tier_redaction_total`, `measurement_rights_tier_block_total`)
    - Structured-log enricher attaches `trace_id`, `data_snapshot_id`, `extraction_version`, `norm_version`, `threshold_version`, `rights_tier`, `actor_user_id` to every measurement log line via the existing log filter chain
    - _Requirements: 7.13, 7.14, 9.12_

  - [ ] 14.2 Implement audit log filter helpers and the partial composite index usage
    - Helper `apps/api/core/app/services/measurement/audit_query.py::query_measurement_audit_logs(filters, page, page_size)` filtering `audit_logs.action` against the measurement / rights_tier verb prefixes, returning rows within 3 s for result sets up to 10 000 entries
    - Validates that no measurement endpoint mutates or deletes existing `audit_logs` rows
    - _Requirements: 9.15_
    - _Properties: 23_

  - [ ] 14.3 Add operator runbooks under `apps/api/core/docs/runbooks/`
    - `measurement-es-sync-backlog.md` — diagnose persistent ES sync backlog
    - `measurement-rights-tier-block.md` — investigate `rights_tier.r3_egress_blocked` / `rights_tier.r3_outbound_blocked`
    - `measurement-no-local-provider.md` — recover from `rights_tier.no_local_provider` and drain `awaiting_local_provider` tasks
    - _Requirements: 9.7, 9.8, 9.9, 9.11, 7.5_

- [ ] 15. Test suites: 26 Hypothesis property tests, 5 named compliance tests, perf, e2e
  - [ ] 15.1 Implement Hypothesis composite strategies in `apps/api/core/tests/measurement/strategies.py`
    - `standardized_items()` (all eight question types; mixed CJK/Latin; 0..50 options; Likert 2..11 points; full-width punctuation; NFC variants), `concept_ontology_revisions()`, `validated_scales()`, `egress_payloads()`, `audit_field_tuples()`, `librarian_metadata_payloads()`, `skip_logic_graphs()`, `ocr_confidence_histograms()`
    - Reused by every property test; not optional
    - _Requirements: 5.4, 9.5, 9.6_

  - [ ]* 15.2 Property test 1: Intake admission predicate
    - **Property 1: Intake admission predicate**
    - File `apps/api/core/tests/measurement/properties/test_p01_intake_admission.py`; `@settings(max_examples=200, deadline=None)`; uses fakeredis + pytest-postgresql
    - **Validates: Requirements 1.3, 1.4, 1.10**

  - [ ]* 15.3 Property test 2: Source_Questionnaire structural invariants
    - **Property 2: Source_Questionnaire structural invariants**
    - File `apps/api/core/tests/measurement/properties/test_p02_sq_invariants.py`
    - **Validates: Requirements 1.2, 9.4**

  - [ ]* 15.4 Property test 3: OCR confidence and outcome routing
    - **Property 3: OCR confidence and outcome routing**
    - File `apps/api/core/tests/measurement/properties/test_p03_ocr_routing.py`
    - **Validates: Requirements 1.5, 1.6, 1.7, 1.11**

  - [ ]* 15.5 Property test 4: Librarian metadata authority
    - **Property 4: Librarian metadata authority**
    - File `apps/api/core/tests/measurement/properties/test_p04_metadata_authority.py`
    - **Validates: Requirements 1.8, 1.9, 1.12**

  - [ ]* 15.6 Property test 5: Item_Extractor preserves source order and bytes
    - **Property 5: Item_Extractor preserves source order and source bytes**
    - File `apps/api/core/tests/measurement/properties/test_p05_extractor_preservation.py`
    - **Validates: Requirements 2.1, 2.9**

  - [ ]* 15.7 Property test 6: Raw_Item structural and classification invariants
    - **Property 6: Raw_Item structural and classification invariants**
    - File `apps/api/core/tests/measurement/properties/test_p06_raw_item_invariants.py`
    - **Validates: Requirements 2.2, 2.3, 2.8**

  - [ ]* 15.8 Property test 7: Skip_Logic resolution and matrix grouping
    - **Property 7: Skip_Logic resolution and matrix grouping**
    - File `apps/api/core/tests/measurement/properties/test_p07_skip_logic_matrix.py`
    - **Validates: Requirements 2.4, 2.5, 2.6**

  - [ ]* 15.9 Property test 8: Round-trip equivalence across all three formats
    - **Property 8: Round-trip equivalence across all three formats**
    - File `apps/api/core/tests/measurement/properties/test_p08_roundtrip_equivalence.py`; `@settings(max_examples=200, deadline=None)` raised to compensate for the larger generator surface; fails reduce via Hypothesis shrinker
    - **Validates: Requirements 5.1, 5.2, 5.4, 5.5, 5.6, 5.7**

  - [ ]* 15.10 Property test 9: Standardized_Item canonical schema and option duality
    - **Property 9: Standardized_Item canonical schema and option duality**
    - File `apps/api/core/tests/measurement/properties/test_p09_canonical_schema.py`
    - **Validates: Requirements 3.1, 3.2, 3.3, 3.6**

  - [ ]* 15.11 Property test 10: Versioning and lifecycle invariants
    - **Property 10: Versioning and lifecycle invariants**
    - File `apps/api/core/tests/measurement/properties/test_p10_versioning_lifecycle.py`
    - **Validates: Requirements 3.4, 3.5, 3.8, 3.9, 6.3**

  - [ ]* 15.12 Property test 11: Pipeline-fault routing and content preservation
    - **Property 11: Pipeline-fault routing and content preservation**
    - File `apps/api/core/tests/measurement/properties/test_p11_fault_routing.py`
    - **Validates: Requirements 2.7, 2.10, 3.7, 4.7, 5.6, 5.7**

  - [ ]* 15.13 Property test 12: Concept_Tagger ontology fidelity and rights-tier routing
    - **Property 12: Concept_Tagger ontology fidelity and rights-tier routing**
    - File `apps/api/core/tests/measurement/properties/test_p12_tagger_ontology_routing.py`; uses a deterministic AI-router mock returning canned tag/scale results
    - **Validates: Requirements 4.1, 4.2, 4.3, 4.4, 4.5, 4.6, 4.8, 9.10, 9.11**

  - [ ]* 15.14 Property test 13: Pretty_Printer format admission and language preservation
    - **Property 13: Pretty_Printer format admission and language preservation**
    - File `apps/api/core/tests/measurement/properties/test_p13_pretty_printer_admission.py`
    - **Validates: Requirements 5.1, 5.2, 5.3**

  - [ ]* 15.15 Property test 14: Review_Queue inclusion, transitions, and merge atomicity
    - **Property 14: Review_Queue inclusion, transitions, and merge atomicity**
    - File `apps/api/core/tests/measurement/properties/test_p14_review_queue_transitions.py`
    - **Validates: Requirements 6.1, 6.2, 6.4, 6.5, 6.6, 6.9**

  - [ ]* 15.16 Property test 15: Review_Queue filter correctness
    - **Property 15: Review_Queue filter correctness**
    - File `apps/api/core/tests/measurement/properties/test_p15_review_queue_filters.py`
    - **Validates: Requirements 6.7**

  - [ ]* 15.17 Property test 16: Approval-gated egress and Recommendation_Service exclusion
    - **Property 16: Approval-gated egress and Recommendation_Service exclusion**
    - File `apps/api/core/tests/measurement/properties/test_p16_approval_egress.py`
    - **Validates: Requirements 6.8, 7.2**

  - [ ]* 15.18 Property test 17: Search and find-similar API contract
    - **Property 17: Search and find-similar API contract**
    - File `apps/api/core/tests/measurement/properties/test_p17_search_api_contract.py`
    - **Validates: Requirements 7.6, 7.7, 7.8, 7.9, 7.10, 7.11, 7.12**

  - [ ]* 15.19 Property test 18: Elasticsearch sync-failure backlog
    - **Property 18: Elasticsearch sync-failure backlog**
    - File `apps/api/core/tests/measurement/properties/test_p18_es_sync_backlog.py`
    - **Validates: Requirements 7.5**

  - [ ]* 15.20 Property test 19: AI Survey Designer recommendation flow
    - **Property 19: AI Survey Designer recommendation flow**
    - File `apps/api/core/tests/measurement/properties/test_p19_designer_recommendation.py`
    - **Validates: Requirements 8.1, 8.2, 8.3, 8.4, 8.5, 8.6, 8.7, 11.7**

  - [ ]* 15.21 Property test 20: Rights_Tier classification, propagation, and audit-field enforcement
    - **Property 20: Rights_Tier classification, propagation, and audit-field enforcement**
    - File `apps/api/core/tests/measurement/properties/test_p20_rights_tier_classify.py`
    - **Validates: Requirements 9.1, 9.2, 9.3, 9.4, 9.5, 9.6, 9.12**

  - [ ]* 15.22 Property test 21: Egress redaction and block matrix
    - **Property 21: Egress redaction and block matrix**
    - File `apps/api/core/tests/measurement/properties/test_p21_egress_matrix.py`
    - **Validates: Requirements 9.7, 9.8, 9.9, 8.5, 8.6**

  - [ ]* 15.23 Property test 22: Library_Snapshot identity and daily limit
    - **Property 22: Library_Snapshot identity and daily limit**
    - File `apps/api/core/tests/measurement/properties/test_p22_snapshot_identity.py`
    - **Validates: Requirements 9.13, 9.14**

  - [ ]* 15.24 Property test 23: Audit_Log filter equivalence for measurement entries
    - **Property 23: Audit_Log filter equivalence for measurement entries**
    - File `apps/api/core/tests/measurement/properties/test_p23_audit_filter_equiv.py`
    - **Validates: Requirements 9.15**

  - [ ]* 15.25 Property test 24: Milestone evaluation predicate
    - **Property 24: Milestone evaluation predicate**
    - File `apps/api/core/tests/measurement/properties/test_p24_milestone_predicate.py`
    - **Validates: Requirements 10.1, 10.2, 10.3, 10.4, 10.7, 10.8**

  - [ ]* 15.26 Property test 25: Dashboard staleness threshold
    - **Property 25: Dashboard staleness threshold**
    - File `apps/api/core/tests/measurement/properties/test_p25_dashboard_staleness.py`
    - **Validates: Requirements 10.5, 10.6**

  - [ ]* 15.27 Property test 26: Researcher-contributor lifecycle
    - **Property 26: Researcher-contributor lifecycle**
    - File `apps/api/core/tests/measurement/properties/test_p26_contributor_lifecycle.py`
    - **Validates: Requirements 11.1, 11.2, 11.3, 11.4, 11.5, 11.6**

  - [ ]* 15.28 Compliance test `compliance_test_r2_no_verbatim_egress`
    - File `apps/api/core/tests/measurement/compliance/test_r2_no_verbatim_egress.py`
    - For any R2 item, asserts no API response, webhook payload, export bundle, or AI provider call leaving the local pipeline contains a contiguous span ≥ 8 chars from the item's verbatim stem or option text
    - _Requirements: 9.7_
    - _Properties: 21_

  - [ ]* 15.29 Compliance test `compliance_test_r3_blocked`
    - File `apps/api/core/tests/measurement/compliance/test_r3_blocked.py`
    - For any R3 item, every egress channel except the librarian review surface returns 403 with `rights_tier_egress_blocked`
    - _Requirements: 9.9_
    - _Properties: 21_

  - [ ]* 15.30 Compliance test `compliance_test_r3_local_only_routing`
    - File `apps/api/core/tests/measurement/compliance/test_r3_local_only_routing.py`
    - For any R3 task submitted to `tag_concepts`, the AI provider URL host is in `Settings.local_only_provider_hosts`
    - _Requirements: 9.10, 9.11_
    - _Properties: 12, 21_

  - [ ]* 15.31 Compliance test `compliance_test_audit_field_guard`
    - File `apps/api/core/tests/measurement/compliance/test_audit_field_guard.py`
    - For any write attempt missing or supplying an empty value for any of the five mandatory audit fields, the row is rejected and exactly one `audit_field.missing` event is emitted naming the missing field
    - _Requirements: 9.5, 9.6_
    - _Properties: 20_

  - [ ]* 15.32 Compliance test `compliance_test_audit_logs_append_only`
    - File `apps/api/core/tests/measurement/compliance/test_audit_logs_append_only.py`
    - The Measurement_Library exposes no endpoint that mutates or deletes existing `audit_logs` rows; mirrors the api-platform-export Req 7.6 conformance pattern
    - _Requirements: 9.12_
    - _Properties: 23_

  - [ ]* 15.33 Performance test bundle in `apps/api/core/tests/measurement/performance/`
    - `perf_search.py` (Req 7.13: search p95 ≤ 500 ms / p99 ≤ 1000 ms against 40 k-item bank)
    - `perf_find_similar.py` (Req 7.14: find-similar p95 ≤ 1500 ms / p99 ≤ 3000 ms)
    - `perf_review_queue.py` (Req 6.7: list p95 ≤ 2000 ms against 10 k-entry queue)
    - `perf_audit_log.py` (Req 9.15: filter p95 ≤ 3000 ms against 10 k-entry result)
    - `perf_es_sync_lag.py` (Req 7.3, 7.4: PG-commit-to-ES-visible p99 ≤ 60 s rolling 24 h)
    - All five run on `locust` against the synthetic 40 k-item harness
    - _Requirements: 6.7, 7.3, 7.4, 7.13, 7.14, 9.15_

  - [ ]* 15.34 End-to-end and Celery DAG integration tests in `apps/api/core/tests/measurement/e2e/`
    - `test_e2e_librarian_flow.py`: upload → OCR → extract → standardize → tag → roundtrip → review approve → ES sync → search returns the item
    - `test_e2e_recommendation_flow.py`: researcher submits construct → search returns item → accepts into draft → exports survey with citations appendix
    - `test_celery_dag_integration.py`: verifies header propagation of the five mandatory audit fields across all DAG hops; runs against a real Postgres + Redis + Elasticsearch (with IK plugin) using the existing `tests/conftest.py` fixtures
    - _Requirements: 1.1, 5.5, 7.2, 8.1, 8.2, 8.4, 9.5_

- [ ] 16. Documentation
  - [ ] 16.1 Update `apps/api/core/docs/measurement/README.md`
    - Architecture diagrams reproduced from design.md
    - Pointer to `app/core/measurement_versions.py` for current version constants
    - Operator overview of the three Rights_Tier_Gate enforcement points
    - _Requirements: 9.1, 9.4, 9.7_

  - [ ] 16.2 Add OpenAPI examples and developer guide
    - Annotate every router under `app/api/v1/measurement/` with FastAPI `responses=` examples covering success and each named error code
    - Generate `docs/measurement/openapi-snippet.json` from the OpenAPI export and check it into the repo for downstream API client generators
    - _Requirements: 7.6, 7.9, 7.11, 7.12_

  - [ ] 16.3 Final checkpoint
    - Run the full test suite (unit + property + compliance + e2e + perf smoke) on a fresh database, confirm all migrations apply cleanly, surface any deviations
    - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional in MVP rollout but each maps to one specific named property or compliance check. The 26 property tests collectively validate the 26 correctness properties listed in design.md §"Correctness Properties"; the 5 compliance tests collectively validate the Rights_Tier_Gate and audit-field-guard invariants from design.md §"Rights Tier and Compliance Architecture".
- Every task references granular sub-requirements from `requirements.md` (e.g., `1.3, 1.4, 1.10` rather than a bare `Requirement 1`) so traceability is per acceptance criterion.
- Five mandatory audit fields (`data_snapshot_id`, `extraction_version`, `norm_version`, `threshold_version`, `trace_id`) propagate through Celery headers, are persisted as NOT NULL columns on every measurement table, and ride every audit_logs.details payload. The trigger `enforce_measurement_audit_fields` rejects any malformed write at the database level; the audit-field guard wrapper converts the SQL exception into a `audit_field.missing` audit event before re-raising HTTP 500.
- Reuse-only invariants the implementation MUST honor: the existing T10 `audit_logs` schema is unchanged; existing `get_principal` and `require_scope` are reused without forking; the existing AI router `app.core.ai_router.route_request` is reached only through the new `route_for_rights_tier` wrapper; the existing webhook emitter and notification service are reused for contributor flows.

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1", "1.2", "1.3", "1.9"] },
    { "id": 1, "tasks": ["1.4"] },
    { "id": 2, "tasks": ["1.5"] },
    { "id": 3, "tasks": ["1.6"] },
    { "id": 4, "tasks": ["1.7"] },
    { "id": 5, "tasks": ["1.8", "2.1", "2.2", "2.4"] },
    { "id": 6, "tasks": ["2.3", "2.5", "3.3", "6.1", "6.2", "9.1", "12.1", "14.1"] },
    { "id": 7, "tasks": ["3.1", "4.1", "5.1", "5.3", "7.1", "9.2", "12.4"] },
    { "id": 8, "tasks": ["3.2", "3.4", "4.2", "4.3", "5.2", "6.3", "7.2", "7.3", "9.3", "9.4", "9.5", "12.2", "12.3", "14.2", "14.3"] },
    { "id": 9, "tasks": ["3.5", "3.6", "4.4", "5.4", "6.4", "7.4", "8.1", "8.2", "9.6", "13.1"] },
    { "id": 10, "tasks": ["8.3", "8.4", "13.2", "13.3", "11.1"] },
    { "id": 11, "tasks": ["10.1", "10.2", "10.3", "10.4", "11.2", "11.3", "11.4", "11.5", "11.6"] },
    { "id": 12, "tasks": ["15.1"] },
    { "id": 13, "tasks": ["15.2", "15.3", "15.4", "15.5", "15.6", "15.7", "15.8", "15.9", "15.10", "15.11", "15.12", "15.13", "15.14", "15.15", "15.16", "15.17", "15.18", "15.19", "15.20", "15.21", "15.22", "15.23", "15.24", "15.25", "15.26", "15.27", "15.28", "15.29", "15.30", "15.31", "15.32"] },
    { "id": 14, "tasks": ["15.33", "15.34"] },
    { "id": 15, "tasks": ["16.1", "16.2"] }
  ]
}
```
