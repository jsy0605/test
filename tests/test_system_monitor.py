import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from app import create_app
from system_monitor import SystemMonitor
from tests.auth_helpers import login_admin


class SystemMonitorTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.config = {"TESTING": True, "DATABASE": Path(self.temp.name) / "test.sqlite3"}

    def test_page_and_api_require_admin_before_collecting_metrics(self):
        monitor = Mock()
        app = create_app({**self.config, "SYSTEM_MONITOR": monitor})
        client = app.test_client()
        self.assertEqual(client.get("/sysmon").headers["Location"], "/login")
        self.assertEqual(client.get("/api/system/metrics").status_code, 401)
        monitor.snapshot.assert_not_called()
        login_admin(client)
        response = client.get("/sysmon")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["Cache-Control"], "no-store")
        self.assertIn('src="/static/js/system-monitor.js"', response.get_data(as_text=True))
        self.assertIn('/sysmon', client.get('/data').get_data(as_text=True))

    def test_actual_metrics_are_valid_and_fresh(self):
        app = create_app(self.config)
        client = login_admin(app.test_client())
        first = client.get("/api/system/metrics")
        second = client.get("/api/system/metrics")
        self.assertEqual(first.status_code, 200)
        self.assertEqual(first.headers["Cache-Control"], "no-store")
        data = first.json
        for metric in ("cpu", "memory", "disk"):
            self.assertGreaterEqual(data[metric]["percent"], 0)
            self.assertLessEqual(data[metric]["percent"], 100)
        for metric in ("memory", "disk"):
            self.assertGreater(data[metric]["total_bytes"], 0)
        self.assertEqual(data["memory"]["used_bytes"], data["memory"]["total_bytes"] - data["memory"]["available_bytes"])
        self.assertEqual(data["disk"]["path"], self.temp.name)
        self.assertGreater(second.json["sampled_at"], data["sampled_at"])
        self.assertGreaterEqual(second.json["server"]["uptime_seconds"], data["server"]["uptime_seconds"])
        self.assertEqual(data["refresh_interval_ms"], 2000)
        self.assertTrue(data["host"]["name"])

    def test_cpu_uses_measured_interval_and_ram_uses_available_capacity(self):
        clock, wall = [100], [1000]
        monitor = SystemMonitor(self.temp.name, clock=lambda: clock[0], wall_clock=lambda: wall[0])
        with (patch("system_monitor.psutil.cpu_percent", return_value=34.5) as cpu,
              patch("system_monitor.psutil.virtual_memory", return_value=SimpleNamespace(total=1000, available=400, percent=60, used=200)),
              patch("system_monitor.psutil.disk_usage", return_value=SimpleNamespace(total=2000, used=500, free=1500, percent=25)) as disk,
              patch("system_monitor.psutil.cpu_count", return_value=4),
              patch("system_monitor.psutil.boot_time", return_value=200)):
            clock[0] = 112
            wall[0] = 1012
            data = monitor.snapshot()
            cpu.assert_called_once_with(interval=0.1)
            disk.assert_called_once_with(self.temp.name)
            self.assertEqual(data["cpu"]["percent"], 34.5)
            self.assertEqual(data["memory"]["used_bytes"], 600)
            self.assertEqual(data["server"]["uptime_seconds"], 12)
            self.assertEqual(data["host"]["uptime_seconds"], 812)
            # 서버 실행 시간은 시스템 시각이 뒤로 바뀌어도 단조 시계를 사용합니다.
            wall[0] = 900
            clock[0] = 114
            self.assertEqual(monitor.snapshot()["server"]["uptime_seconds"], 14)

    def test_collection_failure_is_not_reported_as_zero_usage(self):
        monitor = Mock()
        monitor.snapshot.side_effect = PermissionError("test-only failure")
        app = create_app({**self.config, "SYSTEM_MONITOR": monitor})
        client = login_admin(app.test_client())
        with self.assertLogs(app.logger, level="ERROR"):
            response = client.get("/api/system/metrics")
        self.assertEqual(response.status_code, 503)
        self.assertIn("error", response.json)
        self.assertNotIn("cpu", response.json)

    def test_logout_revokes_metrics_access_and_kiosk_remains_public(self):
        client = login_admin(create_app(self.config).test_client())
        self.assertEqual(client.get("/api/system/metrics").status_code, 200)
        self.assertEqual(client.post("/logout").status_code, 303)
        self.assertEqual(client.get("/api/system/metrics").status_code, 401)
        self.assertEqual(client.get("/sysmon").status_code, 302)
        response = client.get("/")
        self.assertEqual(response.status_code, 200)
        response.close()
