# Arti
PC3용 ROS 2 Jazzy 키오스크 및 중앙 관제 웹앱입니다. Flask와 SQLite를 사용합니다.
로봇 네임스페이스는 config/fleet.json, Discovery 서버 설정은 config/central_ros.json에 있습니다.

## 실행
프로젝트 루트에서 실행합니다.
```bash
source /opt/ros/jazzy/setup.bash
python3 -m venv --system-site-packages .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
bash scripts/build-interfaces.sh
bash scripts/run-dev.sh
```

키오스크는 http://127.0.0.1:5000/ , 관리자 화면은 /data 입니다.
계정과 운영 DB는 각 PC의 instance 디렉터리에 생성됩니다.
