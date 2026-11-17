"""로봇/중앙 서버가 HTTP로 전송한 로그만 저장합니다."""
import os
import re
import secrets
from datetime import datetime
from pathlib import Path
from flask import abort, jsonify, request
from log_query import log_page


def initialize_log_token(app):
    if app.config.get('LOG_API_TOKEN'): return
    path = Path(app.config['DATABASE']).parent / '.robot-log-token'
    if not path.exists():
        temporary = path.with_name('.robot-log-token-' + secrets.token_hex(8) + '.tmp')
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            with os.fdopen(descriptor, 'w') as stream:
                stream.write(secrets.token_urlsafe(32))
            try:
                os.link(temporary, path)
            except FileExistsError:
                pass
        finally:
            temporary.unlink(missing_ok=True)
    token = path.read_text().strip()
    if len(token) < 32: raise RuntimeError('로봇 로그 전송 토큰 파일을 확인해 주세요.')
    app.config['LOG_API_TOKEN'] = token


def sent_time(value):
    if type(value) is int and 0 <= value <= 253402300799999: return value
    if isinstance(value, str) and len(value) <= 80:
        try:
            date = datetime.fromisoformat(value.replace('Z','+00:00'))
            if date.tzinfo is None: raise ValueError()
            result = int(date.timestamp() * 1000)
            if not 0 <= result <= 253402300799999: raise ValueError()
            return result
        except (ValueError, OverflowError, OSError): pass
    abort(400, description='sent_at은 Unix 밀리초 정수 또는 시간대가 있는 ISO 날짜·시간이어야 합니다.')


def register_robot_logs(app, get_db, json_body):
    @app.get('/api/logs')
    def list_robot_logs():
        return jsonify(log_page(get_db(), request.args))

    @app.post('/api/logs')
    def receive_robot_log():
        body = json_body({'robot_id','sent_at','message'})
        robot_id, message = body.get('robot_id'), body.get('message')
        if not isinstance(robot_id, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,64}', robot_id):
            abort(400, description='robot_id는 영문·숫자·밑줄·하이픈 1~64자로 보내 주세요.')
        if not isinstance(message, str) or not message.strip() or len(message) > 10000:
            abort(400, description='message는 비어 있지 않은 10000자 이내 문자열이어야 합니다.')
        timestamp = sent_time(body.get('sent_at'))
        db = get_db()
        with db:
            cursor = db.execute('INSERT INTO Log (robot_id,sent_at,message) VALUES (?,?,?)', (robot_id,timestamp,message))
            log_id = cursor.lastrowid
        return jsonify(log_id=log_id, robot_id=robot_id, sent_at=timestamp, message=message), 201

    @app.delete('/api/logs')
    def reset_robot_logs():
        body = json_body({'confirm','expected_count'})
        expected = body.get('expected_count')
        if body.get('confirm') != 'RESET_LOGS' or type(expected) is not int or expected < 0:
            abort(400, description='삭제할 전체 로그 건수를 확인해 주세요.')
        db = get_db()
        with db:
            db.execute('BEGIN IMMEDIATE')
            count = db.execute('SELECT COUNT(*) FROM Log').fetchone()[0]
            if count != expected:
                abort(409, description='로그 건수가 변경됐습니다. 초기화 창을 다시 열어 확인해 주세요.')
            db.execute('DELETE FROM Log')
            db.execute("DELETE FROM sqlite_sequence WHERE name='Log'")
        return jsonify(deleted=count,total=0)
