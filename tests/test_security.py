import os
import secrets
os.environ.setdefault("JWT_SECRET_KEY", secrets.token_urlsafe(48))
import asyncio
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from datetime import timedelta
import hashlib
import json
import logging
from pathlib import Path
import sqlite3
import subprocess
import sys
from tempfile import TemporaryDirectory
from threading import Barrier
import time
import unittest
from unittest.mock import patch
from cryptography.fernet import Fernet, InvalidToken
from fastapi import APIRouter
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
from jose import jwt
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import NullPool
from app.core.auth import issue_tokens, create_access_token, now, SECRET_KEY, ALGORITHM
from app.core.database import Base, get_db
from app.core.passwords import hash_password, verify_password
from app.main import app
from app.models.user import User
from app.models.security import AuthSession, RefreshToken, LoginAttempt
from app.core import backups

ROOT = Path(__file__).resolve().parents[1]

class SecurityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = TemporaryDirectory()
        cls.engine = create_engine('sqlite:///' + (Path(cls.directory.name)/'security.db').as_posix(),
            poolclass=NullPool, connect_args={"check_same_thread": False, "timeout": 30})
        @event.listens_for(cls.engine, "connect")
        def fk(connection, _):
            connection.execute("PRAGMA foreign_keys=ON")
        Base.metadata.create_all(cls.engine)
        cls.Session = sessionmaker(bind=cls.engine, autoflush=False)
        def test_db():
            with cls.Session() as db:
                yield db
        app.dependency_overrides[get_db] = test_db
        cls.client = TestClient(app)

    @classmethod
    def tearDownClass(cls):
        cls.client.close(); app.dependency_overrides.clear()
        cls.engine.dispose(); cls.directory.cleanup()

    def setUp(self):
        with self.engine.begin() as c:
            for table in reversed(Base.metadata.sorted_tables):
                c.execute(table.delete())
        with self.Session() as db:
            db.add_all([User(username='security-admin', role='admin', hashed_password=hash_password('testing-password')),
                        User(username='security-teacher', role='teacher', hashed_password=hash_password('testing-password'))])
            db.commit()

    def login(self, username='security-teacher', password='testing-password'):
        return self.client.post('/auth/token', data={'username': username, 'password': password})

    def tokens(self, username='security-teacher'):
        result=self.login(username)
        self.assertEqual(result.status_code,200,result.text)
        return result.json()

    def headers(self, tokens):
        return {'Authorization': 'Bearer '+tokens['access_token']}

    def test_pending_signup_requires_admin_approval(self):
        result=self.client.post('/auth/signup',json={'username':'new-teacher','password':'new-testing-password','role':'teacher'})
        self.assertEqual(result.status_code,202)
        self.assertEqual(self.login('new-teacher','new-testing-password').status_code,401)
        with self.Session() as db:
            user_id=db.query(User).filter_by(username='new-teacher').one().id
        admin=self.tokens('security-admin')
        approved=self.client.put(f'/auth/accounts/{user_id}/status',headers=self.headers(admin),json={'is_active':True})
        self.assertEqual(approved.status_code,200,approved.text)
        self.assertEqual(self.login('new-teacher','new-testing-password').status_code,200)
        self.assertEqual(self.client.post('/auth/signup',json={'username':'rogue','password':'testing-password','role':'admin'}).status_code,422)
        self.assertEqual(self.client.post('/auth/signup',json={'username':'weak','password':'short'}).status_code,422)

    def test_jwt_expiry_identity_and_hashed_refresh_storage(self):
        result=self.tokens()
        claims=jwt.get_unverified_claims(result['access_token'])
        self.assertEqual(claims['exp']-claims['iat'],900)
        self.assertNotIn('security-teacher',result['access_token'])
        self.assertTrue(claims['sub'].isdigit())
        self.assertNotIn('username',claims)
        self.assertLessEqual(result['refresh_expires_at']-now(),7*86400)
        with self.Session() as db:
            stored=db.query(RefreshToken).one()
            self.assertEqual(stored.digest,hashlib.sha256(result['refresh_token'].encode()).hexdigest())
        expired=create_access_token(claims,timedelta(seconds=-1))
        self.assertEqual(self.client.get('/learners',headers={'Authorization':'Bearer '+expired}).status_code,401)
        for field in ('exp','iat','nbf','iss','aud','jti','sid','ver','type','role'):
            invalid=claims.copy(); invalid.pop(field)
            encoded=jwt.encode(invalid,SECRET_KEY,algorithm=ALGORITHM)
            self.assertEqual(self.client.get('/learners',headers={'Authorization':'Bearer '+encoded}).status_code,401,field)

    def test_refresh_rotation_reuse_revokes_session_family(self):
        first=self.tokens()
        second=self.client.post('/auth/refresh',json={'refresh_token':first['refresh_token']})
        self.assertEqual(second.status_code,200,second.text)
        second=second.json()
        self.assertNotEqual(first['refresh_token'],second['refresh_token'])
        self.assertEqual(first['refresh_expires_at'],second['refresh_expires_at'])
        self.assertEqual(self.client.post('/auth/refresh',json={'refresh_token':first['refresh_token']}).status_code,401)
        self.assertEqual(self.client.get('/learners',headers=self.headers(second)).status_code,401)
        self.assertEqual(self.client.post('/auth/refresh',json={'refresh_token':second['refresh_token']}).status_code,401)

    def test_logout_revokes_access_and_refresh_but_not_other_sessions(self):
        one=self.tokens(); two=self.tokens()
        self.assertEqual(self.client.post('/auth/logout').status_code,401)
        self.assertEqual(self.client.post('/auth/logout',headers=self.headers(one)).status_code,200)
        self.assertEqual(self.client.get('/learners',headers=self.headers(one)).status_code,401)
        self.assertEqual(self.client.post('/auth/refresh',json={'refresh_token':one['refresh_token']}).status_code,401)
        self.assertEqual(self.client.get('/learners',headers=self.headers(two)).status_code,200)
        self.assertEqual(self.client.post('/auth/logout-refresh',json={'refresh_token':two['refresh_token']}).status_code,200)
        self.assertEqual(self.client.get('/learners',headers=self.headers(two)).status_code,401)

    def test_account_disable_and_reenable_never_resurrect_old_tokens(self):
        teacher=self.tokens(); admin=self.tokens('security-admin')
        with self.Session() as db:
            user=db.query(User).filter_by(username='security-teacher').one(); user_id=user.id
        for active in (False,True):
            result=self.client.put(f'/auth/accounts/{user_id}/status',headers=self.headers(admin),json={'is_active':active})
            self.assertEqual(result.status_code,200,result.text)
            self.assertEqual(self.client.get('/learners',headers=self.headers(teacher)).status_code,401)
            self.assertEqual(self.client.post('/auth/refresh',json={'refresh_token':teacher['refresh_token']}).status_code,401)
        self.assertEqual(self.login().status_code,200)
        with self.Session() as db:
            admin_id=db.query(User).filter_by(role='admin').one().id
        self.assertEqual(self.client.put(f'/auth/accounts/{admin_id}/status',headers=self.headers(admin),json={'is_active':False}).status_code,409)

    def test_unknown_roles_and_database_role_changes_are_rejected(self):
        result=self.tokens()
        with self.Session() as db:
            user=db.query(User).filter_by(role='teacher').one(); user.role='other'; db.commit()
        self.assertEqual(self.client.get('/learners',headers=self.headers(result)).status_code,401)
        self.assertEqual(self.login().status_code,401)

    def test_absolute_session_expiry(self):
        result=self.tokens()
        with self.Session() as db:
            db.query(AuthSession).update({'expires_at':now()-1}); db.commit()
        self.assertEqual(self.client.get('/learners',headers=self.headers(result)).status_code,401)
        self.assertEqual(self.client.post('/auth/refresh',json={'refresh_token':result['refresh_token']}).status_code,401)

    def test_parallel_failed_logins_are_limited_and_privately_monitored(self):
        barrier=Barrier(6)
        def attempt(_):
            barrier.wait(timeout=15)
            return self.login(password='wrong-password')
        with self.assertLogs('school.security',level=logging.INFO) as captured:
            with ThreadPoolExecutor(max_workers=6) as workers:
                responses=list(workers.map(attempt,range(6)))
        self.assertEqual(sorted(r.status_code for r in responses),[401]*5+[429])
        self.assertEqual(next(r for r in responses if r.status_code==429).headers['retry-after'],'900')
        logs=' '.join(captured.output)
        self.assertNotIn('security-teacher',logs); self.assertNotIn('wrong-password',logs); self.assertNotIn('testclient',logs)
        admin=self.tokens('security-admin')
        monitor=self.client.get('/auth/monitoring',headers=self.headers(admin)).json()
        self.assertEqual(monitor['failed'],5); self.assertEqual(monitor['succeeded'],1)
        with self.Session() as db:
            row=db.query(LoginAttempt).first()
            self.assertEqual(len(row.account_key),64); self.assertEqual(len(row.client_key),64)
            self.assertNotIn('security',row.account_key)

    def test_client_limit_covers_distributed_usernames(self):
        with patch('app.core.auth.authenticate_user',return_value=None):
            for index in range(30):
                self.assertEqual(self.login(f'unknown-{index}').status_code,401)
            self.assertEqual(self.login('another-unknown').status_code,429)

    def test_all_business_routes_have_explicit_permissions(self):
        # New public business routes must be an explicit security decision.
        app.openapi()
        public={'/health','/ready','/auth/token','/auth/signup','/auth/refresh','/auth/logout-refresh'}
        def dependencies(node):
            return {getattr(child.call,'__name__','') for child in node.dependencies} | set().union(*(dependencies(child) for child in node.dependencies),set())
        def flatten(routes, prefix=""):
            for route in routes:
                if isinstance(route, APIRoute):
                    yield prefix + route.path, route
                elif hasattr(route, "original_router"):
                    yield from flatten(route.original_router.routes, prefix + route.include_context.prefix)
        routes=list(flatten(app.routes))
        if not routes:
            self.fail('No routes were audited')
        secured=0
        for path, route in routes:
            if path in public: continue
            names=dependencies(route.dependant)
            self.assertIn('get_current_user',names,path)
            if path.startswith(('/fees','/reports','/admin','/auth/accounts','/auth/monitoring')):
                self.assertIn('admin_only',names,path)
            if path=='/marks/submit': self.assertIn('teacher_only',names)
            secured+=1
        self.assertGreater(secured,20)
        teacher=self.tokens()
        for path in ('/fees','/reports/dashboard','/admin/dashboard','/auth/accounts','/auth/monitoring'):
            self.assertEqual(self.client.get(path,headers=self.headers(teacher)).status_code,403,path)
        self.assertEqual(self.client.post('/marks/submit',headers=self.headers(self.tokens('security-admin'))).status_code,403)

    def test_cors_exact_local_web_and_android_origins(self):
        for origin in ('http://localhost:3000','http://127.0.0.1:3000','https://localhost'):
            result=self.client.options('/learners',headers={'Origin':origin,'Access-Control-Request-Method':'GET','Access-Control-Request-Headers':'Authorization'})
            self.assertEqual(result.status_code,200)
            self.assertEqual(result.headers['access-control-allow-origin'],origin)
            self.assertNotIn('access-control-allow-credentials',result.headers)
        for origin in ('https://evil.example','null','https://localhost.evil.example'):
            result=self.client.options('/learners',headers={'Origin':origin,'Access-Control-Request-Method':'GET'})
            self.assertEqual(result.status_code,400)
            self.assertNotIn('access-control-allow-origin',result.headers)

    def test_health_and_readiness_fail_closed(self):
        self.assertEqual(self.client.get('/health').json(),{'status':'ok'})
        self.assertEqual(self.client.get('/ready').status_code,503)  # no migration metadata
        with self.engine.begin() as c:
            c.exec_driver_sql('CREATE TABLE IF NOT EXISTS alembic_version (version_num VARCHAR(32) NOT NULL)')
            c.exec_driver_sql('DELETE FROM alembic_version')
            c.exec_driver_sql("INSERT INTO alembic_version VALUES ('0005_security')")
        with patch('app.main.backup_is_current',return_value=False):
            self.assertEqual(self.client.get('/ready').status_code,503)
        with patch('app.main.backup_is_current',return_value=True):
            self.assertEqual(self.client.get('/ready').json(),{'status':'ready'})
        with self.engine.begin() as c: c.exec_driver_sql('DROP TABLE alembic_version')

    def test_unexpected_errors_do_not_log_personal_data(self):
        def failing_db():
            raise RuntimeError('PRIVATE_NAME password=PRIVATE_PASSWORD token=PRIVATE_TOKEN')
            yield
        original=app.dependency_overrides[get_db]
        app.dependency_overrides[get_db]=failing_db
        try:
            with self.assertLogs('school.security',level=logging.ERROR) as logs:
                response=self.client.get('/learners',headers=self.headers({'access_token':'invalid'}))
            self.assertEqual(response.status_code,500)
            self.assertEqual(response.json(),{'detail':'Internal server error'})
            self.assertNotIn('PRIVATE_',str(logs.output))
            self.assertFalse(logging.getLogger('uvicorn.access').isEnabledFor(logging.INFO))
        finally: app.dependency_overrides[get_db]=original

    def test_fee_pdf_is_streamed_without_persistent_files(self):
        admin=self.tokens('security-admin'); headers=self.headers(admin)
        headers['Idempotency-Key']='private-pdf-learner'
        learner=self.client.post('/learners',headers=headers,json={'name':'Private PDF Learner','class_name':'7'})
        self.assertEqual(learner.status_code,201,learner.text)
        headers['Idempotency-Key']='private-pdf-fee'
        fee=self.client.post('/fees',headers=headers,json={'learner_id':learner.json()['id'],'grade':'7','academic_year':2026,'term':3,'school_required':1000})
        self.assertEqual(fee.status_code,200,fee.text)
        before=set(Path.cwd().glob('*.pdf'))
        pdf=self.client.get(f"/fees/records/{fee.json()['id']}/statement.pdf",headers=headers)
        self.assertEqual(pdf.status_code,200,pdf.text[:50])
        self.assertTrue(pdf.content.startswith(b'%PDF'))
        self.assertNotIn('content-length',pdf.headers)
        self.assertIn('no-store',pdf.headers['cache-control'])
        self.assertNotIn('Private PDF Learner',pdf.headers['content-disposition'])
        self.assertEqual(set(Path.cwd().glob('*.pdf')),before)

    def test_password_hashes_are_argon2_and_invalid_hashes_fail(self):
        encoded=hash_password('testing-password')
        self.assertTrue(encoded.startswith('$argon2id$'))
        self.assertTrue(verify_password('testing-password',encoded))
        for bad in (None,'','malformed','$argon2id$invalid'):
            self.assertFalse(verify_password('testing-password',bad))
        self.assertFalse(verify_password('wrong',encoded))

class ConfigurationTests(unittest.TestCase):
    def test_startup_refuses_missing_default_weak_secrets_and_invalid_origins(self):
        with TemporaryDirectory() as directory:
            envfile=Path(directory)/'.env'; envfile.write_text('')
            base={**os.environ,'APP_ENV_FILE':str(envfile)}
            for environment in ('DEV','PROD'):
                for secret in ('','replace-with-a-long-random-secret','development-only-secret-change-before-production','x'*64):
                    result=subprocess.run([sys.executable,'-c','import app.main'],cwd=ROOT,
                        env={**base,'ENV':environment,'JWT_SECRET_KEY':secret},capture_output=True,text=True)
                    self.assertNotEqual(result.returncode,0,(environment,secret))
                    self.assertIn('Configure JWT_SECRET_KEY',result.stderr)
            for origin in ('*','null','https://school.example/path','https://*.school.example'):
                result=subprocess.run([sys.executable,'-c','import app.main'],cwd=ROOT,
                    env={**base,'JWT_SECRET_KEY':secrets.token_urlsafe(48),'CORS_ORIGINS':origin},capture_output=True,text=True)
                self.assertNotEqual(result.returncode,0,origin)
                self.assertIn('CORS_ORIGINS',result.stderr)

class BackupTests(unittest.TestCase):
    def test_encrypted_backup_restore_corruption_and_freshness(self):
        with TemporaryDirectory() as directory:
            root=Path(directory); source=root/'source.db'; target=root/'private-backups'
            with closing(sqlite3.connect(source)) as c:
                c.execute('CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT, token_version INTEGER NOT NULL DEFAULT 0)')
                c.execute('CREATE TABLE auth_sessions (id TEXT PRIMARY KEY, user_id INTEGER REFERENCES users(id), revoked_at INTEGER)')
                c.execute('CREATE TABLE refresh_tokens (digest TEXT PRIMARY KEY, session_id TEXT REFERENCES auth_sessions(id), consumed_at INTEGER)')
                c.execute("INSERT INTO users VALUES (1,'PRIVATE_LEARNER_NAME',0)")
                c.execute("INSERT INTO auth_sessions VALUES ('session',1,NULL)")
                c.execute("INSERT INTO refresh_tokens VALUES ('digest','session',NULL)"); c.commit()
            engine=create_engine('sqlite:///'+source.as_posix())
            with patch.object(backups,'engine',engine),patch.object(backups,'BACKUP_DIRECTORY',target),patch.dict(os.environ,{'BACKUP_ENCRYPTION_KEY':Fernet.generate_key().decode()}):
                result=backups.backup(); encrypted=target/result['file']
                self.assertTrue(result['restore_verified']); self.assertTrue(backups.backup_is_current())
                self.assertNotIn(b'PRIVATE_LEARNER_NAME',encrypted.read_bytes())
                restored=root/'restored.db'
                self.assertEqual(backups.restore_file(encrypted,restored),{'users':1,'auth_sessions':1,'refresh_tokens':1})
                with closing(sqlite3.connect(restored)) as c:
                    self.assertEqual(c.execute('SELECT name FROM users').fetchone()[0],'PRIVATE_LEARNER_NAME')
                    self.assertEqual(c.execute('SELECT token_version FROM users').fetchone()[0],1)
                    self.assertIsNotNone(c.execute('SELECT revoked_at FROM auth_sessions').fetchone()[0])
                    self.assertIsNotNone(c.execute('SELECT consumed_at FROM refresh_tokens').fetchone()[0])
                with self.assertRaises(RuntimeError): backups.restore_file(encrypted,restored)
                with patch.dict(os.environ,{'BACKUP_ENCRYPTION_KEY':Fernet.generate_key().decode()}):
                    with self.assertRaises(InvalidToken): backups.restore_file(encrypted,root/'wrong-key.db')
                encrypted.write_bytes(b'corrupt')
                self.assertFalse(backups.backup_is_current())
                with self.assertRaises(InvalidToken): backups.restore_file(encrypted,root/'corrupt.db')
                result['created_at']=now()-37*3600
                (target/'latest.json').write_text(json.dumps(result))
                self.assertFalse(backups.backup_is_current())
            engine.dispose()

class BackupScheduleTests(unittest.IsolatedAsyncioTestCase):
    async def test_scheduler_runs_backup_and_retries_after_failures(self):
        from app.core.operations import maintain_backups
        with patch('app.core.operations.backup_is_current',return_value=False),patch('app.core.operations.backup') as run,patch('app.core.operations.asyncio.sleep',side_effect=asyncio.CancelledError):
            with self.assertRaises(asyncio.CancelledError): await maintain_backups()
            run.assert_called_once()
        with patch('app.core.operations.backup_is_current',return_value=False),patch('app.core.operations.backup',side_effect=RuntimeError('private failure')),patch('app.core.operations.asyncio.sleep',side_effect=asyncio.CancelledError) as delay:
            with self.assertLogs('school.security',level=logging.ERROR) as logs:
                with self.assertRaises(asyncio.CancelledError): await maintain_backups()
            self.assertNotIn('private failure',str(logs.output)); delay.assert_called_once_with(1800)

if __name__=='__main__': unittest.main()
