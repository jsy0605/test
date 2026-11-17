import assert from 'node:assert/strict';
import { createAutoReturn, farewellPage } from '../static/js/visit-handoff.js';
function clock() {
  let time = 0, id = 0;
  const timers = new Map();
  return {timers, now: () => time,
    setTimer(fn, delay) {timers.set(++id, {fn, at:time + delay}); return id;},
    clearTimer(id) {timers.delete(id);},
    advance(ms) {
      const end = time + ms;
      while (true) {
        const next = [...timers].filter(([, timer]) => timer.at <= end).sort((a,b) => a[1].at - b[1].at)[0];
        if (!next) break;
        time = next[1].at; timers.delete(next[0]); next[1].fn();
      }
      time = end;
    },
  };
}
{
  const env = clock(); let returns = 0;
  const timer = createAutoReturn({...env, onReturn: () => returns++});
  timer.start('session-a');
  env.advance(9000); assert.equal(returns, 0);
  timer.start('session-a'); // 상태 갱신으로 다시 그려도 남은 시간은 1초입니다.
  env.advance(999); assert.equal(returns, 0);
  env.advance(1); assert.equal(returns, 1);
  env.advance(10000); assert.equal(returns, 1);
}
{
  const env = clock(); let returns = 0;
  const timer = createAutoReturn({...env, onReturn: () => returns++});
  timer.start('session-a'); env.advance(2000); timer.cancel(); // 처음으로 버튼
  env.advance(10000); assert.equal(returns, 0); assert.equal(env.timers.size, 0);
  timer.start('session-b'); env.advance(10000); assert.equal(returns, 1);
}
{
  const env = clock(); let returns = 0;
  const timer = createAutoReturn({...env, onReturn: () => returns++});
  timer.start('session-a'); env.advance(4000); timer.suspend(); env.advance(9000);
  assert.equal(returns, 0); timer.resume(); assert.equal(returns, 1);
}
const markup = farewellPage();
assert(markup.includes('즐거운 관람 되세요!'));
assert.equal((markup.match(/<button/g) || []).length, 1);
assert(markup.includes('data-action="reset">처음으로'));
assert(!markup.includes('작품 설명') && !markup.includes('다음 작품') && !markup.includes('일시정지'));
console.log('마지막 화면 검증: 버튼 1개, 10초 자동 복귀, 수동 복귀 취소, 재표시와 백그라운드 시간 유지');
