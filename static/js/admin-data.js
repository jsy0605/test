export const escape = value => String(value ?? '').replace(/[&<>"']/g, char => ({
  '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
}[char]));
export const formatTime = value => value == null ? '—' : new Date(value).toLocaleString('ko-KR', {timeZone:'Asia/Seoul', hour12:false}) + ' KST';
export function numericValue(value) {
  if (value === '' || value == null) return null;
  const number = Number(value);
  if (!Number.isFinite(number) || Math.abs(number) > 1e12) throw new Error('좌표는 ±1e12 범위의 숫자로 입력해 주세요.');
  return number;
}
export function artworkPayload(values, inline = false) {
  const payload = {...values};
  for (const axis of ['x','y']) if (axis in payload) payload[axis] = numericValue(payload[axis]);
  if (inline) {payload.title = payload.title_en; payload.artist_name = payload.artist_name_en;}
  return payload;
}
export function posePayload(values, active) {
  const pose = Object.fromEntries(['x','y','theta'].map(key => [key, numericValue(values[key])]));
  const present = Object.values(pose).filter(value => value !== null).length;
  if (present !== 0 && present !== 3) throw new Error('위치는 x·y·theta를 모두 입력하거나 모두 비워 주세요.');
  return {active, frame_id: values.frame_id, pose: present ? pose : null};
}
export function robotRows(robots) {
  return robots.length ? robots.map(robot => `<tr><th scope="row">${escape(robot.robot_id)}</th><td>${robot.pose ? escape(robot.pose.x) : '수신 전'}</td><td>${robot.pose ? escape(robot.pose.y) : '수신 전'}</td><td>${robot.pose ? escape(robot.pose.theta) : '수신 전'}</td><td>${robot.active ? '활성' : '비활성'}</td><td>${escape(robot.frame_id)}</td><td>${escape(formatTime(robot.pose_updated_at))}</td></tr>`).join('') : '<tr><td colspan="7" class="empty">등록된 로봇이 없습니다.</td></tr>';
}
export function logRows(logs) {
  return logs.length ? logs.map(entry => `<tr><td>${escape(entry.log_id)}</td><td>${escape(entry.robot_id)}</td><td>${escape(formatTime(entry.sent_at))}</td><td>${escape(entry.message)}</td></tr>`).join('') : '<tr><td colspan="4" class="empty">조건에 맞는 수신 로그가 없습니다.</td></tr>';
}
