import assert from 'node:assert/strict';
import { subscribeRobotAvailability } from '../static/js/robot-availability.js';

class FakeEventSource {
  constructor(url) { assert.equal(url, '/api/availability/stream'); this.handlers={}; FakeEventSource.instance=this; }
  addEventListener(name, callback) { this.handlers[name]=callback; }
  close() { this.closed=true; }
  send(data) { this.handlers.availability({data:JSON.stringify(data)}); }
}

let time=0, tick, cleared=false;
const snapshots=[];
const stop=subscribeRobotAvailability(s => snapshots.push(s), {
  EventSourceImpl:FakeEventSource, now:() => time,
  every:callback => { tick=callback; return 1; }, cancelEvery:() => { cleared=true; },
});
const source=FakeEventSource.instance;
assert.equal(snapshots.at(-1).available, null);
source.send({status:'available',available:true});
assert.equal(snapshots.at(-1).available,true);
source.send({status:'unavailable',available:false});
assert.equal(snapshots.at(-1).available,false);
source.send({status:'available',available:true});
time=4000; tick();
assert.deepEqual(snapshots.at(-1),{status:'stale',available:null});
source.send({status:'available',available:'true'});
assert.equal(snapshots.at(-1).available,null);
source.send({status:'available',available:true});
source.handlers.error();
assert.deepEqual(snapshots.at(-1),{status:'disconnected',available:null});
source.send({status:'available',available:true});
assert.equal(snapshots.at(-1).available,true);
stop();
assert(source.closed && cleared);
const count=snapshots.length;
source.send({status:'unavailable',available:false});
assert.equal(snapshots.length,count);
console.log('토픽 상태 스트림 검증 완료: true/false 전환, 오래된 상태, 잘못된 메시지, 단절·복구, 구독 종료');
