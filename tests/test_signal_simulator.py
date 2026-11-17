import tempfile
import unittest
from pathlib import Path
from app import create_app
from signal_simulator import ManualTransport, LABELS
from robot_availability import RobotAvailability


class SimulatorTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.transport = ManualTransport()
        self.app = create_app({'TESTING': True, 'DATABASE': Path(self.temp.name)/'sim.sqlite3',
            'SIGNAL_SIMULATOR': self.transport, 'PREPARATION_TRANSPORT': self.transport,
            'AVAILABILITY_MONITOR': RobotAvailability(), 'CENTRAL_ROS_ENABLED': False})
        self.client = self.app.test_client()
        self.manager = self.app.extensions['robot_preparation']
        self.addCleanup(self.manager.stop)

    def send(self, event, **values):
        response = self.client.post('/api/simulator/signal', json={'signal': event, **values})
        self.assertEqual(response.status_code, 200, response.json)
        return response.json.get('session_id')

    def test_all_signals_without_preconditions(self):
        # Each signal must work as the first input to a new, unprepared session.
        for event in LABELS:
            sid = self.client.post('/api/simulator/session').json['session_id']
            self.send(event, session_id=sid)
        self.assertEqual(len(self.transport.history), len(LABELS))

    def test_jumps_backward_and_after_completion(self):
        sid = self.send('art3')
        self.assertTrue(sid)
        row = self.client.get('/api/sessions/'+sid).json
        self.assertEqual(row['visitedIds'], ['art-03'])
        self.assertEqual(row['status'], 'active')
        self.send('tour_completed', session_id=sid)
        self.send('art1', session_id=sid)
        self.assertEqual(self.client.get('/api/sessions/'+sid).json['status'], 'active')
        self.send('ready_on', session_id=sid)
        self.assertEqual(self.manager.get(sid).phase, 'ready')
        self.send('arrived', session_id=sid)
        self.assertEqual(self.manager.get(sid).phase, 'arrived')
        self.send('scan_failed', session_id=sid)
        self.send('scan_success', session_id=sid)
        self.assertEqual(self.manager.get(sid).phase, 'waiting_ready')
        self.send('ready_on', session_id=sid)
        self.assertEqual(self.client.patch('/api/sessions/'+sid, json={'status': 'active'}).status_code, 200)

    def test_normal_kiosk_call_and_register_still_work(self):
        session = self.client.post('/api/sessions', json={'mode': 'course', 'courseId': 'A', 'artworkIds': ['art-01','art-02','art-03']}).json
        sid = session['id']
        self.assertEqual(self.client.post('/api/sessions/'+sid+'/preparation', json={}).status_code, 202)
        self.send('arrived', session_id=sid)
        self.assertEqual(self.client.post('/api/sessions/'+sid+'/preparation/register', json={}).status_code, 202)
        self.send('scan_success', session_id=sid)
        self.send('ready_on', session_id=sid)
        self.assertEqual(self.manager.get(sid).phase, 'ready')

    def test_values_isolation_and_stream(self):
        self.send('available_off')
        self.assertFalse(self.client.get('/api/simulator').json['availability']['available'])
        self.send('available_on')
        self.assertTrue(self.client.get('/api/simulator').json['availability']['available'])
        sid = self.send('scan_progress', message='<script>test</script>', progress=.83, robot='robot2')
        self.assertEqual(self.manager.get(sid).progress, .83)
        self.assertEqual(self.manager.get(sid).robot_id, 'robot2')
        response = self.client.get('/api/simulator/live', buffered=False)
        try:
            chunk = next(iter(response.response)).decode()
            self.assertIn(sid, chunk)
            self.assertIn('registering', chunk)
        finally:
            response.close()
        self.send('connection_off', session_id=sid)
        response = self.client.get('/api/simulator/live', buffered=False)
        try:
            self.assertEqual(next(iter(response.response)).decode(), ': paused\n\n')
        finally:
            response.close()
        self.send('connection_on', session_id=sid)
        for bad in [{'signal':'bad'}, {'signal':'art1','progress':2}, {'signal':'art1','progress':True}, {'signal':'art1','session_id':42}]:
            self.assertEqual(self.client.post('/api/simulator/signal', json=bad).status_code, 400)
        self.assertEqual(self.client.get('/remote', environ_overrides={'REMOTE_ADDR':'192.168.1.5'}).status_code, 403)
        other = create_app({'TESTING': True, 'DATABASE': Path(self.temp.name)/'real.sqlite3'}).test_client()
        self.assertFalse(other.get('/api/test-mode').json['enabled'])
        self.assertEqual(other.get('/remote').status_code, 404)
