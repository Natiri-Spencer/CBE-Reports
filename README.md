# CBE Reports API

FastAPI service for teacher authentication, learner marks, CBC performance
reports, fee records, payments, and PDF exports.

## Requirements

- Python 3.11 or newer
- SQLite for local development or PostgreSQL for deployment

## Local setup

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements-dev.txt
Copy-Item .env.example .env
python init_db.py
python -m uvicorn app.main:app --reload
```

Set `INITIAL_ADMIN_USERNAME` and `INITIAL_ADMIN_PASSWORD` before running
`init_db.py` to create the first administrator. Public signup creates teacher
accounts only.

## Configuration

- `ENV`: `DEV` or `PROD`
- `JWT_SECRET_KEY`: required in production
- `DATABASE_URL`: SQLAlchemy database URL
- `CORS_ORIGINS`: comma-separated permitted frontend origins

Production should use PostgreSQL, HTTPS, a long random JWT secret, and an
explicit list of CORS origins.

## Verification

```powershell
python -m unittest discover -s tests -v
```

The test suite uses an isolated in-memory database. It does not modify the
development database.

The liveness endpoint is `GET /health`; API documentation is available at
`/docs` in environments where documentation is enabled.

## Repository structure

The backend and frontend are maintained as two independent Git repositories.
Clone this repository beside `student_reports_frontend`; do not initialize a
third Git repository around both folders. The frontend repository is
https://github.com/Natiri-Spencer/CBE-Reports-Frontend.git.

Local databases, learner exports, generated reports, PDFs, and original learner
lists are deliberately excluded from Git. Tests use anonymized data from
`tests/fixtures`.
