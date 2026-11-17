import assert from 'node:assert/strict';
import {bindLogReset} from '../static/js/admin-log-reset.js';
class Element {
  constructor(){this.events=new Map();this.disabled=false;this.textContent='';this.open=false;}
  addEventListener(name,fn){this.events.set(name,fn);}
  showModal(){this.open=true;}
  close(){this.open=false;this.events.get('close')?.();}
  async fire(name,event={preventDefault(){}}){return this.events.get(name)?.(event);}
}
function setup(request) {
  const elements=new Map();
  const get=selector=>{if(!elements.has(selector))elements.set(selector,new Element());return elements.get(selector);};
  let refreshed=0;
  bindLogReset({request,root:{querySelector:get},writeOptions:(method,body)=>({method,body}),onReset:async()=>{refreshed++;}});
  return {get,refreshed:()=>refreshed};
}
{
  const calls=[];
  const ui=setup(async (url,options)=>{calls.push({url,options});return options?.method==='DELETE'?{deleted:4,total:0}:{total:4};});
  await ui.get('#open-log-reset').fire('click');
  assert.equal(calls[0].url,'/api/logs?limit=1');
  assert.equal(calls.length,1,'Opening the dialog must not delete records');
  assert(ui.get('#log-reset-description').textContent.includes('전체 로봇 로그 4건'));
  await ui.get('#log-reset-form').fire('submit');
  assert.deepEqual(calls[1],{url:'/api/logs',options:{method:'DELETE',body:{confirm:'RESET_LOGS',expected_count:4}}});
  assert.equal(ui.get('#log-reset-dialog').open,false);
  assert.equal(ui.refreshed(),1);
  assert(ui.get('#log-reset-result').textContent.includes('4건을 삭제'));
}
{
  let removed=0;
  const ui=setup(async (_url,options)=>{if(options?.method==='DELETE')removed++;return {total:4};});
  await ui.get('#open-log-reset').fire('click');
  await ui.get('#cancel-log-reset').fire('click');
  await ui.get('#log-reset-form').fire('submit');
  assert.equal(removed,0);assert.equal(ui.refreshed(),0);
}
{
  const ui=setup(async (_url,options)=>{if(options?.method==='DELETE')assert.fail('Empty DB must not submit deletion');return {total:0};});
  await ui.get('#open-log-reset').fire('click');
  assert.equal(ui.get('#confirm-log-reset').disabled,true);
  await ui.get('#log-reset-form').fire('submit');
  assert.equal(ui.refreshed(),0);
}
{
  let deletions=0;
  const ui=setup(async (_url,options)=>{if(options?.method==='DELETE'){deletions++;throw new Error('로그 건수가 변경됐습니다.');}return {total:4};});
  await ui.get('#open-log-reset').fire('click');
  await ui.get('#log-reset-form').fire('submit');
  assert(ui.get('#log-reset-message').textContent.includes('변경'));
  assert.equal(ui.get('#log-reset-dialog').open,true);
  assert.equal(ui.get('#confirm-log-reset').disabled,true);
  await ui.get('#log-reset-form').fire('submit');
  assert.equal(deletions,1,'A failed deletion requires a fresh preview');
}
{
  let finish,signal;
  const ui=setup((_url,options)=>{signal=options.signal;return new Promise(resolve=>{finish=resolve;});});
  const opening=ui.get('#open-log-reset').fire('click');
  await ui.get('#cancel-log-reset').fire('click');
  assert.equal(signal.aborted,true);
  finish({total:4}); await opening;
  assert.equal(ui.get('#log-reset-dialog').open,false);
  assert.equal(ui.get('#confirm-log-reset').disabled,true);
}
console.log('DB 로그 초기화 UI 검증: 전체 건수 확인, 삭제 실행, 취소, 빈 DB, 건수 변경, 늦은 응답 방지');
