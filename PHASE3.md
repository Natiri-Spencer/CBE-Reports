# Phase 3: Backend security

Implemented for the existing SQLite deployment on 25 October 2026. School records were preserved. The database is at Alembic revision `0005_security`.

## Controls and evidence

| Requirement | Implementation | Verification |
| --- | --- | --- |
| Reject missing/default JWT secret | Every server environment validates an independently generated secret, at least 32 bytes with no known placeholder values. No development fallback. | Subprocess startup tests cover DEV and PROD, missing, placeholder and weak keys. |
| One password hashing implementation | `app/core/passwords.py` uses argon2-cffi Argon2id for registration, administrator bootstrap, verification and rehashing. Existing Argon2 hashes remain valid. | Existing database has three Argon2 hashes; hash and malformed-hash tests pass. |
| Login limiting and monitoring | SQLite serializes attempt reservations across workers: five failures/pending attempts per account and thirty authentication/registration requests per client in fifteen minutes. Returns 429 with Retry-After. | Six simultaneous failed requests produce five 401s and one 429. Administrator monitoring shows aggregate counts for the last day. |
| Token lifecycle and disabled accounts | Access JWTs last fifteen minutes. Opaque refresh tokens rotate, are stored only as SHA-256 digests, and have an absolute seven-day session lifetime. Reuse revokes the session family. Logout and disabling revoke sessions immediately. | Expiry, missing claims, reuse, separate sessions, account approval/disable/reactivation and last-admin protection tests. |
| Endpoint permissions | All 28 business endpoints have a staff or explicit role dependency. Unknown roles and disabled users are rejected. Signup creates a pending teacher account, requiring administrator approval. | Recursive route audit plus HTTP role tests. Administrator account controls are available on the overview screen. |
| CORS | Exact approved local origins: `http://localhost:3000`, `http://127.0.0.1:3000`, Android `https://localhost`. Explicit methods/headers; bearer authentication, no credential cookies. | Web and Android preflights succeed; unknown, null and lookalike origins fail. |
| Private logs | No request access logs or forwarded-header trust. SQL parameters are hidden. Unexpected errors emit only a fixed event and generic response. Authentication logs contain event names, never usernames, IPs, passwords or tokens. | Private error/log tests; migration logging preserves monitoring and keeps access logging disabled. |
| PDF handling | Active PDF endpoints stream chunks from memory, close their buffers and send no-store headers. Legacy booklet generation also uses memory. No server PDF files or public PDF URLs. | PDF signature, headers, no Content-Length/persistent file checks, and a real HTTP download. |
| Health/readiness | Public `/health` is liveness. `/ready` checks database access, the current migration and a verified backup less than 36 hours old with matching source, key and checksum. Failure returns generic 503. | Failure tests, real database audit, production HTTP smoke checks. |
| Backups and restore | Encrypted consistent SQLite snapshots, an independent Fernet key, fourteen-day retention and a disposable restore/integrity/FK/count check on every backup. Restores revoke all historical sessions and increment token versions. | Actual school backup restored and checked independently; corruption, wrong-key, overwrite and restored-session tests. |

## Session and permission policy

- Both approved teachers and administrators can read/create learner identities and read/export marks.
- Only teachers can submit marks. Only administrators can access fees, payments, finance/learner reports, administrator dashboards, account controls and authentication monitoring.
- `/auth/signup` returns 202 and never signs the applicant in. New passwords require at least twelve characters. Duplicate signup requests do not reveal account status.
- `/auth/token` accepts the existing OAuth form login. JWT subjects are numeric account IDs; claims include issuer, audience, session ID, token version, type and expiry. Every authenticated request checks current account and session state.
- `/auth/refresh` authenticates using the opaque refresh token in its JSON body. The frontend serializes renewal and preserves mutation retry keys across renewal.
- `/auth/logout` requires an access token. `/auth/logout-refresh` accepts the opaque token so an expired access token does not prevent revocation. Logout affects that session; disabling an account affects all its sessions. A network failure leaves credentials available for a logout retry and displays an error.
- Refresh credentials remain in sessionStorage; access credentials follow the existing localStorage flow. Closing a tab without a refresh credential may require another login. Old JWTs issued before Phase 3 require a fresh login.
- Failure monitoring stores HMAC account/client keys rather than raw identifiers. Attempt records older than seven days are removed on the next authentication reservation. Client identity comes from the connection, never an untrusted forwarded header.

## Backup operation

The application's lifespan starts the backup worker automatically. It checks on startup and every thirty minutes, creates a verified backup when the latest is at least twenty-four hours old or invalid, and retries failures on the next check. It runs while the backend is running; after downtime it catches up at startup. This machine does not expose a working Windows Task Scheduler. No independent Windows scheduled task was installed.

Backups live under `.local/backups`. The first verified encrypted backups are already present. Windows ACLs on `.env`, `.local` and the SQLite data files were applied and checked: only the running Windows account and SYSTEM have access. Future files beneath `.local` inherit those restrictions. Run the permission script as the account that will run the backend; do not change the service account without granting it the required private access.

The backup encryption key is in the ignored `.env`. Keep a secure recovery copy of that key. The key must remain available to read older backups; generating a replacement does not decrypt older snapshots. Configured keys and raw credentials are never printed.

Run an extra backup from the backend directory:

```powershell
.\.venv\Scripts\python.exe scripts/backup_database.py
```

Restore to a NEW file, using the original backup key in the environment/configuration:

```powershell
.\.venv\Scripts\python.exe scripts/backup_database.py --restore .local/backups/SELECTED.backup --destination .local/restored-school.sqlite3
```

The command refuses to overwrite an existing file, authenticates/decrypts the snapshot, checks integrity and foreign keys, reopens the result, and verifies all table counts. It revokes restored sessions before writing. Stop the backend before choosing a restored database as `DATABASE_URL`, review the recovered account state, and create a new verified backup before reopening access. The restore test never replaces the live database.

## Configuration and deployment

For a new installation, `scripts/bootstrap_security.py` creates unique JWT and backup keys in `.env` and refuses to overwrite an existing configuration. `scripts/secure_local_files.ps1` applies and verifies the private Windows ACLs. The example environment deliberately contains unusable placeholders.

`run_prod.ps1` remains bound to loopback. For an external deployment, configure HTTPS at the serving layer and put the exact deployed web origin in `CORS_ORIGINS`. The current allowlist supports local web use and the configured Capacitor Android origin. Arbitrary web origins remain blocked. Forwarded headers are disabled by default; a proxy deployment must deliberately configure trusted proxy handling if per-client network limits are needed behind it.

## Validation and local evidence

- All 43 backend regression/security tests, 25 frontend tests and five real HTTP React integration tests passed. The frontend build, OpenAPI drift and Alembic model/schema drift checks passed.
- `.local/phase3-migration-20261025`: original verified pre-Phase-3 backup, anonymized rehearsal and successful application; original school rows preserved.
- `.local/phase3-final-verification`: repeat rehearsal/application at the final migration fingerprint, with no schema drift or changed school records.
- `.local/phase3-audit-20261025.json`: twenty passing checks against the real database, endpoint permissions and an independent encrypted restore.
- `.local/phase3-production-smoke.json`: `/health`, `/ready` and frontend/deep links return 200; private accounts return 401; unknown auth paths return JSON 404.
- `.local/backups/latest.json`: latest encrypted backup checksum, source/key identifiers and successful restore evidence. No secret values.

Existing counts remain: three users, three learners, three fee records, twelve payment rows, seven activity rows and zero marks. Synthetic frontend verification uses a separate temporary database. Start a fresh `tests/serve_browser_fixture.py` process for each integration-suite run because those tests deliberately mutate their fixture.
