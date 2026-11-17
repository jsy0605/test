import assert from 'node:assert/strict';
import { subscribeSystemMetrics, validateMetrics } from '../static/js/system-monitor-feed.js';

const sample = {
  sampled_at: 1000, cpu: {percent: 25},
  memory: {percent: 60, total_bytes: 1000, used_bytes: 600, available_bytes: 400},
  disk: {percent: 50, total_bytes: 2000, used_bytes: 1000, free_bytes: 1000},
  host: {name: 'test-machine', os: 'test-os', uptime_seconds: 100}, server: {uptime_seconds: 10},
};
const tick = () => new Promise(resolve => setImmediate(resolve));
function timers() {
  let index = 0;
  const queue = new Map();
  return {queue, schedule(fn, delay) { queue.set(++index, {fn, delay}); return index; }, cancel(id) { queue.delete(id); }};
}

assert.equal(validateMetrics(sample), sample);
for (const invalid of [
  {...sample, cpu: {percent: 101}}, {...sample, cpu: {percent: NaN}},
  {...sample, memory: {...sample.memory, total_bytes: 0}}, {...sample, disk: {...sample.disk, used_bytes: -1}},
]) assert.throws(() => validateMetrics(invalid));

{
  const timer = timers();
  const states = [], samples = [];
  let calls = 0, signal;
  const stop = subscribeSystemMetrics(data => samples.push(data), state => states.push(state), {
    ...timer, now: () => 0,
    fetchImpl: async (url, options) => {
      assert.equal(url, '/api/system/metrics'); signal = options.signal; calls++;
      if (calls === 1) return {ok: true, status: 200, json: async () => sample};
      throw new Error('test-only offline');
    },
  });
  await tick();
  assert.deepEqual(states, ['loading', 'live']);
  assert.equal(samples.length, 1);
  assert.equal(timer.queue.size, 1);
  const next = [...timer.queue.values()][0];
  assert.equal(next.delay, 2000);
  timer.queue.clear(); await next.fn();
  assert.equal(states.at(-1), 'error');
  assert.equal(samples.length, 1, 'Failure must preserve last sample instead of adding fake zeros');
  stop();
  assert.equal(timer.queue.size, 0);
  assert.equal(signal.aborted, false);
}
{
  const timer = timers();
  const states = [];
  subscribeSystemMetrics(() => assert.fail('Unauthorized data must not be shown'), state => states.push(state), {
    ...timer, fetchImpl: async () => ({status: 401, ok: false}),
  });
  await tick();
  assert.deepEqual(states, ['loading', 'unauthorized']);
  assert.equal(timer.queue.size, 0, 'Expired login must stop polling');
}
{
  const timer = timers();
  let signal, finish;
  const samples = [];
  const stop = subscribeSystemMetrics(data => samples.push(data), () => {}, {
    ...timer, fetchImpl: (_url, options) => { signal = options.signal; return new Promise(resolve => { finish = resolve; }); },
  });
  assert.deepEqual([...timer.queue.values()].map(item => item.delay), [5000], 'An in-flight request has only a timeout, no overlapping poll');
  stop();
  assert.equal(signal.aborted, true);
  finish({ok: true, status: 200, json: async () => sample});
  await tick();
  assert.equal(samples.length, 0, 'Stopping prevents late responses from updating the page');
  assert.equal(timer.queue.size, 0);
}
console.log('System Monitor polling verified: real values, 2s refresh, error recovery, login expiry, no overlap and cleanup');
