export const POLL_INTERVAL = 2000;

export function validateMetrics(data) {
  const nonnegative = value => typeof value === 'number' && Number.isFinite(value) && value >= 0;
  if (!data || !nonnegative(data.sampled_at)
      || typeof data.host?.name !== 'string' || typeof data.host?.os !== 'string'
      || !nonnegative(data.host?.uptime_seconds) || !nonnegative(data.server?.uptime_seconds)) {
    throw new Error('Invalid metrics');
  }
  for (const key of ['cpu', 'memory', 'disk']) {
    if (!nonnegative(data[key]?.percent) || data[key].percent > 100) throw new Error('Invalid percentage');
  }
  for (const [key, fields] of Object.entries({
    memory: ['total_bytes', 'used_bytes', 'available_bytes'], disk: ['total_bytes', 'used_bytes', 'free_bytes'],
  })) {
    if (fields.some(field => !nonnegative(data[key][field])) || data[key].total_bytes === 0
        || fields.slice(1).some(field => data[key][field] > data[key].total_bytes)) throw new Error('Invalid capacity');
  }
  return data;
}

export function subscribeSystemMetrics(onSample, onState, {
  fetchImpl = globalThis.fetch,
  schedule = globalThis.setTimeout,
  cancel = globalThis.clearTimeout,
  now = Date.now,
} = {}) {
  let stopped = false;
  let timer;
  let timeout;
  let controller;
  async function poll() {
    if (stopped) return;
    const started = now();
    controller = new AbortController();
    timeout = schedule(() => controller?.abort(), 5000);
    try {
      const response = await fetchImpl('/api/system/metrics', { cache: 'no-store', signal: controller.signal });
      if (stopped) return;
      if ([401, 403].includes(response.status)) {
        stopped = true;
        onState('unauthorized');
        return;
      }
      if (!response.ok) throw new Error('Metrics unavailable');
      const data = validateMetrics(await response.json());
      if (stopped) return;
      onSample(data);
      onState('live');
    } catch {
      if (!stopped) onState('error');
    } finally {
      cancel(timeout);
      controller = null;
      if (!stopped) timer = schedule(poll, Math.max(0, POLL_INTERVAL - (now() - started)));
    }
  }
  onState('loading');
  poll();
  return () => {
    stopped = true;
    cancel(timer);
    cancel(timeout);
    controller?.abort();
  };
}
