import tempfile
import unittest

from tests.auth_helpers import login_admin
from pathlib import Path

from app import create_app


class ManagedDataTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.config = {"TESTING": True, "DATABASE": Path(self.temp.name) / "test.sqlite3"}
        self.client = login_admin(create_app(self.config).test_client())

    def test_four_artworks_with_requested_fields(self):
        artworks = self.client.get("/api/artworks").json["artworks"]
        self.assertEqual([art["artwork_index"] for art in artworks], [1, 2, 3, 4])
        self.assertEqual(set(artworks[0]), {"artwork_index", "artist_name", "theme", "title", "description",
            "artwork_code", "title_en", "artist_name_en", "year", "medium", "curator_notes", "image_path", "image_alt", "artwork_id", "location", "x", "y"})
        self.assertEqual(self.client.get("/api/artworks/999").status_code, 404)
        self.assertEqual(self.client.post("/api/artworks", json={}).status_code, 405)

    def test_artwork_edit_survives_restart_and_escapes_html(self):
        body = {"artist_name": "새 작가", "theme": '새 테마 " &', "title": '<img src=x onerror="alert(1)">',
                "description": "바뀐 설명\n두 번째 줄"}
        original = self.client.get("/api/artworks/2").json
        result = self.client.patch("/api/artworks/2", json=body)
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.json, {**original, **body})
        restarted = login_admin(create_app(self.config).test_client())
        self.assertEqual(restarted.get("/api/artworks/2").json, result.json)
        self.assertEqual(restarted.get("/api/catalog").json["artworks"][1], result.json)
        page = restarted.get("/data").get_data(as_text=True)
        self.assertNotIn(body["title"], page)
        self.assertIn("&lt;img", page)

    def test_invalid_artwork_edit_does_not_change_saved_data(self):
        original = self.client.get("/api/artworks/1").json
        for body in ({}, {"title": "   "}, {"description": None}, {"artwork_index": 2},
                     {"artist_name": "가" * 201}, {"title": ["제목"]}):
            with self.subTest(body=body):
                self.assertEqual(self.client.patch("/api/artworks/1", json=body).status_code, 400)
                self.assertEqual(self.client.get("/api/artworks/1").json, original)
        long_description = "작품🌱" * 2500
        self.assertEqual(self.client.patch("/api/artworks/1", json={"description": long_description}).status_code, 200)

    def test_robot_pose_upsert_filter_and_restart(self):
        initial = self.client.get("/api/robots").json["robots"]
        self.assertEqual(len(initial), 1)
        self.assertIsNone(initial[0]["pose"])
        self.assertIsNone(initial[0]["pose_updated_at"])
        for robot_id, active in (("robot-01", True), ("robot-02", False)):
            result = self.client.put(f"/api/robots/{robot_id}", json={
                "active": active, "pose": {"x": 1.2, "y": -0.5, "theta": 1.57}, "frame_id": "map",
            })
            self.assertEqual(result.status_code, 200)
            self.assertEqual(result.json["active"], active)
            self.assertIsInstance(result.json["pose_updated_at"], int)
        self.assertEqual([r["robot_id"] for r in self.client.get("/api/robots").json["robots"]], ["robot-01"])
        self.assertEqual([r["robot_id"] for r in self.client.get("/api/robots?active=false").json["robots"]], ["robot-02"])
        restarted = login_admin(create_app(self.config).test_client())
        robots = restarted.get("/api/robots?active=all").json["robots"]
        self.assertEqual(len(robots), 2)
        self.assertEqual(robots[0]["pose"], {"x": 1.2, "y": -0.5, "theta": 1.57})
        self.assertEqual(restarted.put("/api/robots/robot-01", json={"active": False, "pose": None}).status_code, 200)
        self.assertEqual(restarted.get("/api/robots").json["robots"], [])
        self.assertIsNone(restarted.get("/api/robots/robot-01").json["pose_updated_at"])

    def test_bad_robot_poses_do_not_overwrite_latest(self):
        url = "/api/robots/robot-01"
        original = self.client.put(url, json={"active": True, "pose": {"x": 1, "y": 2, "theta": 0}}).json
        for pose in ({"x": 0, "y": 0}, {"x": True, "y": 0, "theta": 0},
                     {"x": "0", "y": 0, "theta": 0}, {"x": float("nan"), "y": 0, "theta": 0},
                     {"x": float("inf"), "y": 0, "theta": 0}, {"x": 10**1000, "y": 0, "theta": 0},
                     {"x": 0, "y": 0, "theta": 0, "z": 1}, []):
            self.assertEqual(self.client.put(url, json={"active": True, "pose": pose}).status_code, 400)
        self.assertEqual(self.client.put(url, json={"active": 1, "pose": None}).status_code, 400)
        self.assertEqual(self.client.put(url, json={"active": True}).status_code, 400)
        self.assertEqual(self.client.put(url, json={"active": True, "pose": None, "frame_id": ""}).status_code, 400)
        self.assertEqual(self.client.get(url).json, original)
        self.assertEqual(self.client.get("/api/robots?active=yes").status_code, 400)
        self.assertEqual(self.client.get("/api/robots/missing").status_code, 404)


if __name__ == "__main__":
    unittest.main()
