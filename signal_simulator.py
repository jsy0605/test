"""Free signal injection for an isolated, loopback-only kiosk. No ROS commands."""
from database import SESSION_SELECT

import json
import math
import threading
import time
from datetime import datetime
from zoneinfo import ZoneInfo
from uuid import uuid4
from flask import Response, abort, jsonify, render_template, request

GROUPS = [
 ('availability','호출 가능 여부',[('available_on','호출 가능 ON'),('available_off','호출 가능 OFF'),('availability_lost','가용 신호 수신 중단')]),
 ('assignment','호출·배정',[('assign','선택 로봇 배정 성공'),('reject','배정 거절'),('call_timeout','호출 응답 시간 초과'),('call_failed','호출 서비스 오류')]),
 ('movement','Undock·스캔 장소',[('undocking','Undock 진행'),('undocked','Undock 성공'),('move_progress','이동 중'),('arrived','스캔 장소 도착 성공'),('move_failed','이동 실패'),('move_rejected','이동 요청 거절'),('move_cancelled','이동 취소'),('move_timeout','이동 응답 시간 초과'),('undock_failed','Undock 실패')]),
 ('scan','스캔·등록',[('scan_progress','스캔 진행 중'),('scan_success','스캔·등록 성공'),('scan_failed','스캔 실패'),('scan_retry','스캔 재시도 허용'),('ready_on','관람 준비 완료 ON'),('ready_off','관람 준비 완료 OFF'),('scan_rejected','등록 요청 거절'),('scan_cancelled','등록 취소'),('scan_timeout','등록 응답 시간 초과'),('multiple_visitors','여러 명 감지'),('visitor_missing','관람객 미감지'),('identity_mismatch','다른 관람객 감지')]),
 ('tour','관람·작품 설명',[('tour_moving','관람 이동 중'),('art1','1번 구역 정지·설명 시작'),('art2','2번 구역 정지·설명 시작'),('art3','3번 구역 정지·설명 시작'),('zone1_out','1번 관람 구역 이탈'),('zone2_out','2번 관람 구역 이탈'),('zone3_out','3번 관람 구역 이탈'),('explanation_completed','설명 재생 완료'),('explanation_failed','설명 재생 실패'),('explanation_stop','설명 중단'),('visitor_wait','관람객 기다리기'),('resume','대기·오류 해제'),('tour_completed','관람 정상 종료'),('aborted','관람 비정상 종료')]),
 ('dock','복귀·Dock',[('returning','복귀 중'),('docking','Dock 진행'),('docked','Dock 성공·충전'),('dock_failed','Dock 실패'),('charging_off','충전 중단'),('charging_on','충전 시작'),('return_failed','복귀 실패')]),
 ('errors','오류·통신',[('tracking_lost','사용자 추적 실패'),('tracking_recovered','사용자 재인식 성공'),('visitor_far','관람객 거리 초과'),('visitor_near','관람객 거리 정상'),('obstacle','장애물·경로 막힘'),('emergency','긴급 정지'),('low_battery','배터리 부족'),('connection_off','키오스크 상태 수신 OFF'),('connection_on','키오스크 상태 수신 ON'),('obstacle_clear','장애물 해제'),('emergency_clear','긴급 정지 해제'),('battery_ok','배터리 정상'),('localization_lost','로봇 위치 추정 실패'),('sensor_failed','카메라·LiDAR 오류'),('error_clear','오류 전체 해제')]),
]
LABELS = {key: label for _, _, items in GROUPS for key, label in items}
PREPARATION_PHASES = {
    'assign': 'moving', 'undocking': 'moving', 'undocked': 'moving', 'move_progress': 'moving',
    'arrived': 'arrived', 'scan_retry': 'arrived', 'scan_progress': 'registering',
    'scan_success': 'waiting_ready', 'ready_on': 'ready', 'ready_off': 'waiting_ready',
    'move_cancelled': 'cancelled', 'scan_cancelled': 'cancelled',
}
PREPARATION_ERRORS = {'reject', 'call_timeout', 'call_failed', 'move_failed', 'move_rejected',
    'move_timeout', 'undock_failed', 'scan_failed', 'scan_rejected', 'scan_timeout',
    'multiple_visitors', 'visitor_missing', 'identity_mismatch'}
RESUME = {'resume', 'tracking_recovered', 'visitor_near', 'obstacle_clear', 'emergency_clear', 'battery_ok', 'error_clear'}

class ManualTransport:
    manual = True
    def __init__(self):
        self.stopped = threading.Event()
        self.cv = threading.Condition(threading.RLock())
        self.jobs = {}
        self.runtime = {}
        self.history = []
        self.latest = None
        self.sequence = 0
    def start(self, callback):
        self.ready_callback = callback
    def stop(self):
        self.stopped.set()
    def snapshot(self, sid=None):
        with self.cv:
            return {'sessions': [{'id': k, 'phase': (self.runtime.get(k, {}).get('phase') or v.phase), 'robot': v.robot_id}
                for k, v in list(self.jobs.items())], 'runtime': dict(self.runtime.get(sid, {})),
                'history': list(self.history[-80:]), 'latest_session': self.latest}


def register_signal_simulator(app, get_db, serialize):
    sim = app.config.get('SIGNAL_SIMULATOR')
    @app.get('/api/test-mode')
    def test_mode():
        return jsonify(enabled=sim is not None)
    if sim is None:
        return
    monitor = app.extensions['robot_availability']
    manager = app.extensions['robot_preparation']
    sim.jobs = manager.jobs
    settings = {'available': True, 'receiving': True}
    def heartbeat():
        while not sim.stopped.wait(.5):
            if settings['receiving']:
                monitor.update(settings['available'])
    threading.Thread(target=heartbeat, daemon=True).start()
    monitor.update(True)

    @app.before_request
    def local_only():
        if request.remote_addr not in {'127.0.0.1', '::1'}:
            abort(403)

    def new_session():
        sid = str(uuid4())
        db = get_db()
        with db:
            db.execute("INSERT INTO TourSession (record_id, mode, route, artwork_ids, status, created_time) VALUES (?, 'course', 'custom', ?, 'calling', ?)",
                (sid, json.dumps(['art-01', 'art-02', 'art-03']), int(time.time()*1000)))
        row = db.execute(SESSION_SELECT + ' WHERE record_id=?', (sid,)).fetchone()
        return manager.start(serialize(row))

    @app.get('/remote')
    def remote():
        return render_template('signal_remote.html', groups=GROUPS, count=len(LABELS))

    @app.get('/api/simulator')
    def snapshot():
        return jsonify({**sim.snapshot(), 'availability': monitor.snapshot()})

    @app.post('/api/simulator/session')
    def fresh_session():
        with sim.cv:
            job = new_session()
        return jsonify(session_id=job.session['id']), 201

    @app.post('/api/simulator/signal')
    def signal():
        body = request.get_json()
        if not isinstance(body, dict) or set(body)-{'signal', 'session_id', 'robot', 'message', 'progress'}:
            abort(400)
        event = body.get('signal')
        robot = body.get('robot', 'robot1')
        message = body.get('message', '')
        progress = body.get('progress', .5)
        if (event not in LABELS or robot not in {'robot1', 'robot2'} or not isinstance(message, str)
                or len(message) > 500 or isinstance(progress, bool) or not isinstance(progress, (int, float))
                or not math.isfinite(progress) or not 0 <= progress <= 1):
            abort(400)
        message = message.strip() or LABELS[event]
        sid = body.get('session_id')
        if sid is not None and not isinstance(sid, str):
            abort(400)
        with sim.cv:
            if event.startswith('available_') or event == 'availability_lost':
                if event == 'availability_lost':
                    settings['receiving'] = False
                else:
                    settings.update(available=event == 'available_on', receiving=True)
                    monitor.update(settings['available'])
            else:
                if not sid:
                    sid = next(reversed(sim.jobs), None)
                job = manager.get(sid)
                if not job:
                    if sid:
                        row = get_db().execute(SESSION_SELECT + ' WHERE record_id=?', (sid,)).fetchone()
                        if row is None:
                            abort(404, description='대상 테스트 세션을 찾을 수 없어요.')
                        job = manager.start(serialize(row))
                    else:
                        job = new_session()
                    sid = job.session['id']
                with job.lock:
                    # Intentional bypass: test inputs can jump forward, backward, or recover after termination.
                    job.cancel.clear()
                    job.robot_id, job.robot_namespace = robot, '/' + robot
                    job.message, job.progress = message, float(progress)
                    job.motion_pending = False
                    runtime = sim.runtime.setdefault(sid, {'receiving': True})
                    if event in {'connection_off', 'connection_on'}:
                        runtime['receiving'] = event == 'connection_on'
                    else:
                        sim.sequence += 1
                        phase = PREPARATION_PHASES.get(event, 'error' if event in PREPARATION_ERRORS else None)
                        runtime.update(phase=event, message=message, sequence=sim.sequence,
                            preparation_phase=phase, resume=event in RESUME)
                        if phase:
                            job.phase = phase
                            job.registration_started = phase in {'registering', 'waiting_ready', 'ready'}
                            job.ready_received = phase == 'ready'
                            if phase in {'waiting_ready', 'ready'}:
                                job.visitor_id = 'sim-' + sid
                            manager.persist(job)
                        db = get_db()
                        row = db.execute(SESSION_SELECT + ' WHERE record_id=?', (sid,)).fetchone()
                        ids, visited = json.loads(row['artwork_ids']), json.loads(row['visited_ids'])
                        if event in {'art1', 'art2', 'art3'}:
                            art = 'art-' + event[-1].zfill(2)
                            if art not in ids:
                                ids.append(art)
                            if art not in visited:
                                visited.append(art)
                        status = ('calling' if phase else 'completed' if event == 'tour_completed'
                            else 'cancelled' if event == 'aborted' else 'active')
                        with db:
                            db.execute('UPDATE TourSession SET artwork_ids=?, visited_ids=?, status=?, robot_id=?, robot_namespace=?, started_at=COALESCE(started_at,?), end_time=? WHERE record_id=?',
                                (json.dumps(ids), json.dumps(visited), status, robot, '/' + robot, int(time.time()*1000),
                                 int(time.time()*1000) if status in {'completed', 'cancelled'} else None, sid))
                    sim.latest = sid
            sim.history.append({'at': datetime.now(ZoneInfo('Asia/Seoul')).strftime('%H:%M:%S'),
                'session': sid, 'event': event, 'label': message, 'robot': robot, 'progress': progress})
            sim.history[:] = sim.history[-80:]
            return jsonify({**sim.snapshot(sid), 'session_id': sid})

    @app.get('/api/simulator/live')
    @app.get('/api/simulator/events/<sid>')
    def simulator_events(sid=None):
        def stream():
            import sqlite3
            while not sim.stopped.is_set():
                with sim.cv:
                    target = sid or sim.latest
                    value = dict(sim.runtime.get(target, {}))
                    job = manager.get(target)
                    preparation = job.snapshot() if job else None
                if target and value.get('receiving', True):
                    with sqlite3.connect(app.config['DATABASE']) as db:
                        db.row_factory = sqlite3.Row
                        row = db.execute(SESSION_SELECT + ' WHERE record_id=?', (target,)).fetchone()
                    if row:
                        yield 'data: ' + json.dumps({'runtime': value, 'session': serialize(row), 'preparation': preparation}) + '\n\n'
                elif target:
                    yield ': paused\n\n'
                else:
                    yield 'data: {}\n\n'
                time.sleep(.2)
        return Response(stream(), mimetype='text/event-stream', headers={'Cache-Control': 'no-store', 'X-Accel-Buffering': 'no'})
