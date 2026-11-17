#!/usr/bin/env bash
# 사용: source scripts/central-ros-env.bash
if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
  echo '현재 터미널에 적용하려면 source scripts/central-ros-env.bash를 사용하세요.' >&2
  exit 1
fi

_arti_load_central_ros() {
  local project_root settings
  project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)" || return
  # 검증에 실패하면 기존 환경을 바꾸지 않습니다. 값은 Python에서 검증·인용됩니다.
  settings="$(python3 "$project_root/central_ros.py")" || return
  source /opt/ros/jazzy/setup.bash || return
  if [[ -f "$project_root/ros2_ws/install/local_setup.bash" ]]; then
    source "$project_root/ros2_ws/install/local_setup.bash" || return
  fi
  eval "$settings"
}

if _arti_load_central_ros; then
  unset -f _arti_load_central_ros
  return 0
else
  unset -f _arti_load_central_ros
  return 1
fi
