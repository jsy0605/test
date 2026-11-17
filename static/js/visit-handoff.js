export function farewellPage() {
  return `<section class="farewell-content" aria-labelledby="farewell-title"><div class="farewell-flower" aria-hidden="true">✳</div><h1 id="farewell-title">즐거운 관람 되세요!</h1><p>10초 후 처음 화면으로 돌아가요.</p><button class="button primary" data-action="reset">처음으로</button></section>`;
}

// 같은 마지막 화면을 다시 그려도 최초 진입 시각부터 10초를 계산합니다.
export function createAutoReturn({onReturn, delay = 10000, now = Date.now,
  setTimer = setTimeout, clearTimer = clearTimeout}) {
  let key = null;
  let deadline = 0;
  let timer = null;
  function suspend() {
    if (timer !== null) clearTimer(timer);
    timer = null;
  }
  function cancel() {
    suspend(); key = null; deadline = 0;
  }
  function check() {
    suspend();
    if (key === null) return;
    const remaining = deadline - now();
    if (remaining > 0) { timer = setTimer(check, remaining); return; }
    cancel(); onReturn();
  }
  function start(nextKey) {
    if (key !== nextKey) { cancel(); key = nextKey; deadline = now() + delay; }
    check();
  }
  return {start, cancel, suspend, resume: check};
}
