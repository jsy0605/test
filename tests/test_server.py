import sqlite3
import tempfile
import unittest

from tests.auth_helpers import login_admin
from pathlib import Path

from app import create_app


class ServerTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.config = {"TESTING": True, "DATABASE": Path(self.temp.name) / "test.sqlite3", "ROS_PREPARATION_REQUIRED": False}
        self.client = login_admin(create_app(self.config).test_client())
        self.course = self.client.get("/api/catalog").json["courses"][0]

    def create_session(self):
        response = self.client.post("/api/sessions", json={
            "mode": "course", "courseId": self.course["id"], "artworkIds": self.course["ids"],
        })
        self.assertEqual(response.status_code, 201)
        return response.json, response.headers["Location"]

    def test_pages_and_catalog(self):
        for path in ("/", "/data", "/static/js/app.js", "/static/css/data.css", "/static/art/hero.svg"):
            with self.subTest(path=path):
                response = self.client.get(path)
                self.assertEqual(response.status_code, 200)
                response.close()
        self.assertEqual(self.client.get("/api/health").json["database"], "sqlite")
        self.assertEqual(len(self.client.get("/api/catalog").json["artworks"]), 4)
        self.assertEqual(self.client.get("/instance/arti.sqlite3").status_code, 404)

    def test_tour_persists_across_app_restart(self):
        session, url = self.create_session()
        started = self.client.patch(url, json={"status": "active"})
        self.assertEqual(started.status_code, 200)
        self.assertIsInstance(started.json["startedAt"], int)
        visited = self.course["ids"][:2]
        self.assertEqual(self.client.patch(url, json={"visitedIds": visited}).status_code, 200)
        completed = self.client.patch(url, json={"status": "completed", "visitedIds": visited})
        self.assertEqual(completed.status_code, 200)
        self.assertGreaterEqual(completed.json["endedAt"], completed.json["startedAt"])
        restarted = login_admin(create_app(self.config).test_client())
        self.assertEqual(restarted.get(url).json, completed.json)
        self.assertEqual(len(restarted.get("/api/sessions").json["sessions"]), 1)
        with sqlite3.connect(self.config["DATABASE"]) as db:
            self.assertEqual(db.execute("SELECT status FROM TourSession").fetchone()[0], "completed")

    def test_four_artworks_and_legacy_migration(self):
        import json

        session, url = self.create_session()
        # 이전 JSON 구조 DB를 재현하고, 관람 기록 보존도 함께 확인합니다.
        with sqlite3.connect(self.config["DATABASE"]) as db:
            db.execute("ALTER TABLE Art RENAME TO test_modern_artworks")
            db.execute("CREATE TABLE artworks (id TEXT PRIMARY KEY, data TEXT NOT NULL)")
            for index in range(1, 6):
                artwork_id = f"art-{index:02d}"
                db.execute("INSERT INTO artworks VALUES (?, ?)",
                           (artwork_id, json.dumps({"id": artwork_id, "title": "이전 예시 작품"})))
            db.execute("UPDATE courses SET data=? WHERE id='B'", (
                json.dumps({"id": "B", "ids": ["art-04", "art-05", "art-02", "art-03"]}),))
        restarted = login_admin(create_app(self.config).test_client())
        catalog = restarted.get("/api/catalog").json
        self.assertEqual([art["artwork_index"] for art in catalog["artworks"]], [1, 2, 3, 4])
        with sqlite3.connect(self.config["DATABASE"]) as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM artworks_legacy_v1").fetchone()[0], 5)
        self.assertEqual(catalog["courses"][0]["ids"], ["art-01", "art-02", "art-03"])
        self.assertEqual(catalog["courses"][1]["ids"], ["art-03", "art-02", "art-01"])
        self.assertEqual(restarted.get(url).json, session)
        for course in catalog["courses"]:
            result = restarted.post("/api/sessions", json={
                "mode": "course", "courseId": course["id"], "artworkIds": course["ids"],
            })
            self.assertEqual(result.status_code, 201)

        # 다음 실행 때는 기존 데이터를 다시 덮어쓰지 않습니다.
        with sqlite3.connect(self.config["DATABASE"]) as db:
            art = catalog["artworks"][0]
            art["title"] = "수정한 제목"
            db.execute("UPDATE Art SET title=? WHERE artwork_index=?", (art["title"], art["artwork_index"]))
        twice = create_app(self.config).test_client()
        self.assertEqual(twice.get("/api/catalog").json["artworks"][0]["title"], "수정한 제목")

    def test_cancel_and_terminal_state(self):
        session, url = self.create_session()
        result = self.client.patch(url, json={"status": "cancelled"})
        self.assertEqual(result.status_code, 200)
        self.assertIsNone(result.json["startedAt"])
        self.assertIsNotNone(result.json["endedAt"])
        self.assertEqual(self.client.patch(url, json={"status": "active"}).status_code, 409)
        self.assertEqual(self.client.patch(url, json={"status": "cancelled"}).json, result.json)

    def test_invalid_creation_does_not_write(self):
        cases = [
            {}, {"mode": "wrong"}, {"mode": [], "artworkIds": []},
            {"mode": "course", "courseId": "A", "artworkIds": ["missing"]},
            {"mode": "course", "courseId": "A", "artworkIds": ["art-01"]},
            {"mode": "course", "courseId": [], "artworkIds": ["art-01"]},
            {"mode": "free", "artworkIds": ["art-01", "art-01"]},
            {"mode": "free", "artworkIds": [None]},
            {"mode": "free", "artworkIds": [], "extra": True},
            {"mode": "free", "artworkIds": ["art-01"], "courseId": "A"},
        ]
        for body in cases:
            with self.subTest(body=body):
                self.assertEqual(self.client.post("/api/sessions", json=body).status_code, 400)
        self.assertEqual(self.client.get("/api/sessions").json["sessions"], [])

    def test_invalid_updates_rollback(self):
        session, url = self.create_session()
        self.assertEqual(self.client.patch(url, json={"status": "completed"}).status_code, 409)
        self.assertEqual(self.client.patch(url, json={"status": []}).status_code, 409)
        self.assertEqual(self.client.patch(url, json={"visitedIds": ["art-01"]}).status_code, 409)
        self.assertEqual(self.client.get(url).json, session)
        self.client.patch(url, json={"status": "active", "visitedIds": ["art-01"]})
        self.assertEqual(self.client.patch(url, json={"visitedIds": []}).status_code, 409)
        self.assertEqual(self.client.patch(url, json={"visitedIds": ["art-04"]}).status_code, 400)
        self.assertEqual(self.client.get(url).json["visitedIds"], ["art-01"])

    def test_bad_requests_and_cross_site(self):
        self.assertEqual(self.client.post("/api/sessions", data="abc").status_code, 415)
        self.assertEqual(self.client.post("/api/sessions", data="{", content_type="application/json").status_code, 400)
        self.assertEqual(self.client.post("/api/sessions", json=[]).status_code, 400)
        self.assertEqual(self.client.post("/api/sessions", json={}, headers={"Origin": "https://example.com"}).status_code, 403)
        self.assertEqual(self.client.post("/api/sessions", json={}, headers={"Sec-Fetch-Site": "cross-site"}).status_code, 403)
        self.assertEqual(self.client.post("/api/sessions", data='"' + 'a' * 140000 + '"', content_type="application/json").status_code, 413)
        self.assertEqual(self.client.get("/api/sessions/missing").status_code, 404)
        for limit in ("0", "501", "abc", "9" * 5000):
            self.assertEqual(self.client.get("/api/sessions", query_string={"limit": limit}).status_code, 400)

    def test_free_and_custom_courses(self):
        for mode, course in (("free", None), ("course", "custom")):
            response = self.client.post("/api/sessions", json={
                "mode": mode, "courseId": course, "artworkIds": ["art-01"],
            })
            self.assertEqual(response.status_code, 201)
            self.assertTrue(response.json["simulation"])

    def test_checklist_tour_sorts_selection_without_creating_a_course(self):
        with sqlite3.connect(self.config['DATABASE']) as db:
            courses_before = db.execute('SELECT id,data FROM courses ORDER BY id').fetchall()
        response = self.client.post('/api/sessions', json={
            'mode': 'course', 'courseId': None, 'artworkIds': ['art-04', 'art-01', 'art-03'],
        })
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json['artworkIds'], ['art-01', 'art-03', 'art-04'])
        self.assertIsNone(response.json['courseId'])
        with sqlite3.connect(self.config['DATABASE']) as db:
            self.assertEqual(db.execute('SELECT id,data FROM courses ORDER BY id').fetchall(), courses_before)
            self.assertEqual(db.execute('SELECT route,artwork_ids FROM TourSession').fetchone(),
                             (None, '["art-01", "art-03", "art-04"]'))
        for ids in ([], ['art-04', 'art-04'], ['art-05']):
            self.assertEqual(self.client.post('/api/sessions', json={
                'mode': 'course', 'artworkIds': ids,
            }).status_code, 400)

    def test_legacy_course_requests_also_store_clockwise_artwork_order(self):
        for course_id, ids in (('B', ['art-03', 'art-02', 'art-01']),
                               ('custom', ['art-04', 'art-02'])):
            with self.subTest(course_id=course_id):
                response = self.client.post('/api/sessions', json={
                    'mode': 'course', 'courseId': course_id, 'artworkIds': ids,
                })
                self.assertEqual(response.status_code, 201)
                expected = sorted(ids)
                self.assertEqual(response.json['artworkIds'], expected)
                self.assertEqual(self.client.get(response.headers['Location']).json['artworkIds'], expected)


if __name__ == "__main__":
    unittest.main()
