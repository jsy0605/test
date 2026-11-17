"""Art I 로컬 데이터 서버. 실행: python3 app.py"""

import json
import os
import sqlite3
import time
from datetime import datetime
from pathlib import Path
from uuid import uuid4
from zoneinfo import ZoneInfo

from flask import Flask, abort, current_app, g, jsonify, render_template, request, send_from_directory
from werkzeug.exceptions import HTTPException

from database import initialize_database, ARTWORK_SELECT, SESSION_SELECT
from log_query import log_page
from session_query import session_page
from robot_logs import initialize_log_token, register_robot_logs
from managed_data import register_managed_data, robot_data
from robot_availability import register_robot_availability
from robot_preparation import register_robot_preparation
from central_ros import apply_ros_environment
from admin_auth import initialize_session_key, register_admin_auth
from system_monitor import register_system_monitor
from signal_simulator import register_signal_simulator

ROOT = Path(__file__).resolve().parent


def get_db():
    """요청마다 연결을 열고, 요청이 끝나면 닫습니다."""
    if "db" not in g:
        g.db = sqlite3.connect(current_app.config["DATABASE"], timeout=10)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


def now_ms():
    return time.time_ns() // 1_000_000


def session_data(row):
    return {
        "id": row["id"], "mode": row["mode"],
        "courseId": row["course_id"],
        "artworkIds": json.loads(row["artwork_ids"]),
        "visitedIds": json.loads(row["visited_ids"]),
        "status": row["status"], "createdAt": row["created_at"],
        "startedAt": row["started_at"], "endedAt": row["ended_at"],
        "robotId": row["robot_id"] or "배정 대기",
        "robotNamespace": row["robot_namespace"], "visitorId": row["visitor_id"],
        "simulation": True,
    }


def json_body(allowed):
    if not request.is_json:
        abort(415, description="Content-Type을 application/json으로 지정해 주세요.")
    body = request.get_json()
    if not isinstance(body, dict):
        abort(400, description="JSON 객체를 보내 주세요.")
    if set(body) - allowed:
        abort(400, description="지원하지 않는 항목이 있습니다.")
    return body


def validate_ids(ids, allowed):
    if (not isinstance(ids, list) or len(ids) > 100
            or any(not isinstance(item, str) for item in ids)):
        abort(400, description="작품 ID를 문자열 배열로 보내 주세요.")
    if len(set(ids)) != len(ids) or not set(ids).issubset(allowed):
        abort(400, description="중복되거나 존재하지 않는 작품 ID입니다.")
    return ids


def create_app(test_config=None):
    app = Flask(__name__)
    app.config.update(
        DATABASE=ROOT / "instance" / "arti.sqlite3",
        MAX_CONTENT_LENGTH=128 * 1024,
        TEMPLATES_AUTO_RELOAD=True,
        ROS_PREPARATION_REQUIRED=True,
        CENTRAL_ROS_ENABLED=True,
        SECRET_KEY=os.environ.get("ARTI_SECRET_KEY"),
        ROBOT_API_TOKEN=os.environ.get("ARTI_ROBOT_API_TOKEN"),
        TRUSTED_HOSTS=os.environ.get("ARTI_ALLOWED_HOSTS", "localhost,127.0.0.1,[::1]").split(","),
        LOG_API_TOKEN=os.environ.get("ARTI_LOG_API_TOKEN"),
    )
    if test_config:
        app.config.update(test_config)
    if not app.testing and app.config["CENTRAL_ROS_ENABLED"]:
        apply_ros_environment()
    Path(app.config["DATABASE"]).parent.mkdir(parents=True, exist_ok=True)
    initialize_session_key(app)
    initialize_log_token(app)

    @app.before_request
    def prepare_request():
        g.database_path = app.config["DATABASE"]
        if request.method in {"POST", "PATCH", "DELETE", "PUT"}:
            origin = request.headers.get("Origin")
            if (request.headers.get("Sec-Fetch-Site") == "cross-site"
                    or (origin and origin != request.host_url.rstrip("/"))):
                abort(403, description="같은 로컬 서버 화면에서 요청해 주세요.")

    @app.teardown_appcontext
    def close_db(error=None):
        db = g.pop("db", None)
        if db is not None:
            db.close()

    # 첫 실행에만 예시 데이터를 추가합니다. 기존 데이터는 덮어쓰지 않습니다.
    with app.app_context():
        g.database_path = app.config["DATABASE"]
        db = get_db()
        initialize_database(db, ROOT)

    register_admin_auth(app, get_db)
    register_robot_logs(app, get_db, json_body)
    register_system_monitor(app)
    register_managed_data(app, get_db, json_body, now_ms)
    register_robot_availability(app)
    @app.errorhandler(HTTPException)
    def http_error(error):
        return jsonify(error={"message": error.description}), error.code

    @app.errorhandler(sqlite3.Error)
    def database_error(error):
        app.logger.exception("SQLite 요청 처리 실패")
        return jsonify(error={"message": "데이터 저장에 실패했습니다. 다시 시도해 주세요."}), 503

    @app.after_request
    def response_headers(response):
        if request.path.startswith("/api/") or request.path == "/data":
            response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        return response

    def catalog_data():
        db = get_db()
        return {
            "artworks": [dict(row) for row in db.execute(ARTWORK_SELECT + " ORDER BY artwork_index")],
            "courses": [json.loads(row["data"]) for row in db.execute("SELECT data FROM courses ORDER BY id")],
        }

    def find_session(session_id):
        row = get_db().execute(SESSION_SELECT + " WHERE record_id = ?", (session_id,)).fetchone()
        if row is None:
            abort(404, description="관람 기록을 찾을 수 없습니다.")
        return row

    def persist_assignment(job):
        # ROS callbacks run outside Flask's request context.
        with sqlite3.connect(app.config["DATABASE"], timeout=10) as db:
            db.execute("UPDATE TourSession SET robot_id=?, robot_namespace=?, visitor_id=? WHERE record_id=?",
                       (job.robot_id, job.robot_namespace, job.visitor_id or None, job.session['id']))

    register_robot_preparation(app, find_session, session_data, persist_assignment)
    register_signal_simulator(app, get_db, session_data)

    @app.get("/")
    def index():
        return send_from_directory(ROOT, "index.html")

    @app.get("/api/health")
    def health():
        get_db().execute("SELECT 1").fetchone()
        return jsonify(status="ok", database="sqlite", simulation=True)

    @app.get("/api/ros/config")
    def ros_config():
        import os
        return jsonify({key: os.environ.get(key) for key in (
            "ROS_DOMAIN_ID", "ROS_DISCOVERY_SERVER", "ROS_SUPER_CLIENT", "RMW_IMPLEMENTATION",
        )})

    @app.get("/api/catalog")
    def catalog_endpoint():
        return jsonify(catalog_data())

    @app.get("/api/sessions")
    def list_sessions():
        return jsonify(session_page(get_db(), request.args, session_data))

    @app.post("/api/sessions")
    def create_session():
        body = json_body({"mode", "courseId", "artworkIds"})
        mode = body.get("mode")
        course_id = body.get("courseId")
        if mode not in ("course", "free"):
            abort(400, description="mode는 course 또는 free여야 합니다.")
        catalog = catalog_data()
        ids = validate_ids(body.get("artworkIds"), {f"art-{art['artwork_index']:02d}" for art in catalog["artworks"]})
        if not ids:
            abort(400, description="관람할 작품을 하나 이상 선택해 주세요.")
        if mode == "free" and course_id is not None:
            abort(400, description="자유 관람의 courseId는 null이어야 합니다.")
        if mode == "course":
            if course_id is not None:
                # 이전 클라이언트가 보낸 코스 ID는 호환을 위해 처리합니다.
                courses = {course["id"]: course for course in catalog["courses"]}
                if not isinstance(course_id, str) or course_id not in {*courses, "custom"}:
                    abort(400, description="존재하지 않는 코스입니다.")
                if course_id != "custom" and ids != courses[course_id]["ids"]:
                    abort(400, description="선택한 코스와 작품 순서가 일치하지 않습니다.")
            # 현재 배치의 시계 방향 방문 순서: 001 → 002 → 003 → 004.
            # 이전 클라이언트의 코스 요청도 같은 방향으로 정규화합니다.
            ids.sort(key=lambda artwork_id: int(artwork_id.split('-')[-1]))
        session_id = str(uuid4())
        db = get_db()
        with db:
            db.execute(
                "INSERT INTO TourSession (record_id, mode, route, artwork_ids, status, created_time) "
                "VALUES (?, ?, ?, ?, 'calling', ?)",
                (session_id, mode, course_id, json.dumps(ids), now_ms()),
            )
        response = jsonify(session_data(find_session(session_id)))
        response.status_code = 201
        response.headers["Location"] = f"/api/sessions/{session_id}"
        return response

    @app.get("/api/sessions/<session_id>")
    def get_session(session_id):
        return jsonify(session_data(find_session(session_id)))

    @app.patch("/api/sessions/<session_id>")
    def update_session(session_id):
        body = json_body({"status", "visitedIds"})
        db = get_db()
        # 상태 확인과 변경을 하나의 쓰기 트랜잭션으로 처리합니다.
        with db:
            db.execute("BEGIN IMMEDIATE")
            row = find_session(session_id)
            status = body.get("status", row["status"])
            if app.config["ROS_PREPARATION_REQUIRED"] and row["status"] == "calling":
                job = app.extensions["robot_preparation"].get(session_id)
                if status == "active" and (not job or job.snapshot()["phase"] != "ready"):
                    abort(409, description="로봇의 관람 준비 완료 신호를 기다려 주세요.")
                if status == "cancelled" and job and job.snapshot()["phase"] != "cancelled":
                    abort(409, description="로봇 작업을 먼저 취소하고 종료 상태를 확인해 주세요.")
            transitions = {
                "calling": {"calling", "active", "cancelled"},
                "active": {"active", "completed", "cancelled"},
                "completed": {"completed"}, "cancelled": {"cancelled"},
            }
            if not isinstance(status, str) or status not in transitions[row["status"]]:
                abort(409, description="현재 상태에서 요청한 상태로 변경할 수 없습니다.")
            previous = json.loads(row["visited_ids"])
            visited = validate_ids(body.get("visitedIds", previous), set(json.loads(row["artwork_ids"])))
            if (not set(previous).issubset(visited)
                    or (row["status"] in {"completed", "cancelled"} and visited != previous)
                    or (status == "calling" and visited)):
                abort(409, description="관람 기록을 변경할 수 없습니다.")
            started = row["started_at"]
            ended = row["ended_at"]
            if status == "active" and started is None:
                started = now_ms()
            if status in {"completed", "cancelled"} and ended is None:
                ended = now_ms()
            db.execute(
                "UPDATE TourSession SET status=?, visited_ids=?, started_at=?, end_time=? WHERE record_id=?",
                (status, json.dumps(visited), started, ended, session_id),
            )
        return jsonify(session_data(find_session(session_id)))

    @app.template_filter("localtime")
    def localtime(value):
        return datetime.fromtimestamp(value / 1000, tz=ZoneInfo("Asia/Seoul")).strftime("%Y-%m-%d %H:%M:%S %Z") if value is not None else "—"

    @app.get("/data")
    def data_page():
        logs = log_page(get_db(), request.args)
        return render_template("data.html", catalog=catalog_data(),
                               logs=logs, total=logs['total'])

    return app


if __name__ == "__main__":
    create_app().run(host=os.environ.get("ARTI_BIND_HOST", "127.0.0.1"), port=5000, debug=False)
