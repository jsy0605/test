const session=document.querySelector('#session'),robot=document.querySelector('#robot'),message=document.querySelector('#message');
async function refresh(){
 const response=await fetch('/api/simulator');if(!response.ok)throw Error('리모컨 서버에 연결할 수 없어요.');
 const data=await response.json(),previous=session.value;
 session.replaceChildren(new Option('자동 · 최근 관람 / 없으면 새로 생성',''),...data.sessions.map(s=>new Option(`${s.robot||'배정 전'} · ${s.id.slice(0,8)} · ${s.phase}`,s.id)));
 if(data.sessions.some(s=>s.id===previous))session.value=previous;
 document.querySelector('#status').textContent=`호출 가능: ${data.availability.status}  ·  테스트 관람 ${data.sessions.length}개`;
 document.querySelector('#history').replaceChildren(...data.history.slice().reverse().map(h=>{
  const li=document.createElement('li');li.textContent=`${h.at} · ${h.robot==='robot2'?'Arty 2':'Arty 1'} · ${h.label} · ${h.session?.slice(0,8)||'전체'}`;return li;
 }));
}
// Serialize rapid clicks instead of dropping the second signal.
let queue=Promise.resolve();
document.addEventListener('click',e=>{
 const button=e.target.closest('[data-signal]');if(!button)return;
 const payload={signal:button.dataset.signal,session_id:session.value,robot:robot.value,message:document.querySelector('#custom-message').value,progress:Number(document.querySelector('#progress').value)/100};
 queue=queue.then(async()=>{
  const response=await fetch('/api/simulator/signal',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});
  const data=await response.json();if(!response.ok)throw Error(data.error?.message||'신호를 보낼 수 없어요.');
  document.querySelectorAll('[data-signal]').forEach(b=>b.classList.toggle('selected',b===button));
  message.textContent=`✓ 전송 완료 · ${button.querySelector('span').textContent}`;message.dataset.error='false';await refresh();
 }).catch(e=>{message.textContent=e.message;message.dataset.error='true';});
});
document.querySelector('#new-session').onclick=()=>{
 queue=queue.then(async()=>{
  const response=await fetch('/api/simulator/session',{method:'POST'});if(!response.ok)throw Error('새 테스트 생성 실패');
  const data=await response.json();await refresh();session.value=data.session_id;message.textContent='새 테스트가 준비됐어요. 원하는 신호를 보내세요.';
 }).catch(e=>{message.textContent=e.message;});
};
document.querySelector('#progress').oninput=e=>document.querySelector('#progress-value').textContent=e.target.value+'%';
document.querySelector('#search').oninput=e=>{
 const query=e.target.value.trim().toLowerCase();
 document.querySelectorAll('[data-signal]').forEach(b=>b.hidden=!b.textContent.toLowerCase().includes(query));
 document.querySelectorAll('.group').forEach(g=>g.hidden=![...g.querySelectorAll('[data-signal]')].some(b=>!b.hidden));
};
async function poll(){try{await refresh();}catch(e){message.textContent=e.message;}setTimeout(poll,1000);}poll();
