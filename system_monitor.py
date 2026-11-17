"""Flask가 실행되는 기기의 실제 자원 사용량. 조회 시에만 측정합니다."""

import platform
import time
from pathlib import Path

import psutil
from flask import jsonify, render_template


class SystemMonitor:
    def __init__(self, disk_path, clock=time.monotonic, wall_clock=time.time):
        self.disk_path = Path(disk_path).resolve()
        self.clock = clock
        self.wall_clock = wall_clock
        self.started = clock()
        self.started_at = wall_clock()

    def snapshot(self):
        # 각 HTTP 요청의 스레드에서도 첫 호출부터 실제 구간 측정값을 얻습니다.
        cpu_percent = psutil.cpu_percent(interval=0.1)
        memory = psutil.virtual_memory()
        disk = psutil.disk_usage(str(self.disk_path))
        now = self.wall_clock()
        return {
            "sampled_at": int(now * 1000),
            "refresh_interval_ms": 2000,
            "host": {
                "name": platform.node() or "이 기기",
                "os": f"{platform.system()} {platform.release()}",
                "logical_cpus": psutil.cpu_count(logical=True),
                "uptime_seconds": int(max(0, now - psutil.boot_time())),
            },
            "cpu": {"percent": cpu_percent},
            "memory": {
                "percent": memory.percent,
                "total_bytes": memory.total,
                "used_bytes": memory.total - memory.available,
                "available_bytes": memory.available,
            },
            "disk": {
                "percent": disk.percent,
                "total_bytes": disk.total,
                "used_bytes": disk.used,
                "free_bytes": disk.free,
                "path": str(self.disk_path),
            },
            "server": {
                "status": "running",
                "started_at": int(self.started_at * 1000),
                "uptime_seconds": int(max(0, self.clock() - self.started)),
            },
        }


def register_system_monitor(app):
    monitor = app.config.get("SYSTEM_MONITOR") or SystemMonitor(Path(app.config["DATABASE"]).parent)
    app.extensions["system_monitor"] = monitor

    @app.get("/sysmon")
    def system_monitor_page():
        return render_template("system_monitor.html")

    @app.get("/api/system/metrics")
    def system_metrics():
        try:
            return jsonify(monitor.snapshot())
        except (OSError, psutil.Error):
            app.logger.exception("시스템 사용량 측정 실패")
            return jsonify(error={"message": "시스템 사용량을 읽지 못했습니다. 잠시 후 다시 시도합니다."}), 503
