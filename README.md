# CBE Reports API

FastAPI service for teacher authentication, learner marks, CBC performance
reports, fee records, payments, and PDF exports.

## Requirements

- Python 3.11 or newer
- SQLite, retained for deployment at the user's request

## Local setup for a new database

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements-dev.txt
python scripts/bootstrap_security.py
python init_db.py
python scripts/backup_database.py
./scripts/secure_local_files.ps1
python -m uvicorn app.main:app --reload --env-file .env --no-access-log --no-proxy-headers
```

Set `INITIAL_ADMIN_USERNAME` and `INITIAL_ADMIN_PASSWORD` before running
`init_db.py` to create the first administrator (password: at least twelve characters). Public signup requests a teacher account; an administrator must approve access.

## Configuration

- `ENV`: `DEV` or `PROD`
- `JWT_SECRET_KEY`: required and validated in every environment; no default
- `BACKUP_ENCRYPTION_KEY`: independent Fernet key required for verified backups
- `DATABASE_URL`: SQLAlchemy database URL
- `CORS_ORIGINS`: comma-separated permitted frontend origins

Production uses SQLite and a long random JWT secret. Deploy behind HTTPS with an explicit list
of CORS origins. Writes acquire a SQLite transaction lock before reading
balances or retry receipts. Existing databases follow the backup and rehearsal
workflow below before any schema upgrade.

## API contract

The version 2 contract is FastAPI's `/openapi.json`, exported to
`contracts/openapi.json` and the frontend's `src/generated/openapi.json`.
Regenerate it after intentional API changes:

```powershell
python scripts/export_openapi.py
python scripts/export_openapi.py --check
```

Learner IDs are permanent UUIDs. Marks require `learner_id`, `class_name`,
`academic_year`, `term`, and all nine scores, including `creative_arts`.
Names are display values and cannot identify a write target. Scores use
snake_case in Python, JSON, and JavaScript.

Learner, marks, payment-history, and dashboard-report reads support `limit`
and `offset`, returning `items`, `total`, `limit`, and `offset`. Report summaries
cover the entire selected period independently of the displayed page.

Mutating learner, marks, fee-save, and payment requests require an
`Idempotency-Key` header. Retry an uncertain request with the same key and
payload. A changed payload with an existing key returns 409. Committed responses
are stored in the same transaction as the mutation. The frontend retains
pending keys across tab reloads and an expired login.

## Verification

Existing databases must follow the verified backup and anonymized rehearsal
workflow in [PHASE2.md](PHASE2.md) before applying schema migrations.

```powershell
python -m unittest discover -s tests -v
```

The test suite uses isolated in-memory and temporary file-backed databases.
It does not modify the development database. Concurrency checks use separate
SQLite connections for six simultaneous requests.

For form-to-API integration checks, start `python tests/serve_browser_fixture.py`
in this backend environment, then run the frontend command documented in its
README. This fixture creates a new synthetic school in `.local`; it never uses
the real school database.

Security policy, session renewal/logout, account approval, daily encrypted backups and restore instructions are in [PHASE3.md](PHASE3.md).

The liveness endpoint is `GET /health`; readiness is `GET /ready` and requires a current verified backup. API documentation is available at
`/docs` in environments where documentation is enabled.

## Repository structure

The backend and frontend are maintained as two independent Git repositories.
Clone this repository beside `student_reports_frontend`; do not initialize a
third Git repository around both folders. The frontend repository is
https://github.com/Natiri-Spencer/CBE-Reports-Frontend.git.

Local databases, learner exports, generated reports, PDFs, and original learner
lists are deliberately excluded from Git. Tests use anonymized data from
`tests/fixtures`.
