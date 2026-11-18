# 로봇별 네임스페이스의 배터리, 도크, odom 토픽을 구독한다.
# 콜백에 로봇 이름을 고정해 두 로봇의 수신값을 구분한다.

import json
import threading
import time
from pathlib import Path


class Fleet:
    def __init__(self):
        self.names = json.loads((Path(__file__).parent / "config/fleet.json").read_text())
        self.values = {name: {} for name in self.names}
        self.lock = threading.Lock()

    def receive(self, name, field, value):
        with self.lock:
            self.values[name][field] = (time.monotonic(), value)

    def snapshot(self):
        with self.lock:
            now = time.monotonic()
            rows = {}
            for name, fields in self.values.items():
                # 리뷰: 도킹 해제 메시지를 놓치면 마지막 도킹 수신 후 최대 15초 동안
                # 호출 가능으로 보일 수 있다. 운영에서 허용할 수 있는 지연인지 확인이 필요하다.
                row = {key: value if now - stamp <= (3 if key == "moving" else 15) else None
                       for key, (stamp, value) in fields.items()}
                row["available"] = row.get("dock") is True and (row.get("battery") or 0) > 30
                rows[name] = row
            return rows

    def subscribe(self, node, qos):
        from sensor_msgs.msg import BatteryState
        from irobot_create_msgs.msg import DockStatus
        from nav_msgs.msg import Odometry
        from math import hypot
        for name, namespace in self.names.items():
            node.create_subscription(BatteryState, namespace + "/battery_state",
                lambda msg, n=name: self.receive(n, "battery", round(msg.percentage * 100, 5)
                    if 0 <= msg.percentage <= 1 else None), qos)
            node.create_subscription(DockStatus, namespace + "/dock_status",
                lambda msg, n=name: self.receive(n, "dock", msg.is_docked), qos)
            node.create_subscription(Odometry, namespace + "/odom",
                lambda msg, n=name: self.receive(n, "moving",
                    hypot(msg.twist.twist.linear.x, msg.twist.twist.linear.y) > 0.01 or abs(msg.twist.twist.angular.z) > 0.01), qos)
