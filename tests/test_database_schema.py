"""요청한 SQL 구조, 기존 DB 이전, 실제 API 쓰기의 통합 검증."""
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from app import ROOT, create_app
from database import initialize_database
from tests.auth_helpers import login_admin


class DatabaseSchemaTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'test.sqlite3'
        self.config = {'TESTING': True, 'DATABASE': self.path, 'ROS_PREPARATION_REQUIRED': False}

    def test_requested_tables_values_and_unknown_pose(self):
        client = create_app(self.config).test_client()
        with sqlite3.connect(self.path) as db:
            rows = db.execute('SELECT artwork_id, artwork_title, artist, location, theme, x, y FROM Art ORDER BY artwork_id').fetchall()
            self.assertEqual(rows, [
                ('001', 'artwork1', 'artist1', 'location1', 'theme1', 0, 1),
                ('002', 'artwork2', 'artist2', 'location2', 'theme2', 5, 6),
                ('003', 'artwork3', 'artist3', 'location3', 'theme3', 7, 1),
                ('004', 'artwork4', 'artist4', 'location4', 'theme4', None, None),
            ])
            self.assertEqual(db.execute('SELECT robot_id, x, y, theta FROM Pose ORDER BY robot_id').fetchall(),
                             [('robot-01', None, None, None), ('robot-02', None, None, None)])
            self.assertEqual(db.execute('SELECT COUNT(*) FROM Log').fetchone()[0], 0)
            self.assertEqual(db.execute('PRAGMA user_version').fetchone()[0], 6)
        self.assertEqual(len(client.get('/api/robots?active=all').json['robots']), 2)

    def test_management_and_tour_write_to_requested_columns(self):
        client = login_admin(create_app(self.config).test_client())
        body = {'title_en': 'Edited Title', 'artist_name_en': 'Edited Artist', 'location': '009', 'x': -2.5, 'y': 8}
        result = client.patch('/api/artworks/1', json=body)
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.json['artwork_id'], '001')
        pose = {'x': 0.5, 'y': 1, 'theta': -1.2}
        self.assertEqual(client.put('/api/robots/robot-02', json={'active': True, 'pose': pose}).status_code, 200)
        session = client.post('/api/sessions', json={'mode': 'course', 'courseId': 'A', 'artworkIds': ['art-01', 'art-02', 'art-03']}).json
        url = '/api/sessions/' + session['id']
        client.patch(url, json={'status': 'active'})
        completed = client.patch(url, json={'status': 'completed'}).json
        with sqlite3.connect(self.path) as db:
            self.assertEqual(db.execute("SELECT artwork_title, artist, location, x, y FROM Art WHERE artwork_id='001'").fetchone(),
                             ('Edited Title', 'Edited Artist', '009', -2.5, 8))
            self.assertEqual(db.execute("SELECT x,y,theta FROM Pose WHERE robot_id='robot-02'").fetchone(), (.5, 1, -1.2))
            self.assertEqual(db.execute('SELECT created_time, mode, route, status, end_time, record_id FROM TourSession').fetchone(),
                             (session['createdAt'], 'course', 'A', 'completed', completed['endedAt'], session['id']))
        restarted = create_app(self.config).test_client()
        self.assertEqual(restarted.get('/api/artworks/1').json, result.json)
        self.assertEqual(restarted.get(url).json, completed)

    def test_invalid_coordinates_or_fixed_id_do_not_overwrite(self):
        client = login_admin(create_app(self.config).test_client())
        original = client.get('/api/artworks/1').json
        for body in ({'x': True}, {'x': '2'}, {'y': float('nan')}, {'y': float('inf')}, {'x': 10**1000},
                     {'x': 1e13}, {'location': ''}, {'location': 'x'*65}, {'artwork_id': '005'}):
            with self.subTest(body=body):
                self.assertEqual(client.patch('/api/artworks/1', json=body).status_code, 400)
                self.assertEqual(client.get('/api/artworks/1').json, original)
        self.assertEqual(client.patch('/api/artworks/1', json={'x': None, 'y': None}).status_code, 200)

    def create_legacy_database(self, bad_pose=False):
        catalog = json.loads((ROOT / 'data/catalog.json').read_text())
        fields = [key for key in catalog['artworks'][0] if key not in {'artwork_id', 'location', 'x', 'y'}]
        with sqlite3.connect(self.path) as db:
            db.execute('CREATE TABLE artworks (' + ', '.join(key + (' INTEGER' if key in {'artwork_index', 'year'} else ' TEXT') for key in fields) + ')')
            for item in catalog['artworks'][:3]:
                art = dict(item)
                if art['artwork_index'] == 1:
                    art.update(title='수정한 작품', description='보존할 설명', title_en='My Edited Title', theme='자연')
                db.execute('INSERT INTO artworks VALUES (' + ', '.join('?' for _ in fields) + ')', [art[key] for key in fields])
            db.execute('CREATE TABLE catalog_migrations (version TEXT PRIMARY KEY)')
            db.execute('INSERT INTO catalog_migrations VALUES (?)', (catalog['artwork_version'],))
            db.execute('INSERT INTO catalog_migrations VALUES (?)', (catalog['artwork_content_version'],))
            db.execute('CREATE TABLE robots (robot_id TEXT PRIMARY KEY, active INTEGER, pose_x REAL, pose_y REAL, pose_theta REAL, frame_id TEXT, pose_updated_at INTEGER)')
            db.execute("INSERT INTO robots VALUES ('robot-01', ?, 2.5, 3, 1.5, 'map', 1234)", (2 if bad_pose else 1,))
            # 로봇 배정 컬럼이 없던 버전에서도 이전할 수 있어야 합니다.
            db.execute('CREATE TABLE sessions (id TEXT PRIMARY KEY, mode TEXT, course_id TEXT, artwork_ids TEXT, visited_ids TEXT, status TEXT, created_at INTEGER, started_at INTEGER, ended_at INTEGER)')
            db.execute("INSERT INTO sessions VALUES ('old-record', 'course', 'A', '[\"art-01\"]', '[\"art-01\"]', 'completed', 1000, 2000, 3000)")

    def test_migration_preserves_edits_pose_logs_and_runs_once(self):
        self.create_legacy_database()
        client = create_app(self.config).test_client()
        art = client.get('/api/artworks/1').json
        self.assertEqual((art['title'], art['description'], art['title_en'], art['theme']),
                         ('수정한 작품', '보존할 설명', 'My Edited Title', 'nature'))
        self.assertEqual(client.get('/api/robots/robot-01').json['pose'], {'x': 2.5, 'y': 3, 'theta': 1.5})
        record = client.get('/api/sessions/old-record').json
        self.assertEqual((record['courseId'], record['createdAt'], record['endedAt']), ('A', 1000, 3000))
        with sqlite3.connect(self.path) as db:
            tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            self.assertTrue({'Art', 'Pose', 'Log'}.issubset(tables))
            self.assertTrue({'artworks', 'robots', 'sessions'}.isdisjoint(tables))
            self.assertEqual(db.execute('PRAGMA integrity_check').fetchone()[0], 'ok')
        restarted = create_app(self.config).test_client()
        self.assertEqual(restarted.get('/api/artworks/1').json, art)
        self.assertEqual(restarted.get('/api/sessions/old-record').json, record)

    def test_failed_migration_rolls_back_original_tables_and_data(self):
        self.create_legacy_database(bad_pose=True)
        with sqlite3.connect(self.path) as db:
            db.row_factory = sqlite3.Row
            with self.assertRaises(sqlite3.IntegrityError):
                initialize_database(db, ROOT)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM artworks').fetchone()[0], 3)
            self.assertEqual(db.execute('SELECT active FROM robots').fetchone()[0], 2)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM sessions').fetchone()[0], 1)
            self.assertIsNone(db.execute("SELECT name FROM sqlite_master WHERE name='Art'").fetchone())

    def test_existing_three_artwork_constraint_expands_without_losing_edits_or_logs(self):
        client = login_admin(create_app(self.config).test_client())
        saved = client.patch('/api/artworks/1', json={
            'title': '보존할 제목', 'title_en': 'Keep this title', 'x': -8.5, 'location': '201',
        }).json
        record = client.post('/api/sessions', json={'mode': 'free', 'artworkIds': ['art-01']}).json
        # 직전 v4 DB의 작품 3개 제한을 재현합니다.
        sql = (ROOT / 'schema.sql').read_text().split(';')[0]
        sql = sql.replace("artwork_id GLOB '[0-9][0-9][0-9]'", "artwork_id IN ('001', '002', '003')")
        sql = sql.replace('artwork_index BETWEEN 1 AND 999', 'artwork_index BETWEEN 1 AND 3')
        with sqlite3.connect(self.path) as db:
            db.execute('ALTER TABLE Art RENAME TO saved_art')
            db.execute(sql)
            db.execute('INSERT INTO Art SELECT * FROM saved_art WHERE artwork_index <= 3')
            db.execute('DROP TABLE saved_art')
            db.execute('PRAGMA user_version=4')
        restarted = create_app(self.config).test_client()
        self.assertEqual(restarted.get('/api/artworks/1').json, saved)
        self.assertEqual(restarted.get('/api/artworks/4').json['artwork_id'], '004')
        self.assertEqual(restarted.get('/api/sessions/' + record['id']).json, record)
        twice = create_app(self.config).test_client()
        self.assertEqual(len(twice.get('/api/artworks').json['artworks']), 4)
        self.assertEqual(twice.get('/api/artworks/1').json, saved)

    def test_simple_content_applies_once_and_later_sql_changes_are_live(self):
        app = create_app(self.config)
        client = app.test_client()
        with sqlite3.connect(self.path) as db:
            db.execute("DELETE FROM catalog_migrations WHERE version='simple-artwork-content-v1'")
            db.execute("UPDATE Art SET artwork_title='old-title', artist='old-artist', location='old-room', theme='old-theme', description='old-description', x=12, y=-4 WHERE artwork_id='001'")
        restarted = create_app(self.config).test_client()
        row = restarted.get('/api/artworks/1').json
        self.assertEqual([row[key] for key in ('title_en','artist_name_en','location','theme','description','x','y')],
                         ['artwork1','artist1','location1','theme1','description1',12,-4])
        with sqlite3.connect(self.path) as db:
            db.execute("UPDATE Art SET artwork_title='Live SQL Title', artist='Live SQL Artist', location='New Room', theme='New Theme', description='Live SQL Description' WHERE artwork_id='001'")
        # 같은 앱에서도 새 요청 즉시 최신 DB 값이 반환됩니다.
        live = client.get('/api/catalog').json['artworks'][0]
        self.assertEqual([live[key] for key in ('title_en','artist_name_en','location','theme','description')],
                         ['Live SQL Title','Live SQL Artist','New Room','New Theme','Live SQL Description'])
        self.assertEqual(create_app(self.config).test_client().get('/api/artworks/1').json, live)
