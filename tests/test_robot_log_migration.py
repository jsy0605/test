import sqlite3
import tempfile
import unittest
from pathlib import Path
from app import create_app
from tests.auth_helpers import login_admin


class RobotLogMigrationTest(unittest.TestCase):
    def test_v5_tour_log_migration_preserves_all_other_data_and_kiosk_flow(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'db.sqlite3'
            config={'TESTING':True,'DATABASE':path,'ROS_PREPARATION_REQUIRED':False}
            app=create_app(config)
            client=login_admin(app.test_client())
            client.patch('/api/artworks/1',json={'title_en':'보존할 작품','location':'room-9','x':4.2})
            record=client.post('/api/sessions',json={'mode':'free','artworkIds':['art-01']}).json
            with sqlite3.connect(path) as db:
                before={table:db.execute(f'SELECT * FROM {table} ORDER BY 1').fetchall() for table in ('Art','Pose','admin_users','admin_sessions','courses')}
                db.execute('DROP TABLE Log')
                db.execute('ALTER TABLE TourSession RENAME TO Log')
                db.execute('DROP INDEX tour_session_created_time')
                db.execute('CREATE INDEX log_created_time ON Log (created_time DESC,record_id DESC)')
                db.execute('PRAGMA user_version=5')
            restarted=create_app(config)
            public=restarted.test_client()
            self.assertEqual(public.get('/api/sessions/'+record['id']).json,record)
            self.assertEqual(public.patch('/api/sessions/'+record['id'],json={'status':'active'}).status_code,200)
            with sqlite3.connect(path) as db:
                for table,rows in before.items():self.assertEqual(db.execute(f'SELECT * FROM {table} ORDER BY 1').fetchall(),rows)
                self.assertEqual([row[1] for row in db.execute('PRAGMA table_info(Log)')],['log_id','robot_id','sent_at','message'])
                self.assertEqual(db.execute('SELECT COUNT(*) FROM Log').fetchone()[0],0)
                self.assertEqual(db.execute('SELECT COUNT(*) FROM TourSession').fetchone()[0],1)
                self.assertEqual(db.execute('PRAGMA integrity_check').fetchone()[0],'ok')
            token=app.config['LOG_API_TOKEN']
            self.assertEqual(restarted.config['LOG_API_TOKEN'],token)
            result=public.post('/api/logs',json={'robot_id':'tb4','sent_at':'2026-11-17T10:00:00Z','message':'첫 로봇 로그'},headers={'Authorization':'Bearer '+token})
            self.assertEqual(result.status_code,201);self.assertEqual(result.json['log_id'],1)
            twice=create_app(config)
            with sqlite3.connect(path) as db:self.assertEqual(db.execute('SELECT COUNT(*) FROM Log').fetchone()[0],1)
            self.assertEqual(twice.config['LOG_API_TOKEN'],token)
            self.assertEqual((path.parent/'.robot-log-token').stat().st_mode & 0o777,0o600)

    def test_explicit_lan_host_allows_authenticated_http_sender(self):
        with tempfile.TemporaryDirectory() as folder:
            app=create_app({'TESTING':True,'DATABASE':Path(folder)/'db.sqlite3',
                            'TRUSTED_HOSTS':['localhost','192.168.107.50'],'LOG_API_TOKEN':'test-lan-token'})
            result=app.test_client().post('/api/logs',base_url='http://192.168.107.50:5000',
                json={'robot_id':'tb1','sent_at':123456,'message':'네트워크 수신 확인'},
                headers={'Authorization':'Bearer test-lan-token'},environ_overrides={'REMOTE_ADDR':'192.168.107.101'})
            self.assertEqual(result.status_code,201)
