"""/is_available (std_msgs/msg/Bool) 구독과 브라우저용 1Hz 상태 스트림."""

import atexit
import json
import os
import threading
import time

from flask import Response, abort, jsonify, request


from fleet import Fleet


class RobotAvailability:
    def __init__(self, topic="/is_available", stale_after=3.5, clock=time.monotonic):
        self.fleet = Fleet()
        self.topic = topic
        self.stale_after = stale_after
        self.clock = clock
        self._lock = threading.Lock()
        self._value = None
        self._received_at = None
        self._failed = False
        self._stop = threading.Event()
        self._thread = None
        self._ros_ready = False
        self._dev_value = None

    def update(self, value):
        if type(value) is not bool:
            raise ValueError("is_available 값은 bool이어야 합니다.")
        with self._lock:
            self._value = value
            self._received_at = self.clock()
            self._failed = False

    def snapshot(self):
        with self._lock:
            # 리뷰: 로봇 상태를 한 번도 받지 않아도 unavailable을 반환한다.
            # 기존 테스트가 기대하는 waiting을 호출 불가와 구분할지 확인이 필요하다.
            value = any(row["available"] for row in self.fleet.snapshot().values())
            status = "disconnected" if self._failed else ("available" if value else "unavailable")
            return {
                "topic": self.topic,
                "status": status,
                "available": value if status in {"available", "unavailable"} else None,
                "dev_ready": self._ros_ready,
                "dev_value": self._dev_value,
            }

    def toggle_dev(self):
        with self._lock:
            # 리뷰: _ros_ready가 True로 설정되지 않아 개발용 토글 요청은 503을 반환한다.
            # Fleet 전환 후에도 이 기능을 유지할지 확인이 필요하다.
            if not self._ros_ready:
                raise RuntimeError("ROS 2 연결을 준비하고 있어요. 잠시 후 다시 시도해 주세요.")
            current = self._dev_value
            if current is None:
                fresh = self._received_at is not None and self.clock() - self._received_at <= self.stale_after
                current = self._value if fresh else False
            self._dev_value = not current
            return self._dev_value

    def stop_dev(self):
        with self._lock:
            self._dev_value = None

    def publish_dev(self, publisher, message_type):
        with self._lock:
            value = self._dev_value
        if value is not None:
            publisher.publish(message_type(data=value))

    def start(self, logger):
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._receive, args=(logger,), daemon=True)
        self._thread.start()

    def _receive(self, logger):
        context = node = executor = None
        try:
            import rclpy
            from rclpy.context import Context
            from rclpy.executors import SingleThreadedExecutor
            from rclpy.qos import qos_profile_sensor_data
            from std_msgs.msg import Bool

            context = Context()
            rclpy.init(context=context, args=["--ros-args", "--disable-external-lib-logs"])
            node = rclpy.create_node(
                "arti_kiosk_availability", context=context,
                enable_rosout=False, start_parameter_services=False,
            )
            self.fleet.subscribe(node, qos_profile_sensor_data)
            executor = SingleThreadedExecutor(context=context)
            executor.add_node(node)
            with self._lock:
                self._ros_ready = False
            logger.info("로봇 가용 상태 구독 시작: %s (std_msgs/msg/Bool)", self.topic)
            while not self._stop.is_set() and context.ok():
                executor.spin_once(timeout_sec=0.2)
        except Exception:
            with self._lock:
                self._failed = True
            logger.exception("로봇 가용 상태 토픽을 구독하지 못했습니다.")
        finally:
            with self._lock:
                self._ros_ready = False
                self._dev_value = None
            if executor:
                executor.shutdown(timeout_sec=1)
            if node:
                node.destroy_node()
            if context and context.ok():
                context.shutdown()

    def stop(self):
        self._stop.set()
        if self._thread and self._thread is not threading.current_thread():
            self._thread.join(timeout=2)


def register_robot_availability(app):
    topic = os.environ.get("ARTI_AVAILABILITY_TOPIC", "/is_available")
    monitor = app.config.get("AVAILABILITY_MONITOR") or RobotAvailability(topic=topic)
    app.extensions["robot_availability"] = monitor

    @app.get("/api/fleet")
    def fleet_status():
        if not app.extensions["admin_auth"]["current_admin"]():
            abort(401)
        return jsonify(monitor.fleet.snapshot())

    @app.post("/api/dev/availability")
    def developer_availability():
        if request.remote_addr not in {"127.0.0.1", "::1"}:
            abort(403, description="dev1은 로컬 개발 화면에서만 사용할 수 있어요.")
        if not request.is_json:
            abort(415, description="JSON 형식으로 요청해 주세요.")
        body = request.get_json()
        if (not isinstance(body, dict) or set(body) != {"action"}
                or not isinstance(body["action"], str) or body["action"] not in {"toggle", "stop"}):
            abort(400, description="action은 toggle 또는 stop이어야 합니다.")
        if body["action"] == "stop":
            monitor.stop_dev()
        else:
            try:
                monitor.toggle_dev()
            except RuntimeError as error:
                abort(503, description=str(error))
        return jsonify(monitor.snapshot())

    @app.get("/api/availability/stream")
    def availability_stream():
        def events():
            while True:
                yield "event: availability\ndata: " + json.dumps(monitor.snapshot()) + "\n\n"
                time.sleep(1)

        return Response(events(), mimetype="text/event-stream", headers={
            "Cache-Control": "no-store", "X-Accel-Buffering": "no",
        })

    if not app.testing and app.config.get("ROS_AVAILABILITY_ENABLED", True):
        monitor.start(app.logger)
        atexit.register(monitor.stop)
