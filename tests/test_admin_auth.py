import sqlite3
import tempfile
import unittest
from datetime import timedelta
from pathlib import Path

from werkzeug.security import check_password_hash

from app import create_app
from tests.auth_helpers import TEST_PASSWORD, login_admin


class AdminAuthTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.config = {"TESTING": True, "DATABASE": Path(self.temp.name) / "auth.sqlite3",
                       "ROS_PREPARATION_REQUIRED": False}
        self.app = create_app(self.config)
        self.client = self.app.test_client()

    def token(self, client=None):
        return (client or self.client).get("/api/auth/status").json["csrf_token"]

    def login(self, password=TEST_PASSWORD, username="testadmin"):
        return self.client.post("/login", data={"username": username, "password": password,
                                                "csrf_token": self.token()})

    def test_public_kiosk_still_works_and_management_requires_login(self):
        for path in ("/", "/api/catalog", "/api/artworks", "/api/robots", "/api/health"):
            response = self.client.get(path)
            self.assertEqual(response.status_code, 200, path)
            response.close()
        self.assertEqual(self.client.get("/data").headers["Location"], "/login")
        for path in ("/api/ros/config", "/api/sessions"):
            self.assertEqual(self.client.get(path).status_code, 401)
        created = self.client.post("/api/sessions", json={"mode": "free", "artworkIds": ["art-01"]})
        self.assertEqual(created.status_code, 201)
        url = created.headers["Location"]
        self.assertEqual(self.client.get(url).status_code, 200)
        self.assertEqual(self.client.patch(url, json={"status": "active"}).status_code, 200)

    def test_direct_api_writes_are_rejected_without_login(self):
        original = self.client.get("/api/artworks/1").json
        self.assertEqual(self.client.patch("/api/artworks/1", json={"title": "forbidden"}).status_code, 401)
        self.assertEqual(self.client.put("/api/robots/robot-01", json={"active": False, "pose": None}).status_code, 401)
        self.assertEqual(self.client.post("/api/dev/availability", json={"action": "toggle"}).status_code, 401)
        self.assertEqual(self.client.get("/api/artworks/1").json, original)

    def test_first_account_is_local_only_and_cannot_be_overwritten(self):
        self.assertEqual(self.client.get("/login").headers["Location"], "/admin/setup")
        self.assertEqual(self.client.get("/admin/setup", environ_overrides={"REMOTE_ADDR": "192.0.2.4"}).status_code, 403)
        bad = self.client.post("/admin/setup", data={"username": "testadmin", "password": TEST_PASSWORD})
        self.assertEqual(bad.status_code, 403)
        for body in ({"username": "a", "password": TEST_PASSWORD, "password_confirm": TEST_PASSWORD},
                     {"username": "admin", "password": "short", "password_confirm": "short"},
                     {"username": "admin", "password": TEST_PASSWORD, "password_confirm": "different"}):
            response = self.client.post("/admin/setup", data={**body, "csrf_token": self.token()})
            self.assertEqual(response.status_code, 400)
        login_admin(self.client)
        response = self.client.post("/admin/setup", data={"username": "attacker", "password": "changed-password"})
        self.assertEqual(response.status_code, 302)
        with sqlite3.connect(self.config["DATABASE"]) as db:
            username, password_hash = db.execute("SELECT username, password_hash FROM admin_users").fetchone()
            self.assertEqual(username, "testadmin")
            self.assertNotEqual(password_hash, TEST_PASSWORD)
            self.assertTrue(check_password_hash(password_hash, TEST_PASSWORD))
            self.assertEqual(db.execute("SELECT COUNT(*) FROM admin_users").fetchone()[0], 1)

    def test_login_logout_and_csrf_protected_edit(self):
        login_admin(self.client)
        self.assertEqual(self.client.get("/data").status_code, 200)
        self.client.environ_base.pop("HTTP_X_CSRF_TOKEN")
        self.assertEqual(self.client.patch("/api/artworks/1", json={"title": "changed"}).status_code, 403)
        self.assertEqual(self.client.patch("/api/artworks/1", json={"title": "changed"},
                                          headers={"X-CSRF-Token": "wrong"}).status_code, 403)
        self.assertEqual(self.client.patch("/api/artworks/1", json={"title": "changed"},
                                          headers={"X-CSRF-Token": "잘못된토큰"}).status_code, 403)
        token = self.token()
        old_cookie = self.client.get_cookie("arti_admin_session").value
        result = self.client.patch("/api/artworks/1", json={"title": "changed"}, headers={"X-CSRF-Token": token})
        self.assertEqual(result.status_code, 200)
        self.assertEqual(self.client.post("/logout").status_code, 403)
        self.assertEqual(self.client.get("/logout").status_code, 405)
        self.assertEqual(self.client.post("/logout", data={"csrf_token": token}).status_code, 303)
        self.assertFalse(self.client.get("/api/auth/status").json["authenticated"])
        replay = self.app.test_client()
        replay.set_cookie("arti_admin_session", old_cookie)
        self.assertEqual(replay.get("/api/sessions").status_code, 401)
        self.assertEqual(self.client.get("/api/sessions").status_code, 401)
        self.assertEqual(self.login(password="incorrect-password").status_code, 401)
        result = self.login()
        self.assertEqual(result.status_code, 303)
        self.assertNotEqual(self.token(), token)
        self.assertIn("HttpOnly", result.headers["Set-Cookie"])
        self.assertIn("SameSite=Lax", result.headers["Set-Cookie"])

    def test_session_survives_restart_but_tampering_and_expiry_fail(self):
        login_admin(self.client)
        cookie = self.client.get_cookie("arti_admin_session").value
        restarted_app = create_app(self.config)
        restarted = restarted_app.test_client()
        restarted.set_cookie("arti_admin_session", cookie)
        self.assertEqual(restarted.get("/data").status_code, 200)
        restarted.set_cookie("arti_admin_session", cookie + "tampered")
        self.assertEqual(restarted.get("/api/sessions").status_code, 401)
        restarted.set_cookie("arti_admin_session", cookie)
        restarted_app.config["PERMANENT_SESSION_LIFETIME"] = timedelta(seconds=-1)
        self.assertEqual(restarted.get("/api/sessions").status_code, 401)
        self.assertEqual((Path(self.temp.name) / ".session-secret.key").stat().st_mode & 0o777, 0o600)

    def test_failed_login_is_throttled_and_recovers_after_window(self):
        login_admin(self.client)
        self.client = self.app.test_client()
        for index in range(5):
            self.assertEqual(self.login(password="incorrect-password").status_code, 401, index)
        self.assertEqual(self.login().status_code, 429)
        with sqlite3.connect(self.config["DATABASE"]) as db:
            db.execute("UPDATE admin_login_attempts SET blocked_until=0, window_started=0")
        self.assertEqual(self.login().status_code, 303)

    def test_cli_password_reset_revokes_existing_sessions(self):
        login_admin(self.client)
        result = self.app.test_cli_runner().invoke(args=["set-admin"],
            input="testadmin\nA-different-password42\nA-different-password42\n")
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertNotIn("A-different-password42", result.output)
        self.assertEqual(self.client.get("/api/sessions").status_code, 401)
        self.assertEqual(self.login().status_code, 401)
        self.assertEqual(self.login(password="A-different-password42").status_code, 303)

    def test_open_redirect_and_cross_origin_login_are_rejected(self):
        self.assertEqual(self.client.get("/admin/setup", headers={"Host": "attacker.example"}).status_code, 400)
        login_admin(self.client)
        self.client = self.app.test_client()
        token = self.token()
        form = {"username": "testadmin", "password": TEST_PASSWORD, "csrf_token": token}
        result = self.client.post("/login", data=form, headers={"Origin": "https://example.com"})
        self.assertEqual(result.status_code, 403)
        result = self.client.post("/login?next=https://example.com", data=form)
        self.assertEqual(result.headers["Location"], "/data")
        self.assertEqual(self.client.get("/data").headers["Cache-Control"], "no-store")

    def test_machine_token_only_allows_robot_pose_ingestion(self):
        self.app.config["ROBOT_API_TOKEN"] = "test-only-machine-token"
        headers = {"Authorization": "Bearer test-only-machine-token"}
        response = self.client.put("/api/robots/robot-01", headers=headers, json={
            "active": True, "pose": {"x": 1, "y": 2, "theta": 0},
        })
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.client.get("/api/sessions", headers=headers).status_code, 401)
        self.assertEqual(self.client.patch("/api/artworks/1", headers=headers, json={"title": "no"}).status_code, 401)
        self.assertEqual(self.client.put("/api/robots/robot-01", headers={"Authorization": "Bearer wrong"},
                                         json={"active": False, "pose": None}).status_code, 401)
        self.assertEqual(self.client.put("/api/robots/robot-01", headers={"Authorization": "Bearer 틀린토큰"},
                                         json={"active": False, "pose": None}).status_code, 401)
