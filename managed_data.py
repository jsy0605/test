"""관리 대상: 작품 정보와 로봇의 최신 평면 pose."""

import math
import re

from flask import abort, jsonify
from database import ARTWORK_COLUMNS, ARTWORK_SELECT


ARTWORK_FIELDS = {"artist_name": 200, "theme": 200, "title": 200, "description": 10000,
                  "artist_name_en": 200, "title_en": 200,
                  "image_alt": 500, "location": 64}
OPTIONAL_ARTWORK_FIELDS = {'artist_name_en', 'title_en', 'image_alt'}


def robot_data(row):
    return {
        "robot_id": row["robot_id"], "active": bool(row["active"]),
        "pose": None if row["x"] is None else {
            "x": row["x"], "y": row["y"], "theta": row["theta"],
        },
        "frame_id": row["frame_id"], "pose_updated_at": row["pose_updated_at"],
    }


def register_managed_data(app, get_db, json_body, now_ms):
    def find_artwork(index):
        row = get_db().execute(ARTWORK_SELECT + " WHERE artwork_index = ?", (index,)).fetchone()
        if row is None:
            abort(404, description="등록되지 않은 작품 인덱스입니다.")
        return dict(row)

    def find_robot(robot_id):
        row = get_db().execute("SELECT * FROM Pose WHERE robot_id = ?", (robot_id,)).fetchone()
        if row is None:
            abort(404, description="등록되지 않은 로봇입니다.")
        return row

    @app.get("/api/artworks")
    def list_artworks():
        return jsonify(artworks=[dict(row) for row in get_db().execute(
            ARTWORK_SELECT + " ORDER BY artwork_index")])

    @app.get("/api/artworks/<int:index>")
    def get_artwork(index):
        return jsonify(find_artwork(index))

    @app.patch("/api/artworks/<int:index>")
    def update_artwork(index):
        find_artwork(index)
        body = json_body(set(ARTWORK_FIELDS) | {'x', 'y'})
        if not body:
            abort(400, description="수정할 작품 정보를 하나 이상 보내 주세요.")
        for key, value in body.items():
            if key in {'x', 'y'}:
                if value is not None and (isinstance(value, bool) or not isinstance(value, (int, float))
                        or not -1e12 <= value <= 1e12 or not math.isfinite(value)):
                    abort(400, description='작품 좌표는 ±1e12 범위의 유한한 숫자 또는 null이어야 합니다.')
                continue
            if (not isinstance(value, str) or len(value) > ARTWORK_FIELDS[key]
                    or (key not in OPTIONAL_ARTWORK_FIELDS and not value.strip())):
                abort(400, description=f"{key}는 비어 있지 않은 {ARTWORK_FIELDS[key]}자 이내의 문자열이어야 합니다.")
        # 열 이름은 위의 고정된 허용 목록으로 제한하며, 값은 매개변수로 전달합니다.
        fields = ", ".join(f"{ARTWORK_COLUMNS.get(key, key)} = ?" for key in body)
        db = get_db()
        with db:
            db.execute(f"UPDATE Art SET {fields} WHERE artwork_index = ?",
                       [value.strip() if isinstance(value, str) else value for value in body.values()] + [index])
        return jsonify(find_artwork(index))

    @app.get("/api/robots")
    def list_robots():
        from flask import request
        active = request.args.get("active", "true")
        if active not in {"true", "false", "all"}:
            abort(400, description="active는 true, false 또는 all이어야 합니다.")
        if active == "all":
            rows = get_db().execute("SELECT * FROM Pose ORDER BY robot_id")
        else:
            rows = get_db().execute("SELECT * FROM Pose WHERE active = ? ORDER BY robot_id",
                                    (int(active == "true"),))
        return jsonify(robots=[robot_data(row) for row in rows])

    @app.get("/api/robots/<robot_id>")
    def get_robot(robot_id):
        return jsonify(robot_data(find_robot(robot_id)))

    @app.put("/api/robots/<robot_id>")
    def update_robot(robot_id):
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", robot_id):
            abort(400, description="로봇 ID는 영문, 숫자, 밑줄, 하이픈 1~64자입니다.")
        body = json_body({"active", "pose", "frame_id"})
        if not isinstance(body.get("active"), bool):
            abort(400, description="active는 true 또는 false여야 합니다.")
        if "pose" not in body:
            abort(400, description="pose를 보내 주세요. 위치를 모르면 null을 사용하세요.")
        pose = body["pose"]
        if pose is not None:
            if not isinstance(pose, dict) or set(pose) != {"x", "y", "theta"}:
                abort(400, description="pose는 x, y, theta를 모두 포함해야 합니다.")
            for value in pose.values():
                if (isinstance(value, bool) or not isinstance(value, (int, float))
                        or not -1e12 <= value <= 1e12 or not math.isfinite(value)):
                    abort(400, description="pose에는 유한한 숫자를 사용하세요. 허용 범위는 ±1e12입니다.")
        frame = body.get("frame_id", "map")
        if not isinstance(frame, str) or not frame.strip() or len(frame) > 100:
            abort(400, description="frame_id는 비어 있지 않은 100자 이내 문자열이어야 합니다.")
        db = get_db()
        with db:
            db.execute(
                "INSERT INTO Pose (robot_id, active, x, y, theta, frame_id, pose_updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?) ON CONFLICT(robot_id) DO UPDATE SET "
                "active=excluded.active, x=excluded.x, y=excluded.y, "
                "theta=excluded.theta, frame_id=excluded.frame_id, pose_updated_at=excluded.pose_updated_at",
                (robot_id, int(body["active"]), pose["x"] if pose else None,
                 pose["y"] if pose else None, pose["theta"] if pose else None,
                 frame.strip(), now_ms() if pose else None),
            )
        return jsonify(robot_data(find_robot(robot_id)))
