import { subscribeSystemMetrics } from './system-monitor-feed.js';

const node = id => document.getElementById(id);
const history = [];
let stopPolling;
let authorizationExpired = false;
const text = (id, value) => { node(id).textContent = value; };
const clockTime = value => new Date(value).toLocaleTimeString('ko-KR', { timeZone: 'Asia/Seoul', hour12: false });

function bytes(value) {
  const units = ['B', 'KiB', 'MiB', 'GiB', 'TiB'];
  const index = value > 0 ? Math.min(units.length - 1, Math.floor(Math.log(value) / Math.log(1024))) : 0;
  return `${(value / 1024 ** index).toFixed(index ? 1 : 0)} ${units[index]}`;
}

function duration(seconds) {
  const days = Math.floor(seconds / 86400);
  const hours = Math.floor(seconds % 86400 / 3600);
  const minutes = Math.floor(seconds % 3600 / 60);
  return `${days ? `${days}일 ` : ''}${hours ? `${hours}시간 ` : ''}${minutes}분 ${Math.floor(seconds % 60)}초`;
}

function renderChart() {
  const first = history[0].sampled_at;
  const last = history.at(-1).sampled_at;
  const x = sample => history.length === 1 ? 885 : 40 + (sample.sampled_at - first) / (last - first) * 845;
  const y = value => 175 - value / 100 * 160;
  const groups = [[]];
  for (const sample of history) {
    if (groups.at(-1).length && sample.sampled_at - groups.at(-1).at(-1).sampled_at > 5000) groups.push([]);
    groups.at(-1).push(sample);
  }
  node('chart-series').innerHTML = ['cpu', 'memory', 'disk'].map(key => {
    const lines = groups.map(group => `<polyline class="chart-line" stroke="var(--${key})" points="${group.map(sample => `${x(sample).toFixed(2)},${y(sample[key].percent).toFixed(2)}`).join(' ')}"/>`).join('');
    return `${lines}<circle cx="885" cy="${y(history.at(-1)[key].percent).toFixed(2)}" r="3" fill="var(--${key})"/>`;
  }).join('');
  node('chart-empty').hidden = true;
  node('usage-chart').setAttribute('aria-label', `CPU, 메모리, 디스크의 실제 사용률 추이. 최근 ${history.length}회 측정.`);
  text('chart-caption', `최근 ${history.length}회 측정 · 최대 3분 · 페이지를 새로 열면 초기화`);
  text('chart-from', clockTime(first));
  text('chart-to', `${clockTime(last)} KST`);
}

function renderMetrics(data) {
  text('host-name', data.host.name);
  for (const key of ['cpu', 'memory', 'disk']) {
    const percent = data[key].percent;
    text(`${key}-value`, percent.toFixed(1));
    const meter = node(`${key}-meter`);
    meter.setAttribute('aria-valuenow', percent.toFixed(1));
    meter.querySelector('i').style.width = `${percent}%`;
    const badge = node(`${key}-badge`);
    badge.textContent = percent >= 90 ? '사용량 높음' : percent >= 80 ? '사용량 주의' : '여유';
    badge.classList.toggle('high', percent >= 80);
  }
  text('cpu-detail', data.host.logical_cpus ? `논리 CPU ${data.host.logical_cpus}개 · 전체 기기 사용률` : '전체 기기 사용률');
  text('memory-detail', `${bytes(data.memory.used_bytes)} / ${bytes(data.memory.total_bytes)} 사용 · 사용 가능 ${bytes(data.memory.available_bytes)}`);
  text('disk-detail', `${bytes(data.disk.used_bytes)} / ${bytes(data.disk.total_bytes)} 사용 · 남은 공간 ${bytes(data.disk.free_bytes)}`);
  text('host-os', data.host.os);
  text('host-uptime', duration(data.host.uptime_seconds));
  text('server-uptime', duration(data.server.uptime_seconds));
  text('updated-at', `마지막 측정 ${clockTime(data.sampled_at)} KST`);
  if (history.length && data.sampled_at <= history.at(-1).sampled_at) history.length = 0;
  history.push(data);
  while (history.length > 90 || history[0].sampled_at < data.sampled_at - 180000) history.shift();
  renderChart();
}

function renderState(state) {
  const connection = node('connection-state');
  connection.classList.toggle('live', state === 'live');
  connection.classList.toggle('error', ['error', 'unauthorized'].includes(state));
  text('connection-state', { loading: '측정값을 불러오는 중…', live: '실시간 측정 중 · 2초 갱신', error: '갱신 중단 · 재연결 중', unauthorized: '관리자 로그인 만료' }[state]);
  if (state === 'live') {
    node('error-notice').hidden = true;
    text('server-status', '응답 정상');
  } else if (state === 'error' || state === 'unauthorized') {
    node('error-notice').hidden = false;
    node('login-again').hidden = state !== 'unauthorized';
    text('error-text', state === 'unauthorized' ? '관리자 로그인이 만료됐습니다. 다시 로그인해 주세요.' : '최신 사용량을 가져오지 못했습니다. 표시된 값은 마지막 측정값이며 자동으로 다시 연결합니다.');
    text('server-status', '최신 응답 확인 불가');
    if (state === 'unauthorized') authorizationExpired = true;
  }
}

function connect() {
  stopPolling?.();
  if (!document.hidden && !authorizationExpired) stopPolling = subscribeSystemMetrics(renderMetrics, renderState);
}
document.addEventListener('visibilitychange', () => { if (document.hidden) stopPolling?.(); else connect(); });
window.addEventListener('pagehide', () => stopPolling?.());
window.addEventListener('pageshow', event => { if (event.persisted) connect(); });
connect();
