import {artworkPayload, posePayload, robotRows, logRows} from './admin-data.js';
import {bindLogReset} from './admin-log-reset.js';
const csrf = () => document.querySelector('meta[name="csrf-token"]').content;
async function jsonRequest(url, options = {}) {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 5000);
  const abort = () => controller.abort();
  options.signal?.addEventListener('abort', abort, {once:true});
  if (options.signal?.aborted) abort();
  try {
    const response = await fetch(url, {cache:'no-store', ...options, signal:controller.signal});
    const data = await response.json();
    if (!response.ok) throw new Error(data.error?.message || '요청을 처리하지 못했습니다.');
    return data;
  } catch (error) {
    if (error.name === 'AbortError') throw new Error('서버 응답이 지연되고 있습니다. 다시 시도해 주세요.');
    if (error instanceof TypeError) throw new Error('서버 연결을 확인해 주세요.');
    throw error;
  } finally {clearTimeout(timeout); options.signal?.removeEventListener('abort', abort);}
}
const writeOptions = (method, payload) => ({method, headers:{'Content-Type':'application/json','X-CSRF-Token':csrf()}, body:JSON.stringify(payload)});
const artworkForms = [...document.querySelectorAll('.artwork-row-form, .artwork-form')];
document.addEventListener('input', event => {
  const form = event.target.form;
  if (!form) return;
  if (form.matches('.artwork-row-form, .artwork-form, #robot-edit-form')) form.dataset.dirty = 'true';
});
function updateArtworkForms(index, data, savedForm) {
  for (const form of artworkForms.filter(form => form.dataset.index === index)) {
    if (form !== savedForm && form.dataset.dirty === 'true') continue;
    for (const field of form.elements) if (field.name in data) field.value = data[field.name] ?? '';
    const heading = form.querySelector('h3');
    if (heading) heading.textContent = `${data.artwork_code} · ${data.title}`;
  }
}
for (const form of artworkForms) form.addEventListener('submit', async event => {
  event.preventDefault();
  const button = form.querySelector('button');
  const message = form.querySelector('.save-message');
  if (button.disabled) return;
  const controls = [...form.elements];
  try {
    const payload = artworkPayload(Object.fromEntries(new FormData(form)), form.matches('.artwork-row-form'));
    controls.forEach(control => {control.disabled = true;});
    message.textContent = '저장 중…';
    const data = await jsonRequest(`/api/artworks/${form.dataset.index}`, writeOptions('PATCH', payload));
    form.dataset.dirty = 'false';
    updateArtworkForms(form.dataset.index, data, form);
    message.textContent = '저장 완료 · 키오스크에 자동 반영';
  } catch (error) {
    message.textContent = error.message || '서버 연결을 확인해 주세요.';
  } finally {controls.forEach(control => {control.disabled = false;});}
});

let stopped = false;
const filters = document.querySelector('#log-filters');
const pageState = document.querySelector('#log-page-state');
let offset = Number(pageState.dataset.offset), limit = Number(pageState.dataset.limit), total = Number(pageState.dataset.total);
let logController = null, requestNumber = 0, logTimer = null;
let appliedLogFilters = new URLSearchParams(new FormData(filters));
function applyLogFilters() { appliedLogFilters = new URLSearchParams(new FormData(filters)); }
const previous = document.querySelector('#log-previous'), next = document.querySelector('#log-next');
function pagination() {previous.disabled = offset === 0; next.disabled = offset + limit >= total;}
async function loadLogs(requestedOffset = 0) {
  const number = ++requestNumber;
  logController?.abort(); logController = new AbortController();
  const controller = logController;
  const timeout = setTimeout(() => controller.abort(), 5000);
  clearTimeout(logTimer);
  const query = new URLSearchParams(appliedLogFilters);
  for (const [key, value] of [...query]) if (value === '') query.delete(key);
  query.set('offset', requestedOffset);
  const message = document.querySelector('#log-message');
  message.textContent = '로봇 로그를 조회하고 있습니다…';
  previous.disabled = next.disabled = true;
  try {
    const data = await jsonRequest('/api/logs?' + query.toString(), {signal:controller.signal});
    if (stopped || number !== requestNumber) return;
    offset = data.offset; limit = data.limit; total = data.total;
    document.querySelector('#log-rows').innerHTML = logRows(data.logs);
    document.querySelector('#log-total').textContent = `${total}건`;
    const start = data.logs.length ? offset + 1 : 0;
    const end = data.logs.length ? offset + data.logs.length : 0;
    document.querySelector('#log-range').textContent = `${start}–${end} / ${total}`;
    message.textContent = `검색 결과 ${total}건`;
    history.replaceState(null, '', '/data?' + query.toString());
  } catch (error) {
    if (!stopped && number === requestNumber) message.textContent = error.message || '로그를 조회하지 못했습니다.';
  } finally {
    clearTimeout(timeout);
    if (number === requestNumber) {logController = null; pagination(); scheduleLogs();}
  }
}
function scheduleLogs() {
  clearTimeout(logTimer);
  if (!stopped) logTimer = setTimeout(() => {if (!document.hidden && filters.closest('details').open) void loadLogs(offset); else scheduleLogs();}, 1000);
}
filters.addEventListener('submit', event => {event.preventDefault(); applyLogFilters(); void loadLogs(0);});
document.querySelector('#reset-log-filters').addEventListener('click', () => {
  for (const name of ['q','robot_id','date']) filters.elements[name].value = '';
  applyLogFilters(); void loadLogs(0);
});
bindLogReset({request:jsonRequest, writeOptions, onReset: async () => {
  for (const name of ['q','robot_id','date']) filters.elements[name].value = '';
  applyLogFilters(); await loadLogs(0);
}});
previous.addEventListener('click', () => void loadLogs(Math.max(0, offset - limit)));
next.addEventListener('click', () => void loadLogs(offset + limit));
document.querySelector('#refresh-logs').addEventListener('click', () => void loadLogs(offset));
window.addEventListener('pagehide', () => {stopped = true; clearTimeout(logTimer); logController?.abort();});
window.addEventListener('pageshow', event => {if (event.persisted) {stopped = false;  void loadLogs(offset);}});


scheduleLogs();
