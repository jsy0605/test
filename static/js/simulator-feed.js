// Only the isolated test server exposes /api/simulator/events. No ROS publisher exists here.
let source,timer,last=Date.now();
export function connectSimulator(sessionId,apply){
 source?.close();clearInterval(timer);last=Date.now();let disconnected=false;
 source=new EventSource(sessionId ? `/api/simulator/events/${encodeURIComponent(sessionId)}` : '/api/simulator/live');
 source.onmessage=e=>{try{const data=JSON.parse(e.data);if(sessionId&&data.session?.id!==sessionId)return;last=Date.now();disconnected=false;apply(data);}catch{apply({disconnected:true});}};
 source.onerror=()=>{disconnected=true;apply({disconnected:true});};
 timer=setInterval(()=>{if(!disconnected&&Date.now()-last>3500){disconnected=true;apply({disconnected:true});}},1000);
}
export function stopSimulator(){source?.close();clearInterval(timer);}
