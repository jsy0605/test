"""로컬 관리자 계정, 세션 인증 및 관리자 요청의 CSRF 보호."""

import hmac
import hashlib
import os
import re
import secrets
import time
from datetime import timedelta
from pathlib import Path

import click
from flask import abort, g, jsonify, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

DUMMY_HASH = generate_password_hash(secrets.token_urlsafe(24))
WRITE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


def same_token(expected, supplied):
    return (isinstance(expected, str) and isinstance(supplied, str)
            and hmac.compare_digest(expected.encode("utf-8"), supplied.encode("utf-8")))


def session_digest():
    token = session.get("admin_token")
    return hashlib.sha256(token.encode()).hexdigest() if isinstance(token, str) else ""


def initialize_session_key(app):
    if not app.config.get("SECRET_KEY"):
        path = Path(app.config["DATABASE"]).parent / ".session-secret.key"
        if not path.exists():
            temporary = path.with_name(f".session-secret-{secrets.token_hex(8)}.tmp")
            descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            try:
                with os.fdopen(descriptor, "wb") as stream:
                    stream.write(secrets.token_bytes(32))
                try:
                    os.link(temporary, path)
                except FileExistsError:
                    pass
            finally:
                temporary.unlink(missing_ok=True)
        app.config["SECRET_KEY"] = path.read_bytes()
        if len(app.config["SECRET_KEY"]) < 32:
            raise RuntimeError("세션 서명 키 파일을 확인해 주세요.")
    app.config.update(
        SESSION_COOKIE_NAME="arti_admin_session",
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        PERMANENT_SESSION_LIFETIME=timedelta(hours=8),
        SESSION_REFRESH_EACH_REQUEST=False,
    )


def register_admin_auth(app, get_db):
    def csrf_token():
        if "csrf_token" not in session:
            session["csrf_token"] = secrets.token_urlsafe(32)
        return session["csrf_token"]

    def require_csrf():
        supplied = request.headers.get("X-CSRF-Token") or request.form.get("csrf_token", "")
        expected = session.get("csrf_token")
        if not expected or not same_token(expected, supplied):
            abort(403, description="인증 정보가 만료됐습니다. 페이지를 새로고침하고 다시 시도해 주세요.")

    def current_admin():
        if "current_admin" not in g:
            row = get_db().execute(
                "SELECT u.id, u.username, u.auth_version FROM admin_users u JOIN admin_sessions s ON s.admin_id=u.id "
                "WHERE u.id=? AND s.token_hash=? AND s.expires_at>?",
                (session.get("admin_id"), session_digest(), time.time()),
            ).fetchone()
            g.current_admin = (dict(row) if row and row["auth_version"] == session.get("auth_version") else None)
        return g.current_admin

    def has_admin():
        return get_db().execute("SELECT 1 FROM admin_users LIMIT 1").fetchone() is not None

    def establish_login(row):
        previous_token = session_digest()
        session.clear()
        session["admin_id"] = row["id"]
        session["auth_version"] = row["auth_version"]
        session["admin_token"] = secrets.token_urlsafe(32)
        session.permanent = True
        now = time.time()
        with get_db():
            get_db().execute("DELETE FROM admin_sessions WHERE token_hash=? OR expires_at<=?", (previous_token, now))
            get_db().execute("INSERT INTO admin_sessions VALUES (?, ?, ?)",
                             (session_digest(), row["id"], now + app.permanent_session_lifetime.total_seconds()))
        csrf_token()

    def credentials(form, creating=False):
        username = form.get("username", "").strip().lower()
        password = form.get("password", "")
        if not re.fullmatch(r"[a-z0-9_.-]{3,40}", username):
            return None, "아이디는 영문·숫자·밑줄·점·하이픈 3~40자로 입력해 주세요."
        if not 10 <= len(password) <= 128:
            return None, "비밀번호는 10~128자로 입력해 주세요." if creating else "아이디 또는 비밀번호를 확인해 주세요."
        if creating and password != form.get("password_confirm"):
            return None, "비밀번호 확인이 일치하지 않습니다."
        return (username, password), None

    def admin_request():
        path = request.path
        return (
            path.rstrip("/") in {"/data", "/sysmon"}
            or path.startswith("/api/system/")
            or path == "/api/ros/config"
            or (path == "/api/sessions" and request.method == "GET")
            or (path == "/api/logs" and request.method in WRITE_METHODS | {"GET"})
            or (path.startswith("/api/artworks/") and request.method in WRITE_METHODS)
            or (path.startswith("/api/robots/") and request.method in WRITE_METHODS)
            or (path.startswith("/api/dev/") and request.method in WRITE_METHODS)
        )

    @app.before_request
    def protect_admin_routes():
        if not admin_request():
            return None
        if request.method == 'POST' and request.path == '/api/logs':
            authorization = request.headers.get('Authorization', '')
            if authorization:
                expected = app.config.get('LOG_API_TOKEN')
                if expected and same_token(authorization, 'Bearer ' + expected):
                    return None
                abort(401, description='로봇 로그 전송 토큰을 확인해 주세요.')
        # 로봇 프로그램의 pose 전송은 별도 설정된 전용 토큰으로도 허용합니다.
        if request.method == "PUT" and re.fullmatch(r"/api/robots/[^/]+", request.path):
            authorization = request.headers.get("Authorization", "")
            if authorization:
                expected = app.config.get("ROBOT_API_TOKEN")
                if expected and same_token(authorization, "Bearer " + expected):
                    return None
                abort(401, description="로봇 전송 인증 정보를 확인해 주세요.")
        if current_admin() is None:
            if request.path.startswith("/api/"):
                abort(401, description="관리자 로그인이 필요합니다.")
            return redirect(url_for("admin_login"))
        if request.method in WRITE_METHODS:
            require_csrf()
        return None

    @app.context_processor
    def auth_template_context():
        return {"csrf_token": csrf_token, "current_admin": current_admin()}

    @app.after_request
    def auth_cache_headers(response):
        if request.path in {"/login", "/logout", "/admin/setup", "/data", "/sysmon"} or request.path.startswith("/api/auth/"):
            response.headers["Cache-Control"] = "no-store"
        response.headers["X-Frame-Options"] = "DENY"
        return response

    @app.get("/api/auth/status")
    def admin_status():
        admin = current_admin()
        return jsonify(authenticated=admin is not None, username=admin["username"] if admin else None,
                       setup_required=not has_admin(), csrf_token=csrf_token())

    @app.route("/admin/setup", methods=["GET", "POST"])
    def admin_setup():
        if request.remote_addr not in {"127.0.0.1", "::1"}:
            abort(403, description="최초 관리자 계정은 이 컴퓨터에서만 만들 수 있습니다.")
        if has_admin():
            return redirect(url_for("admin_login"))
        error = None
        if request.method == "POST":
            require_csrf()
            values, error = credentials(request.form, creating=True)
            if not error:
                username, password = values
                password_hash = generate_password_hash(password)
                db = get_db()
                with db:
                    db.execute("BEGIN IMMEDIATE")
                    if has_admin():
                        abort(409, description="관리자 계정이 이미 만들어졌습니다. 로그인해 주세요.")
                    db.execute("INSERT INTO admin_users (id, username, password_hash, created_at) VALUES (1, ?, ?, ?)",
                               (username, password_hash, int(time.time())))
                establish_login(get_db().execute("SELECT * FROM admin_users WHERE id=1").fetchone())
                return redirect(url_for("data_page"), code=303)
        return render_template("admin_login.html", setup=True, error=error), 400 if error else 200

    @app.route("/login", methods=["GET", "POST"])
    def admin_login():
        if not has_admin():
            return redirect(url_for("admin_setup"))
        if current_admin():
            return redirect(url_for("data_page"))
        error, status = None, 200
        if request.method == "POST":
            require_csrf()
            address = request.remote_addr or "unknown"
            attempts = get_db().execute("SELECT * FROM admin_login_attempts WHERE client_address=?", (address,)).fetchone()
            now = time.time()
            if attempts and attempts["blocked_until"] > now:
                return render_template("admin_login.html", setup=False,
                                       error="로그인 시도가 많습니다. 5분 후 다시 시도해 주세요."), 429
            values, error = credentials(request.form)
            username, password = values or ("", "")
            row = get_db().execute("SELECT * FROM admin_users WHERE username=?", (username,)).fetchone()
            password_ok = check_password_hash(row["password_hash"] if row else DUMMY_HASH, password)
            if not error and row and password_ok:
                with get_db():
                    get_db().execute("DELETE FROM admin_login_attempts WHERE client_address=?", (address,))
                establish_login(row)
                return redirect(url_for("data_page"), code=303)
            db = get_db()
            with db:
                db.execute("BEGIN IMMEDIATE")
                previous = db.execute("SELECT * FROM admin_login_attempts WHERE client_address=?", (address,)).fetchone()
                count = previous["failures"] + 1 if previous and now - previous["window_started"] < 300 else 1
                started = previous["window_started"] if previous and count > 1 else now
                db.execute("INSERT INTO admin_login_attempts VALUES (?, ?, ?, ?) ON CONFLICT(client_address) "
                           "DO UPDATE SET failures=excluded.failures, window_started=excluded.window_started, blocked_until=excluded.blocked_until",
                           (address, count, started, now + 300 if count >= 5 else 0))
            error, status = "아이디 또는 비밀번호를 확인해 주세요.", 401
        return render_template("admin_login.html", setup=False, error=error), status

    @app.post("/logout")
    def admin_logout():
        require_csrf()
        with get_db():
            get_db().execute("DELETE FROM admin_sessions WHERE token_hash=?", (session_digest(),))
        session.clear()
        return redirect(url_for("admin_login"), code=303)

    @app.cli.command("set-admin")
    def set_admin():
        """관리자 계정 생성/복구. 비밀번호는 숨긴 입력으로 받습니다."""
        username = click.prompt("관리자 아이디", default="admin").strip().lower()
        password = click.prompt("새 비밀번호 (10~128자)", hide_input=True, confirmation_prompt=True)
        values, error = credentials({"username": username, "password": password, "password_confirm": password}, creating=True)
        if error:
            raise click.ClickException(error)
        password_hash = generate_password_hash(values[1])
        with get_db():
            get_db().execute(
                "INSERT INTO admin_users (id, username, password_hash, created_at) VALUES (1, ?, ?, ?) "
                "ON CONFLICT(id) DO UPDATE SET username=excluded.username, password_hash=excluded.password_hash, "
                "auth_version=admin_users.auth_version+1", (values[0], password_hash, int(time.time())),
            )
            get_db().execute("DELETE FROM admin_login_attempts")
            get_db().execute("DELETE FROM admin_sessions")
        click.echo("관리자 계정을 저장했습니다. 기존 로그인은 만료됩니다.")

    app.extensions["admin_auth"] = {"csrf_token": csrf_token, "current_admin": current_admin}
