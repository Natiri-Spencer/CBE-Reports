import os as _os
import secrets as _secrets
_os.environ.setdefault("JWT_SECRET_KEY", _secrets.token_urlsafe(48))
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.frontend import mount_frontend


class FrontendHostingTests(unittest.TestCase):
    def test_vite_assets_and_react_deep_links(self):
        with TemporaryDirectory() as directory:
            build = Path(directory)
            (build / "assets").mkdir()
            (build / "assets" / "app.js").write_text("console.log('app')", encoding="utf-8")
            (build / "index.html").write_text("<html>School app</html>", encoding="utf-8")
            (build / "favicon.ico").write_bytes(b"icon")
            app = FastAPI()
            mount_frontend(app, build)
            with TestClient(app) as client:
                for route in ["/", "/login", "/teacher/marks", "/admin", "/admin/finance"]:
                    response = client.get(route)
                    self.assertEqual(response.status_code, 200, route)
                    self.assertIn("School app", response.text)
                self.assertIn("console.log", client.get("/assets/app.js").text)
                self.assertEqual(client.get("/favicon.ico").content, b"icon")
                for route in ["/fees/missing", "/admin/missing", "/assets/missing.js", "/missing.js", "/%2e%2e/private.txt"]:
                    self.assertEqual(client.get(route).status_code, 404, route)
