# Guest PC: 중앙 Discovery 서버 ID 0, ROS_DOMAIN_ID 1
# ROS 2 Jazzy (이 PC에 설치된 배포판)
source /opt/ros/jazzy/setup.bash
unset ROS_LOCALHOST_ONLY
export RMW_IMPLEMENTATION=rmw_fastrtps_cpp
export ROS_DOMAIN_ID=1
export ROS_DISCOVERY_SERVER=192.168.107.42:11811
export ROS_SUPER_CLIENT=True
export ROS_AUTOMATIC_DISCOVERY_RANGE=SUBNET
