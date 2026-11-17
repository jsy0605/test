import assert from 'node:assert/strict';
import {subscribePreparation} from '../static/js/robot-preparation.js';
let source, tick, time=0;
class Source {
  constructor(url) { this.url=url; this.handlers={}; source=this; }
  addEventListener(name, fn) { this.handlers[name]=fn; }
  close() { this.closed=true; }
  send(value) { this.handlers.preparation({data:JSON.stringify(value)}); }
}
const events=[];
const stop=subscribePreparation('session-a', event=>events.push(event), {EventSourceImpl:Source,now:()=>time,every:fn=>(tick=fn,1),cancelEvery:()=>{}});
const valid={session_id:'session-a',phase:'arrived',message:'도착',robot_id:'robot2',progress:1};
source.send(valid); assert.equal(events.at(-1).phase,'arrived');
source.send({...valid,session_id:'old-session'}); assert.equal(events.at(-1).connected,false);
source.send(valid); assert.equal(events.at(-1).connected,true);
time=4000;tick();assert.equal(events.at(-1).connected,false);
source.send({...valid,phase:'ready',robot_id:'DEV-ARTI',dev_mode:true});assert.equal(events.at(-1).phase,'ready');assert.equal(events.at(-1).dev_mode,true);
source.handlers.error();assert.equal(events.at(-1).connected,false);
const count=events.length;stop();source.send(valid);assert.equal(events.length,count);assert.equal(source.closed,true);
console.log('Preparation SSE validation, stale connection, recovery and cleanup passed');
