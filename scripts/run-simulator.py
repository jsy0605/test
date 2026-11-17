"""Run python3 scripts/run-simulator.py; deliberately imports no ROS transport."""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from signal_simulator import ManualTransport
from robot_availability import RobotAvailability
from app import create_app
root=Path(__file__).resolve().parents[1]
transport=ManualTransport()
app=create_app({'CENTRAL_ROS_ENABLED':False,'ROS_AVAILABILITY_ENABLED':False,
    'DATABASE':root/'instance/simulator/arti.sqlite3','PREPARATION_TRANSPORT':transport,
    'SIGNAL_SIMULATOR':transport,'AVAILABILITY_MONITOR':RobotAvailability()})
app.config['SESSION_COOKIE_NAME']='arti_sim_admin_session'
app.extensions['robot_preparation'].ready_timeout=86400
if __name__=='__main__':app.run(host='127.0.0.1',port=5003,debug=False,use_reloader=False)
