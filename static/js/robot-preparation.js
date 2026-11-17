// A single SSE connection mirrors native ROS service/action/topic state.
export function subscribePreparation(sessionId, onChange, {
  EventSourceImpl = globalThis.EventSource,
  every = globalThis.setInterval,
  cancelEvery = globalThis.clearInterval,
  now = Date.now,
} = {}) {
  const phases = ['calling','moving','arrived','registering','waiting_ready','ready','error','cancelling','cancelled'];
  let stopped = false;
  let lastFrame = now();
  let disconnected = false;
  const emit = value => { if (!stopped) onChange(value); };
  const source = new EventSourceImpl(`/api/sessions/${encodeURIComponent(sessionId)}/preparation/events`);
  source.addEventListener('preparation', event => {
    try {
      const value = JSON.parse(event.data);
      if (value.session_id !== sessionId || !phases.includes(value.phase)
          || typeof value.message !== 'string' || typeof value.robot_id !== 'string'
          || !Number.isFinite(value.progress) || value.progress < 0 || value.progress > 1) throw Error();
      lastFrame = now(); disconnected = false;
      emit({...value, connected:true});
    } catch { disconnected = true; emit({connected:false}); }
  });
  source.addEventListener('error', () => { disconnected = true; emit({connected:false}); });
  const watchdog = every(() => {
    if (!disconnected && now() - lastFrame > 3500) {
      disconnected = true;
      emit({connected:false});
    }
  }, 1000);
  return () => { stopped = true; source.close(); cancelEvery(watchdog); };
}
