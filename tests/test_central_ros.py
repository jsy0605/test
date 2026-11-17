import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from central_ros import apply_ros_environment, ros_environment


class CentralRosTest(unittest.TestCase):
    def test_central_server_id_zero_uses_first_slot(self):
        env = ros_environment()
        self.assertEqual(env["ROS_DOMAIN_ID"], "1")
        self.assertEqual(env["ROS_DISCOVERY_SERVER"], "192.168.107.42:11811")
        self.assertNotIn("192.168.107.101", env["ROS_DISCOVERY_SERVER"])
        self.assertNotIn("192.168.107.104", env["ROS_DISCOVERY_SERVER"])
        self.assertEqual(env["ROS_SUPER_CLIENT"], "True")

    def test_existing_robot_server_list_is_replaced(self):
        with patch.dict(os.environ, {"ROS_DISCOVERY_SERVER": "robot1:11811;robot4:11811", "ROS_LOCALHOST_ONLY": "1"}):
            apply_ros_environment()
            self.assertEqual(os.environ["ROS_DISCOVERY_SERVER"], "192.168.107.42:11811")
            self.assertNotIn("ROS_LOCALHOST_ONLY", os.environ)

    def test_server_id_zero_has_no_empty_slot_and_invalid_config_is_atomic(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "config.json"
            config = {"ros_domain_id": 1, "discovery_server_id": 0,
                      "discovery_server_ip": "192.168.107.42", "discovery_server_port": 11811}
            path.write_text(json.dumps(config))
            self.assertEqual(ros_environment(path)["ROS_DISCOVERY_SERVER"], "192.168.107.42:11811")
            path.write_text(json.dumps({**config, "discovery_server_id": 1}))
            self.assertEqual(ros_environment(path)["ROS_DISCOVERY_SERVER"], ";192.168.107.42:11811")
            for key, value in (("ros_domain_id", True), ("discovery_server_id", -1),
                               ("discovery_server_ip", "<PC3_IP>"), ("discovery_server_ip", 123),
                               ("discovery_server_port", 65536)):
                with self.subTest(key=key), patch.dict(os.environ, {"ROS_DISCOVERY_SERVER": "original"}):
                    path.write_text(json.dumps({**config, key: value}))
                    with self.assertRaises(ValueError):
                        apply_ros_environment(path)
                    self.assertEqual(os.environ["ROS_DISCOVERY_SERVER"], "original")

    def test_guest_robot_is_added_only_with_confirmed_unique_id(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "config.json"
            config = {"ros_domain_id": 1, "discovery_server_id": 0,
                      "discovery_server_ip": "192.168.107.42", "discovery_server_port": 11811}
            robot = {"name": "tb1", "ip": "192.168.107.101", "server_id": None,
                     "port": 11811, "enabled": False}
            def write(**changes):
                path.write_text(json.dumps({**config, "additional_discovery_servers": [{**robot, **changes}]}))
            write()
            self.assertEqual(ros_environment(path)["ROS_DISCOVERY_SERVER"], "192.168.107.42:11811")
            write(enabled=True)
            with self.assertRaises(ValueError):
                ros_environment(path)
            write(enabled=True, server_id=0)
            with self.assertRaises(ValueError):
                ros_environment(path)
            write(enabled=True, server_id=1)
            self.assertEqual(ros_environment(path)["ROS_DISCOVERY_SERVER"],
                             "192.168.107.42:11811;192.168.107.101:11811")
            write(enabled=True, server_id=4)
            self.assertEqual(ros_environment(path)["ROS_DISCOVERY_SERVER"],
                             "192.168.107.42:11811;;;;192.168.107.101:11811")
