"""프로젝트 전용 중앙 서버 접속 설정. 전역 .bashrc는 수정하지 않습니다."""

import ipaddress
import json
import os
import shlex
from pathlib import Path

CONFIG_PATH = Path(__file__).resolve().parent / "config" / "central_ros.json"


def ros_environment(path=CONFIG_PATH):
    config = json.loads(Path(path).read_text(encoding="utf-8"))
    fields = {"ros_domain_id", "discovery_server_ip", "discovery_server_id", "discovery_server_port"}
    if (not isinstance(config, dict) or not fields.issubset(config)
            or set(config) - fields - {"additional_discovery_servers"}):
        raise ValueError("중앙 ROS 설정 항목을 확인해 주세요.")
    for key, minimum, maximum in (("ros_domain_id", 0, 232), ("discovery_server_id", 0, 255),
                                  ("discovery_server_port", 1, 65535)):
        if type(config[key]) is not int or not minimum <= config[key] <= maximum:
            raise ValueError(f"{key}는 {minimum}~{maximum} 사이 정수여야 합니다.")
    if not isinstance(config["discovery_server_ip"], str):
        raise ValueError("중앙 서버 IP는 문자열이어야 합니다.")
    address = ipaddress.IPv4Address(config["discovery_server_ip"])
    if address.is_unspecified or address.is_multicast or address == ipaddress.IPv4Address("255.255.255.255"):
        raise ValueError("중앙 서버의 유니캐스트 IP를 지정해 주세요.")
    servers = {config["discovery_server_id"]: f"{address}:{config['discovery_server_port']}"}
    additional = config.get("additional_discovery_servers", [])
    if not isinstance(additional, list):
        raise ValueError("추가 Discovery 서버 목록은 배열이어야 합니다.")
    for server in additional:
        if not isinstance(server, dict) or set(server) != {"name", "ip", "server_id", "port", "enabled"}:
            raise ValueError("추가 Discovery 서버 항목을 확인해 주세요.")
        if not isinstance(server["name"], str) or not server["name"].strip() or type(server["enabled"]) is not bool:
            raise ValueError("추가 서버 이름과 enabled 값을 확인해 주세요.")
        if not isinstance(server["ip"], str):
            raise ValueError("추가 서버 IP는 문자열이어야 합니다.")
        robot_address = ipaddress.IPv4Address(server["ip"])
        if robot_address.is_unspecified or robot_address.is_multicast or int(robot_address) == 0xffffffff:
            raise ValueError("추가 서버의 유니캐스트 IP를 지정해 주세요.")
        if type(server["port"]) is not int or not 1 <= server["port"] <= 65535:
            raise ValueError("추가 서버 포트가 올바르지 않습니다.")
        server_id = server["server_id"]
        if server_id is not None and (type(server_id) is not int or not 0 <= server_id <= 255):
            raise ValueError("추가 Discovery Server ID는 0~255 사이 정수여야 합니다.")
        if not server["enabled"]:
            continue
        if server_id is None:
            raise ValueError(f"{server['name']}의 실제 Discovery Server ID를 먼저 확인해 주세요.")
        if server_id in servers:
            raise ValueError("Discovery Server ID가 중복됩니다.")
        servers[server_id] = f"{robot_address}:{server['port']}"
    # 목록의 위치가 서버 ID이므로, 비어 있는 ID 슬롯도 보존합니다.
    locator = ";".join(servers.get(index, "") for index in range(max(servers) + 1))
    return {
        "RMW_IMPLEMENTATION": "rmw_fastrtps_cpp",
        "ROS_DOMAIN_ID": str(config["ros_domain_id"]),
        "ROS_DISCOVERY_SERVER": locator,
        "ROS_SUPER_CLIENT": "True",
        "ROS_AUTOMATIC_DISCOVERY_RANGE": "SUBNET",
    }


def apply_ros_environment(path=CONFIG_PATH):
    environment = ros_environment(path)
    os.environ.pop("ROS_LOCALHOST_ONLY", None)
    os.environ.update(environment)
    return environment


if __name__ == "__main__":
    environment = ros_environment()
    print("unset ROS_LOCALHOST_ONLY")
    for key, value in environment.items():
        print(f"export {key}={shlex.quote(value)}")
