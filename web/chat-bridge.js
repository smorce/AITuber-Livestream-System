'use strict';
(function(){
 let clearing=null;
 function notice(message){
   const target=document.querySelector('#log');
   if(!target)return;
   const item=document.createElement('div');item.className='msg assistant';item.textContent='Error: '+message;target.appendChild(item);
 }
 window.AITuberChat={
   clear(){
     clearing=fetch('/api/clear',{method:'POST'}).then(r=>{if(!r.ok)throw new Error('Clear failed');}).catch(e=>{notice(e.message);throw e;});
     return clearing;
   },
   async beforeSubmit(){if(clearing){await clearing;clearing=null;}},
   notice
 };
 function connect(){
   const ws=new WebSocket(`${location.protocol==='https:'?'wss':'ws'}://${location.host}/ws?role=chat`);
   ws.onmessage=e=>{const event=JSON.parse(e.data);if(event.type==='speech_error'||event.type==='failed')notice(event.message||'Speech playback failed');};
   ws.onclose=()=>setTimeout(connect,1500);
 }
 connect();
})();
