'use strict';
(function(){
 let clearing=null,generation=0,connected=false,tv={connected:false,ready:false};
 const states=new Map(),rows=new Map();
 const terminal=new Set(['completed','failed','cancelled']);
 function notice(message){
   const target=document.querySelector('#log');
   if(!target)return;
   const item=document.createElement('div');item.className='msg assistant';item.textContent='Error: '+message;target.appendChild(item);
 }
 function reset(){for(const row of rows.values())row.remove();rows.clear();states.clear();}
 function render(state){
   let row=rows.get(state.id);
   if(!row){
     row=document.createElement('div');row.className='msg assistant';row.dataset.speechId=state.id;
     row.setAttribute('role','status');row.setAttribute('aria-live','polite');
     document.querySelector('#log').appendChild(row);rows.set(state.id,row);
   }
   const labels={queued:'音声合成の順番待ち',loading:'音声モデル・基準音声を読み込み中（初回は時間がかかります）',
     synthesizing:'音声合成中',retrying_cpu:'GPUでの処理に失敗：CPUで再試行中',
     waiting:!tv.connected?'合成完了・TV未接続':!tv.ready?'合成完了・TVの再生準備待ち':'合成完了・前の音声の終了待ち',
     preparing_playback:'合成完了・音声準備／動画終端待ち',playing:'音声再生中',finishing:'音声終了・発話動画の終端待ち',
     completed:'音声再生完了',failed:'音声処理に失敗',cancelled:'音声処理を中止'};
   let text='音声：'+(labels[state.phase]||state.phase);
   if(!connected&&!terminal.has(state.phase))text='音声：接続断・現在の状態を確認できません（再接続中）';
   if(['loading','synthesizing','retrying_cpu'].includes(state.phase)&&state.total)text+=` · ${state.completed||0}/${state.total}文 完了`;
   if(!terminal.has(state.phase)&&state.created_at)text+=` · 経過${Math.max(0,Math.floor(Date.now()/1000-state.created_at))}秒`;
   if(state.device)text+=' · '+state.device;
   if(state.phase==='failed'&&state.message)text+=' · '+state.message;
   if(row.textContent!==text)row.textContent=text;
 }
 function update(state){
   if(state.generation!==generation)return;
   states.set(state.id,state);render(state);
   for(const [id,old] of states){
     if(states.size<=40)break;
     if(terminal.has(old.phase)){states.delete(id);rows.get(id)?.remove();rows.delete(id);}
   }
 }
 window.AITuberChat={
   clear(){
     reset();
     clearing=fetch('/api/clear',{method:'POST'}).then(async r=>{
       if(!r.ok)throw new Error('Clear failed');generation=(await r.json()).generation;
     }).catch(e=>{notice(e.message);throw e;});
     return clearing;
   },
   async beforeSubmit(){if(clearing){await clearing;clearing=null;}},
   notice
 };
 function connect(){
   const ws=new WebSocket(`${location.protocol==='https:'?'wss':'ws'}://${location.host}/ws?role=chat`);
   ws.onmessage=e=>{
     const event=JSON.parse(e.data);
     if(event.type==='hello'){connected=true;if(generation!==event.generation)reset();generation=event.generation;}
     if(event.type==='speech_status')update(event);
     if(event.type==='speech_snapshot'){generation=event.generation;tv=event.tv;reset();event.states.forEach(update);}
     if(event.type==='tv_status'){tv=event;states.forEach(render);}
     if(event.type==='speech_error')notice(event.message||'Speech processing failed');
   };
   ws.onclose=()=>{connected=false;states.forEach(render);setTimeout(connect,1500);};
 }
 setInterval(()=>{for(const state of states.values())if(!terminal.has(state.phase))render(state);},1000);
 connect();
})();
