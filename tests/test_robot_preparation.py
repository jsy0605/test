import tempfile
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace as Msg

from app import create_app
from robot_preparation import Preparation, PreparationError, PreparationManager
from tests.auth_helpers import login_admin


def until(predicate, timeout=2):
    deadline = time.monotonic() + timeout
    while not predicate():
        if time.monotonic() > deadline:
            raise AssertionError('state did not converge')
        time.sleep(.005)


class FakeTransport:
    def __init__(self):
        self.calls = []
        self.accept = True
        self.move_error = None
        self.registration_error = None
        self.block_move = False
        self.allow_stop = threading.Event()
        self.early_ready = False

    def start(self, on_ready):
        self.on_ready = on_ready

    def call(self, job):
        self.calls.append('call')
        return Msg(accepted=self.accept, robot_id='robot2', robot_namespace='/robot2', message='배정 거절')

    def action(self, job, kind, feedback):
        self.calls.append(kind)
        if kind == 'move_to_kiosk':
            if self.move_error:
                raise PreparationError(self.move_error)
            if self.block_move:
                with job.lock:
                    job.motion_pending = True
                self.allow_stop.wait(2)
                with job.lock:
                    job.motion_pending = False
        else:
            if self.registration_error:
                raise PreparationError(self.registration_error)
            if self.early_ready:
                self.on_ready(Msg(session_id=job.session['id'], robot_id=job.robot_id, ready=True, message='준비 완료'))
        feedback(Msg(progress=.8, message='진행 중'))
        return Msg(success=True, visitor_id='visitor-a', message='완료')

    def stop(self):
        self.allow_stop.set()


class PreparationTest(unittest.TestCase):
    def setUp(self):
        self.transport = FakeTransport()
        self.manager = PreparationManager(self.transport, ready_timeout=.1)
        self.transport.start(self.manager.receive_ready)
        self.addCleanup(self.manager.stop)

    def job(self):
        job = self.manager.start(dict(id='session-a', mode='course', courseId='A', artworkIds=['art-01']))
        until(lambda: job.phase in {'arrived','error'})
        return job

    def ready(self, job, **kwargs):
        self.manager.receive_ready(Msg(session_id=job.session['id'], robot_id=job.robot_id, ready=True, message='준비 완료', **kwargs))

    def test_real_order_and_wrong_or_early_ready_do_not_advance(self):
        job = self.job()
        self.ready(job)  # before registration: ignore
        self.assertFalse(job.ready_received)
        self.manager.register(job)
        until(lambda: job.phase == 'waiting_ready')
        for session_id, robot_id in [('old-session','robot2'),('session-a','robot1')]:
            self.manager.receive_ready(Msg(session_id=session_id, robot_id=robot_id, ready=True, message=''))
        self.assertEqual(job.phase, 'waiting_ready')
        self.ready(job)
        self.assertEqual(job.phase, 'ready')
        self.assertEqual(job.visitor_id, 'visitor-a')
        self.assertEqual(self.transport.calls, ['call', 'move_to_kiosk', 'register_visitor'])
        self.manager.receive_ready(Msg(session_id='session-a', robot_id='robot2', ready=False, message='대기'))
        self.assertEqual(job.phase, 'waiting_ready')

    def test_ready_just_before_registration_result_is_preserved(self):
        self.transport.early_ready = True
        job = self.job()
        self.manager.register(job)
        until(lambda: job.phase == 'ready')

    def test_reject_failure_and_missing_topic_never_become_ready(self):
        self.transport.accept = False
        job = self.job()
        self.assertEqual(job.phase, 'error')
        self.assertEqual(self.transport.calls, ['call'])
        self.transport.accept = True
        self.transport.move_error = '경로 막힘'
        job = self.manager.start(dict(id='session-b'))
        until(lambda: job.phase == 'error')
        self.assertEqual(job.message, '경로 막힘')
        self.transport.move_error = None
        job = self.manager.start(dict(id='session-c'))
        until(lambda: job.phase == 'arrived')
        self.manager.register(job)
        until(lambda: job.phase == 'error')
        self.assertIn('준비 완료 신호', job.message)

    def test_cancel_waits_for_action_terminal_and_prevents_late_advance(self):
        self.transport.block_move = True
        job = self.manager.start(dict(id='session-cancel'))
        until(lambda: job.motion_pending)
        with self.assertRaises(PreparationError):
            self.manager.cancel_job(job, timeout=.02)
        self.assertNotEqual(job.phase, 'cancelled')
        self.transport.allow_stop.set()
        until(lambda: not job.motion_pending)
        self.manager.cancel_job(job)
        self.assertEqual(job.phase, 'cancelled')
        self.ready(job)
        self.assertEqual(job.phase, 'cancelled')


class PreparationApiTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.transport = FakeTransport()
        self.app = create_app(dict(TESTING=True, DATABASE=Path(self.temp.name)/'db.sqlite3', PREPARATION_TRANSPORT=self.transport))
        self.manager = self.app.extensions['robot_preparation']
        self.addCleanup(self.manager.stop)
        self.client = self.app.test_client()
        self.session = self.client.post('/api/sessions', json=dict(mode='course', courseId='A', artworkIds=['art-01','art-02','art-03'])).json
        self.url = '/api/sessions/' + self.session['id']

    def test_start_gate_persistence_stream_and_duplicate_requests(self):
        self.assertEqual(self.client.patch(self.url, json=dict(status='active')).status_code, 409)
        self.assertEqual(self.client.post(self.url+'/preparation/register', json={}).status_code, 409)
        self.assertEqual(self.client.post(self.url+'/preparation', json={}).status_code, 202)
        job = self.manager.get(self.session['id'])
        until(lambda: job.phase == 'arrived')
        self.client.post(self.url+'/preparation', json={})
        self.assertEqual(self.transport.calls.count('call'), 1)
        self.assertEqual(self.client.get(self.url).json['robotId'], 'robot2')
        self.assertEqual(self.client.patch(self.url, json=dict(status='cancelled')).status_code, 409)
        self.assertEqual(self.client.post(self.url+'/preparation/register', json={}).status_code, 202)
        until(lambda: job.phase == 'waiting_ready')
        self.assertEqual(self.client.post(self.url+'/preparation/register', json={}).status_code, 409)
        self.assertEqual(self.client.patch(self.url, json=dict(status='active')).status_code, 409)
        self.manager.receive_ready(Msg(session_id=job.session['id'], robot_id='robot2', ready=True, message=''))
        stream = self.client.get(self.url+'/preparation/events', buffered=False)
        self.assertIn(b'"phase": "ready"', next(iter(stream.response)))
        stream.close()
        self.assertEqual(self.client.patch(self.url, json=dict(status='active')).status_code, 200)
        self.assertEqual(self.client.get(self.url).json['visitorId'], 'visitor-a')

    def test_cancel_route_then_record_cancel(self):
        self.client.post(self.url+'/preparation', json={})
        job = self.manager.get(self.session['id'])
        until(lambda: job.phase == 'arrived')
        self.assertEqual(self.client.post(self.url+'/preparation/cancel', json={}).status_code, 200)
        self.assertEqual(self.client.patch(self.url, json=dict(status='cancelled')).status_code, 200)
        self.assertEqual(self.client.post(self.url+'/preparation', json={}).status_code, 409)

    def test_dev2_error_to_ready_stream_and_normal_tour_without_ros_commands(self):
        self.transport.accept = False
        self.client.post(self.url+'/preparation', json={})
        old_job = self.manager.get(self.session['id'])
        until(lambda: old_job.phase == 'error')
        stream = self.client.get(self.url+'/preparation/events', buffered=False)
        self.addCleanup(stream.close)
        frames = iter(stream.response)
        self.assertIn(b'"phase": "error"', next(frames))
        login_admin(self.client)
        endpoint = '/api/dev/preparation/' + self.session['id'] + '/ready'
        calls = list(self.transport.calls)
        response = self.client.post(endpoint, json={})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json['phase'], 'ready')
        self.assertTrue(response.json['dev_mode'])
        self.assertEqual(response.json['robot_id'], 'DEV-ARTI')
        self.assertEqual(self.client.post(endpoint, json={}).json, response.json)
        self.assertTrue(old_job.cancel.is_set())
        self.manager._error(old_job, PreparationError('late response'))
        self.assertIn(b'"phase": "ready"', next(frames))
        stream.close()
        row = self.client.get(self.url).json
        self.assertEqual(row['robotId'], 'DEV-ARTI')
        self.assertTrue(row['visitorId'].startswith('dev-visitor-'))
        self.assertEqual(self.client.patch(self.url, json={'status':'active'}).status_code, 200)
        completed = self.client.patch(self.url, json={'status':'completed', 'visitedIds':['art-01']})
        self.assertEqual(completed.status_code, 200)
        self.assertIsInstance(completed.json['endedAt'], int)
        self.assertEqual(self.transport.calls, calls)
        self.assertEqual(self.client.post(endpoint, json={}).status_code, 409)

    def test_dev2_requires_admin_csrf_and_local_access(self):
        endpoint = '/api/dev/preparation/' + self.session['id'] + '/ready'
        self.assertEqual(self.client.post(endpoint, json={}).status_code, 401)
        login_admin(self.client)
        token = self.client.environ_base.pop('HTTP_X_CSRF_TOKEN')
        self.assertEqual(self.client.post(endpoint, json={}).status_code, 403)
        self.client.environ_base['HTTP_X_CSRF_TOKEN'] = token
        self.assertEqual(self.client.post(endpoint, json={}, environ_overrides={'REMOTE_ADDR':'192.168.1.10'}).status_code, 403)
        self.assertIsNone(self.manager.get(self.session['id']))

    def test_dev2_recovers_preparation_lost_on_restart(self):
        login_admin(self.client)
        endpoint = '/api/dev/preparation/' + self.session['id'] + '/ready'
        self.assertIsNone(self.manager.get(self.session['id']))
        self.assertEqual(self.client.post(endpoint, json={}).status_code, 200)
        self.assertEqual(self.client.patch(self.url, json={'status':'active'}).status_code, 200)
        self.assertEqual(self.transport.calls, [])

    def test_dev2_cannot_override_pending_or_live_robot_work(self):
        login_admin(self.client)
        endpoint = '/api/dev/preparation/' + self.session['id'] + '/ready'
        job = Preparation(self.session, phase='error', motion_pending=True)
        self.manager.jobs[self.session['id']] = job
        self.assertEqual(self.client.post(endpoint, json={}).status_code, 409)
        self.assertIs(self.manager.get(self.session['id']), job)
        self.assertFalse(job.cancel.is_set())
        job.motion_pending = False
        for phase in ('calling','moving','registering','cancelling','cancelled'):
            job.phase = phase
            self.assertEqual(self.client.post(endpoint, json={}).status_code, 409)
        self.assertEqual(self.transport.calls, [])


if __name__ == '__main__':
    unittest.main()
