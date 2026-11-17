import assert from 'node:assert/strict';
import { watchCatalog } from '../static/js/catalog-feed.js';
import { loadCatalog, artworks } from '../static/js/data.js';
import { courseSelection } from '../static/js/course-selection.js';
const tick = () => new Promise(resolve => setImmediate(resolve));
function environment() {
  let id = 0;
  const timers = new Map(), listeners = new Map();
  const document = {hidden: false, addEventListener: (key, fn) => listeners.set(key, fn), removeEventListener: key => listeners.delete(key)};
  return {timers, listeners, document,
    options: {documentImpl: document, setTimeoutImpl: (fn, delay) => {timers.set(++id, {fn, delay}); return id;}, clearTimeoutImpl: id => timers.delete(id)},
    async run(delay) {
      const [key, timer] = [...timers].find(([, timer]) => timer.delay === delay);
      timers.delete(key); timer.fn(); await tick();
    },
  };
}

// 같은 페이지에서 DB/API 응답이 바뀌면 표와 선택 경로가 최신 값을 사용합니다.
{
  let row = {artwork_index: 1, artwork_id: '001', title: 'artwork1', title_en: 'artwork1', artist_name: 'artist1', artist_name_en: 'artist1', location: 'location1', theme: 'theme1', description: 'description1'};
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async (url, options) => {
    assert.equal(url, '/api/catalog'); assert.equal(options.cache, 'no-store');
    return {ok: true, json: async () => ({artworks: [row], courses: []})};
  };
  try {
    assert.equal(await loadCatalog(), true);
    assert.equal(await loadCatalog(), false, 'Unchanged content must not reset the checkbox DOM');
    row = {...row, title_en: 'Updated from SQL', artist_name_en: 'New Artist', location: 'new-room', theme: 'updated-theme', description: 'New description'};
    assert.equal(await loadCatalog(), true);
    const markup = courseSelection(artworks, ['art-01']);
    for (const value of ['Updated from SQL','New Artist','new-room','updated-theme','New description']) assert(markup.includes(value));
    assert(markup.includes(' checked'), 'Catalog changes must preserve selected artwork IDs');
  } finally { globalThis.fetch = originalFetch; }
}
{
  const env = environment(), updates = [];
  let calls = 0, errors = 0;
  const stop = watchCatalog({...env.options,
    refresh: async () => {if (++calls === 2) throw new Error('offline'); return calls === 1;},
    onUpdate: changed => updates.push(changed), onError: () => errors++,
  });
  assert.equal(calls, 0);
  await env.run(3000); assert.deepEqual(updates, [true]);
  await env.run(3000); assert.equal(errors, 1);
  await env.run(3000); assert.deepEqual(updates, [true, false]);
  env.document.hidden = true; env.listeners.get('visibilitychange')();
  assert.equal(env.timers.size, 0);
  env.document.hidden = false; env.listeners.get('visibilitychange')(); await tick();
  assert.equal(calls, 4);
  stop(); assert.equal(env.timers.size, 0); assert.equal(env.listeners.size, 0);
}
{
  const env = environment(), updates = [];
  let signal, finish;
  const stop = watchCatalog({...env.options,
    refresh: options => {signal = options.signal; return new Promise(resolve => {finish = resolve;});},
    onUpdate: changed => updates.push(changed),
  });
  await env.run(3000);
  assert.deepEqual([...env.timers.values()].map(timer => timer.delay), [5000], 'No overlapping poll while one request is pending');
  stop(); assert.equal(signal.aborted, true);
  finish(true); await tick();
  assert.equal(updates.length, 0); assert.equal(env.timers.size, 0);
}
{
  const env = environment(); let errors = 0;
  const stop = watchCatalog({...env.options,
    refresh: ({signal}) => new Promise((resolve, reject) => signal.addEventListener('abort', () => reject(new Error('timeout')))),
    onUpdate: () => assert.fail('Timed out request must not update data'), onError: () => errors++,
  });
  await env.run(3000); await env.run(5000);
  assert.equal(errors, 1);
  assert.deepEqual([...env.timers.values()].map(timer => timer.delay), [3000]);
  stop();
}
console.log('DB 자동 갱신 검증: 표 내용 반영, 선택 유지, 3초 재조회, 오류 복구, 요청 중복 방지와 정리');
