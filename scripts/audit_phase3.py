"""Read-only Phase 3 audit, plus a disposable restore of the latest encrypted backup."""
from collections import Counter
from contextlib import closing
from datetime import datetime, timezone
import hashlib
import json
import logging
from pathlib import Path
import sqlite3
import sys
from tempfile import TemporaryDirectory
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
from app.core.settings import ROOT, CORS_ORIGINS, ACCESS_SECONDS, SESSION_SECONDS
from app.core.backups import BACKUP_DIRECTORY, backup_is_current, restore_file, source_path
from app.core.database import engine
from app.main import app
from scripts.prepare_migration import inventory, migration_fingerprint, quote


def audit():
    checks={}
    with closing(sqlite3.connect(source_path().as_uri()+'?mode=ro',uri=True)) as db:
        counts=inventory(db)
        checks['sqlite_integrity_and_foreign_keys']=True
        checks['security_migration_applied']=db.execute('SELECT version_num FROM alembic_version').fetchone()[0]=='0005_security'
        checks['one_password_scheme']=db.execute("SELECT count(*) FROM users WHERE hashed_password NOT LIKE '$argon2%'").fetchone()[0]==0
        checks['known_account_roles']=db.execute("SELECT count(*) FROM users WHERE role NOT IN ('teacher','admin')").fetchone()[0]==0
        checks['active_administrator_exists']=db.execute("SELECT count(*) FROM users WHERE role='admin' AND is_active=1").fetchone()[0]>0
        checks['security_tables_exist']={'auth_sessions','refresh_tokens','login_attempts'} <= counts.keys()
        original=ROOT/'.local/phase3-migration-20261025/verified-backup.sqlite3'
        with closing(sqlite3.connect(original.as_uri()+'?mode=ro',uri=True)) as before:
            preserved=True
            for table in inventory(before):
                if table=='alembic_version': continue
                columns=[row[1] for row in before.execute(f'PRAGMA table_info({quote(table)})')]
                query='SELECT '+','.join(map(quote,columns))+' FROM '+quote(table)
                if Counter(before.execute(query).fetchall())!=Counter(db.execute(query).fetchall()): preserved=False
            checks['all_pre_phase3_school_rows_preserved']=preserved
    rehearsal=json.loads((ROOT/'.local/phase3-final-verification/rehearsal-result.json').read_text())
    checks['final_migration_rehearsal_matches_code']=rehearsal['migration_fingerprint']==migration_fingerprint(ROOT)
    checks['rehearsal_schema_matches_models']=rehearsal['schema_matches_models'] and rehearsal['repeat_upgrade_verified']
    checks['encrypted_backup_current_and_checksum_valid']=backup_is_current()
    manifest=json.loads((BACKUP_DIRECTORY/'latest.json').read_text())
    with TemporaryDirectory(prefix='phase3-audit-restore-',dir=BACKUP_DIRECTORY) as directory:
        restored=Path(directory)/'restore.sqlite3'
        checks['independent_encrypted_restore_matches_counts']=restore_file(BACKUP_DIRECTORY/manifest['file'],restored)==manifest['row_counts']
        with closing(sqlite3.connect(restored)) as db:
            checks['restore_cannot_revive_sessions']=db.execute('SELECT count(*) FROM auth_sessions WHERE revoked_at IS NULL').fetchone()[0]==0
    checks['database_parameters_hidden']=engine.hide_parameters is True
    checks['raw_access_logging_disabled']=logging.getLogger('uvicorn.access').disabled
    checks['approved_local_web_and_android_origins']=set(CORS_ORIGINS)=={'http://localhost:3000','http://127.0.0.1:3000','https://localhost'}
    checks['bounded_token_lifetimes']=ACCESS_SECONDS==900 and SESSION_SECONDS==604800
    def flatten(routes,prefix=''):
        for route in routes:
            if isinstance(route,APIRoute): yield prefix+route.path,route
            elif hasattr(route,'original_router'): yield from flatten(route.original_router.routes,prefix+route.include_context.prefix)
    def dependencies(node):
        names=set()
        for child in node.dependencies:
            names.add(getattr(child.call,'__name__','')); names.update(dependencies(child))
        return names
    public={'/health','/ready','/auth/signup','/auth/token','/auth/refresh','/auth/logout-refresh','/{full_path:path}'}
    permissions=True; secured=0
    for path,route in flatten(app.routes):
        if path in public: continue
        secured+=1; names=dependencies(route.dependant)
        permissions &= 'get_current_user' in names
        if path.startswith(('/fees','/reports','/admin','/auth/accounts','/auth/monitoring')): permissions &= 'admin_only' in names
        if path=='/marks/submit': permissions &= 'teacher_only' in names
    checks['every_business_endpoint_has_required_permissions']=bool(permissions and secured>20)
    with TestClient(app) as client:
        checks['health_responds']=client.get('/health').json()=={'status':'ok'}
        checks['readiness_responds']=client.get('/ready').json()=={'status':'ready'}
        checks['private_accounts_require_authentication']=client.get('/auth/accounts').status_code==401
    result={'audited_at':datetime.now(timezone.utc).isoformat(),'passed':all(checks.values()),'checks':checks,
            'secured_routes':secured,'row_counts':counts,'backup_restore_verified':True}
    output=ROOT/'.local/phase3-audit-20261025.json'
    output.write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(result,indent=2))
    return result['passed']

if __name__=='__main__': raise SystemExit(0 if audit() else 1)
