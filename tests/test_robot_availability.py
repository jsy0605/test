import json
import tempfile
import unittest

from tests.auth_helpers import login_admin
from pathlib import Path
from types import SimpleNamespace

from app import create_app
from robot_availability import RobotAvailability


class AvailabilityTest(unittest.TestCase):
    def test_dev_toggle_uses_topic_publication_and_can_stop(self):
        monitor = RobotAvailability()
        with self.assertRaises(RuntimeError):
            monitor.toggle_dev()
        monitor._ros_ready = True
        self.assertIs(monitor.toggle_dev(), True)
        self.assertIsNone(monitor.snapshot()["available"])
        messages = []
        publisher = SimpleNamespace(publish=messages.append)
        monitor.publish_dev(publisher, SimpleNamespace)
        self.assertIs(messages[-1].data, True)
        monitor.update(messages[-1].data)
        self.assertIs(monitor.snapshot()["available"], True)
        self.assertIs(monitor.toggle_dev(), False)
        monitor.publish_dev(publisher, SimpleNamespace)
        self.assertIs(messages[-1].data, False)
        monitor.stop_dev()
        monitor.publish_dev(publisher, SimpleNamespace)
        self.assertEqual(len(messages), 2)
        self.assertIsNone(monitor.snapshot()["dev_value"])

    def test_dev_endpoint_checks_local_request_and_action(self):
        with tempfile.TemporaryDirectory() as folder:
            monitor = RobotAvailability()
            app = create_app({"TESTING":True, "DATABASE":Path(folder)/"test.sqlite3", "AVAILABILITY_MONITOR":monitor})
            client = login_admin(app.test_client())
            url = "/api/dev/availability"
            self.assertEqual(client.post(url, json={"action":"toggle"}).status_code, 503)
            monitor._ros_ready = True
            self.assertIs(client.post(url, json={"action":"toggle"}).json["dev_value"], True)
            self.assertIs(client.post(url, json={"action":"toggle"}).json["dev_value"], False)
            self.assertIsNone(client.post(url, json={"action":"stop"}).json["dev_value"])
            for body in ({}, {"action":[]}, {"action":"unknown"}, {"action":"toggle","extra":True}):
                self.assertEqual(client.post(url, json=body).status_code, 400)
            self.assertEqual(client.post(url, json={"action":"toggle"}, environ_overrides={"REMOTE_ADDR":"192.0.2.1"}).status_code, 403)
            self.assertEqual(client.post(url, json={"action":"toggle"}, headers={"Origin":"https://example.com"}).status_code, 403)

    def test_bool_and_message_timeout(self):
        clock = [0]
        monitor = RobotAvailability(clock=lambda: clock[0])
        self.assertEqual(monitor.snapshot()["status"], "waiting")
        monitor.update(True)
        self.assertIs(monitor.snapshot()["available"], True)
        clock[0] = 1
        monitor.update(False)
        self.assertIs(monitor.snapshot()["available"], False)
        with self.assertRaises(ValueError):
            monitor.update("true")
        clock[0] = 5
        self.assertEqual(monitor.snapshot()["status"], "stale")
        self.assertIsNone(monitor.snapshot()["available"])
        monitor.update(True)
        self.assertIs(monitor.snapshot()["available"], True)

    def test_stream_sends_topic_state_without_robot_db_lookup(self):
        with tempfile.TemporaryDirectory() as folder:
            monitor = RobotAvailability()
            monitor.update(False)
            app = create_app({"TESTING":True, "DATABASE":Path(folder)/"test.sqlite3", "AVAILABILITY_MONITOR":monitor})
            response = app.test_client().get("/api/availability/stream", buffered=False)
            try:
                self.assertEqual(response.mimetype, "text/event-stream")
                frame = next(iter(response.response)).decode()
                self.assertIn("event: availability", frame)
                payload = json.loads(frame.split("data: ")[1])
                self.assertEqual(payload["topic"], "/is_available")
                self.assertIs(payload["available"], False)
            finally:
                response.close()
