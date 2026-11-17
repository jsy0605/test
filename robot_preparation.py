"""ROS service → movement action → registration action → ready topic, bridged by SSE."""
import atexit
import json
import math
import re
import threading
import time
from dataclasses import dataclass, field

from flask import Response, abort, jsonify, request


class PreparationError(RuntimeError):
    pass


@dataclass
class Preparation:
    session: dict
    phase: str = 'calling'
    message: str = '사용 가능한 아티를 배정하고 있어요.'
    robot_id: str = ''
    robot_namespace: str = ''
    visitor_id: str = ''
    progress: float = 0.0
    ready_received: bool = False
    registration_started: bool = False
    motion_pending: bool = False
    dev_mode: bool = False
    cancel: threading.Event = field(default_factory=threading.Event)
    lock: threading.RLock = field(default_factory=threading.RLock)

    def snapshot(self):
        with self.lock:
            return dict(session_id=self.session['id'], phase=self.phase, message=self.message,
                        robot_id=self.robot_id, visitor_id=self.visitor_id, progress=self.progress,
                        dev_mode=self.dev_mode)

    def update(self, phase, message, progress=0.0):
        with self.lock:
            if self.cancel.is_set():
                return False
            self.phase, self.message, self.progress = phase, message, progress
            return True


class RosPreparationTransport:
    """All ROS futures run on one executor. Workers only wait; they never spin its node."""
    def __init__(self, discovery_timeout=8, action_timeout=180):
        self.discovery_timeout = discovery_timeout
        self.action_timeout = action_timeout
        self.started = threading.Event()
        self.stopping = threading.Event()
        self.error = None
        self.clients = {}
        self.clients_lock = threading.Lock()
        self.thread = None

    def start(self, on_ready):
        self.thread = threading.Thread(target=self._run, args=(on_ready,), daemon=True)
        self.thread.start()

    def _run(self, on_ready):
        context = node = executor = None
        try:
            import rclpy
            from rclpy.context import Context
            from rclpy.executors import SingleThreadedExecutor
            from rclpy.qos import QoSProfile, DurabilityPolicy, ReliabilityPolicy
            from arti_interfaces.srv import CallRobot
            from arti_interfaces.action import MoveToKiosk, RegisterVisitor
            from arti_interfaces.msg import TourReady
            from rclpy.action import ActionClient
            self.types = (CallRobot, MoveToKiosk, RegisterVisitor)
            self.action_client_type = ActionClient
            context = Context()
            rclpy.init(context=context, args=['--ros-args', '--disable-external-lib-logs'])
            node = rclpy.create_node('arti_kiosk_preparation', context=context,
                                    enable_rosout=False, start_parameter_services=False)
            self.node = node
            self.service = node.create_client(CallRobot, '/arti/call_robot')
            # Reliable + volatile works with default publishers; repeated ready messages recommended.
            node.create_subscription(TourReady, '/arti/tour_ready', on_ready,
                QoSProfile(depth=10, durability=DurabilityPolicy.VOLATILE,
                           reliability=ReliabilityPolicy.RELIABLE))
            executor = SingleThreadedExecutor(context=context)
            executor.add_node(node)
            self.started.set()
            while not self.stopping.is_set() and context.ok():
                executor.spin_once(timeout_sec=0.1)
        except Exception as error:
            self.error = error
            self.started.set()
        finally:
            if executor:
                executor.shutdown(timeout_sec=1)
            for client in self.clients.values():
                client.destroy()
            if node:
                node.destroy_node()
            if context and context.ok():
                context.shutdown()

    def _ensure(self):
        if not self.started.wait(self.discovery_timeout) or self.error or self.stopping.is_set():
            raise PreparationError('ROS 연결을 준비하지 못했어요. 인터페이스 빌드와 서버 실행 상태를 확인해 주세요.')

    @staticmethod
    def _wait(future, timeout, cancel=None):
        done = threading.Event()
        future.add_done_callback(lambda _: done.set())
        deadline = time.monotonic() + timeout
        while not done.wait(0.05):
            if cancel and cancel.is_set():
                raise PreparationError('호출을 취소했어요.')
            if time.monotonic() >= deadline:
                raise PreparationError('로봇 응답 시간이 초과됐어요. 연결 상태를 확인해 주세요.')
        return future.result()

    def call(self, job):
        self._ensure()
        deadline = time.monotonic() + self.discovery_timeout
        while not self.service.wait_for_service(timeout_sec=0.2):
            if job.cancel.is_set() or time.monotonic() >= deadline:
                raise PreparationError('아티 호출 서비스에 연결하지 못했어요.')
        if job.cancel.is_set():
            raise PreparationError('호출을 취소했어요.')
        req = self.types[0].Request()
        req.session_id = job.session['id']
        req.mode = job.session['mode']
        req.course_id = job.session.get('courseId') or ''
        req.artwork_ids = job.session['artworkIds']
        return self._wait(self.service.call_async(req), 10, job.cancel)

    def action(self, job, kind, feedback):
        self._ensure()
        action_type = self.types[1 if kind == 'move_to_kiosk' else 2]
        name = job.robot_namespace + '/' + kind
        with self.clients_lock:
            client = self.clients.get(name)
            if client is None:
                client = self.action_client_type(self.node, action_type, name)
                self.clients[name] = client
        deadline = time.monotonic() + self.discovery_timeout
        while not client.wait_for_server(timeout_sec=0.2):
            if job.cancel.is_set() or time.monotonic() >= deadline:
                raise PreparationError('로봇 액션 서버에 연결하지 못했어요.')
        goal = action_type.Goal()
        goal.session_id = job.session['id']
        with job.lock:
            if job.cancel.is_set():
                raise PreparationError('호출을 취소했어요.')
            job.motion_pending = True
        holder = {}
        terminal = threading.Event()

        def result_done(future):
            try:
                holder['result'] = future.result()
            except Exception as error:
                holder['error'] = error
            finally:
                with job.lock:
                    job.motion_pending = False
                terminal.set()

        def goal_done(future):
            try:
                handle = future.result()
                holder['handle'] = handle
                if not handle.accepted:
                    with job.lock:
                        job.motion_pending = False
                    terminal.set()
                else:
                    handle.get_result_async().add_done_callback(result_done)
                    if job.cancel.is_set():
                        holder['cancel_sent'] = True
                        handle.cancel_goal_async()
            except Exception as error:
                # A transport error cannot prove the robot stopped. Keep cancellation unconfirmed.
                holder['error'] = error
                terminal.set()

        try:
            future = client.send_goal_async(goal, feedback_callback=lambda msg: feedback(msg.feedback))
        except Exception:
            with job.lock:
                job.motion_pending = False  # No goal was submitted.
            raise
        future.add_done_callback(goal_done)
        deadline = time.monotonic() + self.action_timeout
        while not terminal.wait(0.05):
            handle = holder.get('handle')
            if job.cancel.is_set() and handle and handle.accepted and not holder.get('cancel_sent'):
                holder['cancel_sent'] = True
                handle.cancel_goal_async()
            if time.monotonic() >= deadline:
                job.cancel.set()  # A late goal response also receives cancellation.
                if handle and handle.accepted and not holder.get('cancel_sent'):
                    holder['cancel_sent'] = True
                    handle.cancel_goal_async()
                raise PreparationError('로봇 작업 시간이 초과됐어요. 취소 후 정지 확인이 필요해요.')
        if 'error' in holder:
            raise PreparationError('로봇 액션 연결이 끊겼어요. 정지 상태를 확인해 주세요.')
        handle = holder.get('handle')
        if not handle or not handle.accepted:
            raise PreparationError('로봇이 작업 요청을 거절했어요.')
        result = holder['result']
        if result.status != 4 or not result.result.success:  # GoalStatus.STATUS_SUCCEEDED
            raise PreparationError(result.result.message or '로봇 작업이 완료되지 않았어요.')
        return result.result

    def stop(self):
        self.stopping.set()
        if self.thread:
            self.thread.join(timeout=2)


class PreparationManager:
    def __init__(self, transport, persist=lambda job: None, ready_timeout=45):
        self.transport, self.persist, self.ready_timeout = transport, persist, ready_timeout
        self.jobs = {}
        self.lock = threading.Lock()

    def start(self, session):
        with self.lock:
            if session['id'] in self.jobs:
                return self.jobs[session['id']]
            job = Preparation(session)
            self.jobs[session['id']] = job
        if not getattr(self.transport, 'manual', False):
            threading.Thread(target=self._call_and_move, args=(job,), daemon=True).start()
        return job

    def get(self, session_id):
        with self.lock:
            return self.jobs.get(session_id)

    def dev_ready(self, session):
        """완료된 오류 작업을 로컬 화면 테스트용 준비 완료 작업으로 교체합니다."""
        with self.lock:
            previous = self.jobs.get(session['id'])
            if previous:
                with previous.lock:
                    if previous.dev_mode and previous.phase == 'ready':
                        return previous
                    if previous.motion_pending:
                        raise PreparationError('로봇 작업의 종료를 확인한 뒤 dev2를 눌러 주세요.')
                    if previous.phase != 'error':
                        raise PreparationError('오류 화면에서 dev2 준비 완료 신호를 사용할 수 있어요.')
                    previous.cancel.set()
            job = Preparation(session, phase='ready', message='dev2 테스트 신호로 관람 준비를 완료했어요. 관람 시작하기를 눌러 주세요.',
                              robot_id='DEV-ARTI', robot_namespace='/dev_arti',
                              visitor_id='dev-visitor-' + session['id'], progress=1.0,
                              ready_received=True, registration_started=True, dev_mode=True)
            self.persist(job)
            self.jobs[session['id']] = job
            return job

    def _error(self, job, error):
        with job.lock:
            if job.phase != 'cancelled':
                job.phase, job.message = 'error', str(error)

    def _call_and_move(self, job):
        try:
            response = self.transport.call(job)
            if not response.accepted:
                raise PreparationError(response.message or '지금 배정 가능한 아티가 없어요.')
            namespace = response.robot_namespace.rstrip('/')
            if (not response.robot_id or not re.fullmatch(r'(?:/[A-Za-z_][A-Za-z0-9_]*)+', namespace)):
                raise PreparationError('로봇 배정 정보가 올바르지 않아요.')
            with job.lock:
                if job.cancel.is_set():
                    return
                job.robot_id, job.robot_namespace = response.robot_id, namespace
                self.persist(job)
            if not job.update('moving', '아티가 키오스크 앞으로 이동하고 있어요.'):
                return
            self.transport.action(job, 'move_to_kiosk', lambda msg: self.feedback(job, 'moving', msg))
            job.update('arrived', '아티 정면에 한 분만 서서 등록을 시작해 주세요.', 1.0)
        except Exception as error:
            self._error(job, error)

    def feedback(self, job, phase, message):
        with job.lock:
            if job.phase != phase or job.cancel.is_set():
                return
            progress = float(message.progress)
            if math.isfinite(progress):
                job.progress = max(0.0, min(1.0, progress))
            if message.message:
                job.message = message.message

    def register(self, job):
        with job.lock:
            if job.phase != 'arrived' or job.cancel.is_set():
                raise PreparationError('아티가 도착한 뒤 등록을 시작해 주세요.')
            job.registration_started = True
            job.update('registering', '정면을 바라보고 잠시 기다려 주세요.')
        if not getattr(self.transport, 'manual', False):
            threading.Thread(target=self._register, args=(job,), daemon=True).start()

    def _register(self, job):
        try:
            result = self.transport.action(job, 'register_visitor', lambda msg: self.feedback(job, 'registering', msg))
            if not result.visitor_id:
                raise PreparationError('등록된 관람객 ID를 받지 못했어요.')
            with job.lock:
                if job.cancel.is_set():
                    return
                job.visitor_id = result.visitor_id
                self.persist(job)
                job.update('ready' if job.ready_received else 'waiting_ready',
                           '관람을 시작할 준비가 됐어요.' if job.ready_received else '로봇의 관람 준비 완료 신호를 기다리고 있어요.')
            deadline = time.monotonic() + self.ready_timeout
            while not job.cancel.wait(0.1):
                with job.lock:
                    if job.phase != 'waiting_ready':
                        return
                    if time.monotonic() >= deadline:
                        raise PreparationError('관람 준비 완료 신호를 받지 못했어요. 로봇 상태를 확인해 주세요.')
        except Exception as error:
            self._error(job, error)

    def receive_ready(self, message):
        job = self.get(message.session_id)
        if not job:
            return
        with job.lock:
            if (job.cancel.is_set() or message.robot_id != job.robot_id or not job.registration_started
                    or job.phase not in {'registering', 'waiting_ready', 'ready'}):
                return
            job.ready_received = bool(message.ready)
            if job.phase in {'waiting_ready', 'ready'}:
                job.update('ready' if message.ready else 'waiting_ready',
                           message.message or ('관람을 시작할 준비가 됐어요.' if message.ready else '로봇의 관람 준비를 기다리고 있어요.'))

    def cancel_job(self, job, timeout=6):
        with job.lock:
            job.cancel.set()
            job.phase, job.message = 'cancelling', '로봇 작업 취소와 정지 상태를 확인하고 있어요.'
        deadline = time.monotonic() + timeout
        while True:
            with job.lock:
                if not job.motion_pending:
                    job.phase, job.message = 'cancelled', '호출을 취소했어요.'
                    return
            if time.monotonic() >= deadline:
                raise PreparationError('아직 로봇 작업의 종료를 확인하지 못했어요. 잠시 후 다시 취소해 주세요.')
            time.sleep(0.05)

    def stop(self):
        for job in list(self.jobs.values()):
            job.cancel.set()
        self.transport.stop()


def register_robot_preparation(app, get_session, serialize_session, persist):
    transport = app.config.get('PREPARATION_TRANSPORT') or RosPreparationTransport()
    manager = PreparationManager(transport, persist)
    app.extensions['robot_preparation'] = manager
    if not app.testing or app.config.get('PREPARATION_TRANSPORT'):
        transport.start(manager.receive_ready)
        atexit.register(manager.stop)

    def job_for(session_id):
        get_session(session_id)
        job = manager.get(session_id)
        if not job:
            abort(409, description='진행 중인 로봇 준비 작업이 없어요. 다시 호출해 주세요.')
        return job

    @app.post('/api/sessions/<session_id>/preparation')
    def begin(session_id):
        session = serialize_session(get_session(session_id))
        if session['status'] != 'calling':
            abort(409, description='현재 관람 상태에서는 호출할 수 없어요.')
        return jsonify(manager.start(session).snapshot()), 202

    @app.post('/api/sessions/<session_id>/preparation/register')
    def register(session_id):
        job = job_for(session_id)
        try:
            manager.register(job)
        except PreparationError as error:
            abort(409, description=str(error))
        return jsonify(job.snapshot()), 202

    @app.post('/api/sessions/<session_id>/preparation/cancel')
    def cancel(session_id):
        get_session(session_id)
        job = manager.get(session_id)
        if job:
            try:
                manager.cancel_job(job)
            except PreparationError as error:
                abort(409, description=str(error))
        return jsonify(cancelled=True)

    @app.post('/api/dev/preparation/<session_id>/ready')
    def dev_ready(session_id):
        if request.remote_addr not in {'127.0.0.1', '::1'}:
            abort(403, description='dev2는 이 컴퓨터에서만 사용할 수 있어요.')
        session = serialize_session(get_session(session_id))
        if session['status'] != 'calling':
            abort(409, description='호출 준비 중인 관람에서만 dev2를 사용할 수 있어요.')
        try:
            job = manager.dev_ready(session)
        except PreparationError as error:
            abort(409, description=str(error))
        return jsonify(job.snapshot())

    @app.get('/api/sessions/<session_id>/preparation/events')
    def events(session_id):
        job = job_for(session_id)
        def stream():
            while True:
                # dev2로 작업을 교체해도 이미 열린 스트림에서 최신 준비 상태를 전달합니다.
                current = manager.get(session_id) or job
                yield 'event: preparation\ndata: ' + json.dumps(current.snapshot()) + '\n\n'
                time.sleep(0.5)
        return Response(stream(), mimetype='text/event-stream', headers={'X-Accel-Buffering': 'no', 'Cache-Control': 'no-store'})
