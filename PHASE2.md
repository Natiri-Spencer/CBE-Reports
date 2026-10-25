# Phase 2: data and API stabilization

Implemented and verified on 25 October 2026. The user explicitly chose to
**keep SQLite**, replacing the original requirement to switch to PostgreSQL.

## Requirement audit

| Requirement | Implementation and evidence |
| --- | --- |
| Database choice | SQLite retained as explicitly requested. Production guidance in README matches this decision. |
| Standard migrations | Backend `alembic.ini` is canonical; the workspace configuration uses the same migration directory. Head is `0004_standardize_indexes`. Rehearsal and the post-migration audit detect no ORM/schema drift. |
| Permanent learner identity | Learners have UUID primary keys. Mark and fee writes require `learner_id`. The migrated school database has no missing learner references. Identical names remain distinct; names are display values. |
| Academic context on marks | Every mark has non-null `class_name`, `academic_year`, and `term`. New writes require a valid class/year/term. Historical records with unknown periods use explicit year 0/term 0 rather than an invented current period. Ranking and report joins use the same academic context. |
| Duplicate prevention | Database unique constraint on `(learner_id, class_name, academic_year, term)`, plus non-null and score/period checks. Conflicting legacy data aborts migration without deleting records. Raw SQL constraint tests and the live-schema audit verify enforcement. |
| Standard field names | Scores use snake_case throughout Python, JSON and JavaScript: `creative_arts`, `integrated_science`, `social_studies`. Old aliases and name-based write payloads are rejected. The audit checks JSON field names. |
| OpenAPI contract | FastAPI version 2 publishes the source contract. Versioned backend/frontend JSON copies are exported by `scripts/export_openapi.py`; `--check` detects drift in CI. The shared JavaScript client validates requests and responses against this schema. SQLite timestamps are serialized as explicit UTC RFC 3339 date-times. |
| Shared CBC grading | `app/services/grading.py` contains the existing app's score bands. Zero is BE2. Valid fractional scores use nearest-integer rounding, ties to even; original scores are retained. Boundaries, fractions, invalid/non-finite scores and overflowing JSON numbers are tested. Exports and saved marks use the same rules. |
| Pagination | Learners, marks, payment history and dashboard reports expose `items`, `total`, `limit`, `offset`, with a maximum page size of 200. The learner picker and saved marks/report/payment-history views provide page controls. Report summaries cover the whole selected period. |
| Transaction and retry safety | Writes acquire a SQLite write lock before reading existing records. Request fingerprints and committed response receipts are persisted in the same transaction as marks/payments. Replays return the original result; changed payloads using an existing key return 409. Bulk mark failures roll back all records. The frontend retains retry keys across network failures, reloads and expired logins. File-backed SQLite tests exercise six simultaneous retries and independent requests. |

## Backup, rehearsal and application evidence

The real database was upgraded from `0002_permanent_learner_ids` to
`0004_standardize_indexes` only after a fresh backup and anonymized rehearsal.
Private evidence is retained outside Git in:

`.local/migration-rehearsal-20261025-06/`

- `verified-backup.sqlite3`: consistent pre-migration backup, integrity checked
  and restored to a separate database to verify it is readable.
- `anonymized.sqlite3`: learner names and permanent IDs, usernames, password
  hashes, payment notes/references, receipt responses and activity descriptions
  are replaced or removed; references remain consistent and the copy is vacuumed.
- `rehearsed.sqlite3`: migration tested twice and compared against ORM metadata.
- `manifest.json`, `rehearsal-result.json`, `applied-result.json`: checksums,
  migration-code fingerprint, row counts, integrity and application results.

The apply script locks writers and refuses changed source data, modified
evidence, or migration code changed since rehearsal. It checks that every
pre-existing school row is preserved and rolls back schema and data together
on failure. Only the Alembic revision metadata is expected to advance.

The read-only final audit is recorded in `.local/phase2-audit-20261025.json`.
All 19 invariant checks passed. The actual database retains 3 learners, 3 fee
records, 12 payment records, 3 users and 7 activity records; no school rows were
removed. There were no existing marks to assign an unknown period to. Synthetic
migration tests additionally verify that existing zero marks and permanent IDs
survive a versioned upgrade.

For future schema changes, use a fresh evidence directory:

```powershell
.\.venv\Scripts\python.exe scripts/prepare_migration.py --source fees.db --output .local/migration-NEW
.\.venv\Scripts\python.exe scripts/rehearse_migration.py .local/migration-NEW
.\.venv\Scripts\python.exe scripts/apply_verified_migration.py --source fees.db --evidence .local/migration-NEW
.\.venv\Scripts\python.exe scripts/audit_phase2.py --source fees.db --evidence .local/migration-NEW
```

Unknown tables require an explicit anonymization rule. Original backups must
remain private. Application import no longer changes the database schema.

## Verification

- Backend regression suite: 25 tests, including database constraints, migration
  rollback, versioned upgrade preservation, namesakes, class/term scoping,
  non-finite score validation, idempotency and concurrent writes.
- Frontend regression suite: 19 tests, including contract validation, permanent
  identity selection, pagination, retry-key persistence and session expiry.
- Form-to-API integration suite: 3 tests using actual React forms, HTTP calls
  and a separate synthetic SQLite school. Covers zero marks, payment/history/
  report refresh, and separate fee records for learners sharing a name.
- Production frontend build, OpenAPI drift check and live read-only invariant
  audit passed.

The in-app browser webview could not attach during a visual smoke-test attempt.
The form integration checks use React DOM against the real synthetic HTTP API;
native browser visual verification was not obtained.
