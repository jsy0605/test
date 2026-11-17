#!/usr/bin/env bash
set -e
cd "$(dirname "$0")/.."
# ROS Jazzy's CMake file(STRINGS) reader splits UTF-8 build paths.
# Keep generated IDL/build files under an ASCII path; installed files stay in this project.
arti_build_dir=$(mktemp -d /tmp/arti-interfaces-build.XXXXXX)
trap 'rm -rf "$arti_build_dir"' EXIT
colcon --log-base ros2_ws/log build --base-paths ros2_ws/src \
  --build-base "$arti_build_dir" --install-base ros2_ws/install \
  --packages-select arti_interfaces --cmake-args -DPython3_EXECUTABLE=/usr/bin/python3
