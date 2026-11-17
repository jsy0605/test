"""Explicit isolated ROS integration fixture. Never starts with the kiosk.
ROS_DOMAIN_ID=181 ROS_LOCALHOST_ONLY=1 python3 tests/ros_preparation_check.py [--serve]
"""
import os
import sys
import tempfile
import threading
import time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main():
    if os.environ.get('ROS_DOMAIN_ID') != '181' or os.environ.get('ROS_LOCALHOST_ONLY') != '1':
        raise SystemExit('Use isolated ROS_DOMAIN_ID=181 and ROS_LOCALHOST_ONLY=1 for this fixture.')
    import rclpy
    from rclpy.context import Context
    from rclpy.executors import MultiThreadedExecutor
    from rclpy.callback_groups import ReentrantCallbackGroup
    from rclpy.action import ActionServer, CancelResponse
    from arti_interfaces.srv import CallRobot
    from arti_interfaces.action import MoveToKiosk, RegisterVisitor
    from arti_interfaces.msg import TourReady
    from std_msgs.msg import Bool
    from robot_preparation import RosPreparationTransport, PreparationManager

    context = Context()
    rclpy.init(context=context, args=['--ros-args','--disable-external-lib-logs'])
    node = rclpy.create_node('arti_test_robot', context=context, enable_rosout=False)
    group = ReentrantCallbackGroup()
    available = node.create_publisher(Bool, '/is_available', 1)
    ready = node.create_publisher(TourReady, '/arti/tour_ready', 10)
    ready_sessions = set()
    ready_lock = threading.Lock()

    def publish():
        available.publish(Bool(data=True))
        with ready_lock:
            ids = list(ready_sessions)
        for session_id in ids:
            ready.publish(TourReady(session_id=session_id, robot_id='robot2', ready=True, message='모의 로봇 준비 완료'))
    node.create_timer(.2, publish, callback_group=group)

    def call(request, response):
        response.accepted = 'reject' not in request.session_id
        response.robot_id, response.robot_namespace = 'robot2', '/robot2'
        response.message = '모의 배정 완료' if response.accepted else '배정 가능한 로봇 없음'
        return response
    node.create_service(CallRobot, '/arti/call_robot', call, callback_group=group)

    def execute(handle, action_type):
        session_id = handle.request.session_id
        result = action_type.Result()
        for i in range(12):
            if handle.is_cancel_requested:
                handle.canceled()
                result.success, result.message = False, '취소 확인'
                return result
            handle.publish_feedback(action_type.Feedback(progress=i/12, message='모의 작업 진행 중'))
            time.sleep(.1)
        result.success, result.message = True, '모의 작업 완료'
        if action_type is RegisterVisitor:
            result.visitor_id = 'visitor-test'
            # Deliberately deliver ready before the result to exercise that race.
            with ready_lock:
                ready_sessions.add(session_id)
            ready.publish(TourReady(session_id=session_id, robot_id='robot2', ready=True, message='모의 준비 완료'))
            time.sleep(.1)
        handle.succeed()
        return result
    servers = [ActionServer(node, cls, '/robot2/'+name,
        execute_callback=lambda handle, cls=cls: execute(handle, cls),
        cancel_callback=lambda _: CancelResponse.ACCEPT, callback_group=group)
        for cls, name in [(MoveToKiosk,'move_to_kiosk'),(RegisterVisitor,'register_visitor')]]
    executor = MultiThreadedExecutor(num_threads=4, context=context)
    executor.add_node(node)
    thread = threading.Thread(target=executor.spin, daemon=True)
    thread.start()
    manager = None
    availability_monitor = None
    try:
        if '--serve' in sys.argv:
            from app import create_app
            with tempfile.TemporaryDirectory(prefix='arti-ros-ui-') as directory:
                app = create_app({'DATABASE':Path(directory)/'test.sqlite3'})
                manager = app.extensions['robot_preparation']
                availability_monitor = app.extensions['robot_availability']
                app.run(host='127.0.0.1', port=5001, debug=False)
        else:
            transport = RosPreparationTransport(discovery_timeout=5, action_timeout=10)
            manager = PreparationManager(transport)
            transport.start(manager.receive_ready)
            def wait_for(job, phase, timeout=12):
                deadline = time.monotonic()+timeout
                while job.snapshot()['phase'] != phase:
                    if time.monotonic() > deadline or job.phase == 'error':
                        raise AssertionError(job.snapshot())
                    time.sleep(.02)
            def start(session_id):
                return manager.start(dict(id=session_id, mode='course', courseId='A', artworkIds=['art-01']))
            job = start('ros-success')
            wait_for(job,'arrived')
            assert job.robot_id == 'robot2'
            manager.register(job)
            wait_for(job,'ready')
            assert job.visitor_id == 'visitor-test'
            job = start('ros-cancel')
            deadline = time.monotonic()+5
            while not job.motion_pending:
                assert time.monotonic() < deadline, job.snapshot()
                time.sleep(.01)
            manager.cancel_job(job)
            assert job.phase == 'cancelled' and not job.motion_pending
            job = start('ros-reject')
            wait_for(job,'error')
            print('Native ROS integration passed: service assignment, action feedback/results, early ready topic, action cancellation and service rejection.', flush=True)
    finally:
        if manager:
            manager.stop()
        if availability_monitor:
            availability_monitor.stop()
        executor.shutdown(timeout_sec=2)
        thread.join(timeout=2)
        for server in servers:
            server.destroy()
        node.destroy_node()
        context.shutdown()


if __name__ == '__main__':
    main()
