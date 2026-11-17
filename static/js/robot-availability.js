// ROS 2 Bool 토픽을 구독하는 Flask가 이 연결 하나로 1초마다 최신 상태를 전달합니다.
export function subscribeRobotAvailability(onChange, {
  EventSourceImpl = globalThis.EventSource,
  now = Date.now,
  every = globalThis.setInterval,
  cancelEvery = globalThis.clearInterval,
  staleAfter = 3500,
} = {}) {
  let stopped = false;
  let lastFrameAt = now();
  let latest = {status:'waiting', available:null};
  const emit = snapshot => {
    if (stopped) return;
    latest = snapshot;
    onChange(snapshot);
  };
  emit(latest);
  const source = new EventSourceImpl('/api/availability/stream');
  source.addEventListener('availability', event => {
    try {
      const snapshot = JSON.parse(event.data);
      if (!['waiting','available','unavailable','stale','disconnected'].includes(snapshot.status)
          || (snapshot.status === 'available' && snapshot.available !== true)
          || (snapshot.status === 'unavailable' && snapshot.available !== false)
          || (!['available','unavailable'].includes(snapshot.status) && snapshot.available !== null)) {
        throw new Error('Invalid availability event');
      }
      lastFrameAt = now();
      const state = {status:snapshot.status, available:snapshot.available};
      if (typeof snapshot.dev_ready === 'boolean') state.devReady = snapshot.dev_ready;
      if (snapshot.dev_value === null || typeof snapshot.dev_value === 'boolean') state.devValue = snapshot.dev_value;
      emit(state);
    } catch {
      emit({status:'disconnected', available:null});
    }
  });
  source.addEventListener('error', () => emit({status:'disconnected', available:null}));
  const watchdog = every(() => {
    if (now() - lastFrameAt > staleAfter && latest.status !== 'disconnected') {
      emit({status:'stale', available:null});
    }
  }, 1000);
  return () => {
    stopped = true;
    source.close();
    cancelEvery(watchdog);
  };
}
