'use strict';
// 既存エディターの描画・位置設定を利用し、再生だけを一元管理する。
(function(){
 const {PlaybackState,chooseIdle}=AITuberPlayback;
 const names=['待機A：髪に触れて微笑むロゼ.mp4','待機B：考えながら襟元を整えるロゼ.mp4','待機C：作業中のロゼ.mp4'];
 const clips=[idleVideo];
 const failed=new Set();
 const preview=new URLSearchParams(location.search).get('preview')==='1';
 const autoplay=new URLSearchParams(location.search).get('autoplay')==='1';
 let autoClaimed=false;
 let claimDenied=false;
 let previous=0,custom=false,socket=null,owner=false,generation=0,loading=null;
 let cfg={flag_lead:.3,audio_lead:.15,off_lead:.2,max_idle_overlap:.3};
 let machine=new PlaybackState(cfg),context=null,source=null,buffer=null;
 let startedAt=0,overlapAt=0,lastTick=performance.now(),heartbeatAt=0,lastReady=null,guardTimer=null,internalSeekUntil=0;
 const seen=new Set();
 for(let i=1;i<3;i++){
   const clip=document.createElement('video');
   clip.style.display='none';clip.preload='auto';clip.playsInline=true;clip.muted=true;
   idleVideo.parentElement.appendChild(clip);clip.src=names[i];clip.load();
   clips.push(clip);videos.push(clip);
   clip.addEventListener('ended',()=>onClipEnded(clip));
 }
 clips.forEach((clip,i)=>clip.addEventListener('error',()=>{failed.add(i);if(video===clip)fail('Idle video failed');}));
 syncVideoSettings();
 function status(text){$('status').textContent=text;}
 function send(event){if(socket?.readyState===WebSocket.OPEN)socket.send(JSON.stringify(event));}
 function setFlag(value){speechFlag=value;machine.flag=value;$('speechFlag').checked=value;updateSpeechUI();}
 function audioContext(){context??=new AudioContext();return context;}
 function remaining(clip){return Number.isFinite(clip.duration)?Math.max(0,(clip.duration-clip.currentTime)/clip.playbackRate):Infinity;}
 function stopSource(){if(source){source.onended=null;try{source.stop();}catch{}source.disconnect();source=null;}clearTimeout(guardTimer);guardTimer=null;buffer=null;}
 function cancel(reason='cancelled',notify=true,message){
   const id=machine.id||loading?.id;
   loading=null;stopSource();machine.cancel();setFlag(false);overlapAt=0;
   if(pendingTransition){pendingTransition.to.pause();pendingTransition=null;}
   if(id&&notify)send({type:reason,id,generation,message});
 }
 function fail(message){cancel('failed',true,message);status('Error: '+message);}
 function ready(){return owner&&context?.state==='running'&&!document.hidden&&!debugOn&&isVideo&&!pendingTransition&&!video.paused&&speechReady&&speechVideo.readyState>=2&&!custom&&(machine.id||(!speechFlag&&video!==speechVideo));}
 function updateReady(){
   const value=!!ready();if(value!==lastReady){lastReady=value;send({type:'ready',ready:value});}
   if(socket?.readyState!==WebSocket.OPEN)return;
   if(autoplay&&!preview&&!autoClaimed&&context?.state==='running'){
     autoClaimed=true;send({type:'claim'});
   }
   if(!owner)status(preview?'プレビュー：音声再生なし':claimDenied?'プレビュー：別のTVが発話中です':'プレビュー：別のTVが音声の再生先です');
   else if(context?.state!=='running')status('音声の自動再生がブラウザで制限されています：open-tv.ps1で起動');
 }
 function pickIdle(fromSpeech=false){
   const available=clips.map((_,i)=>i).filter(i=>!failed.has(i)&&clips[i].readyState>=2);
   const next=chooseIdle(available,fromSpeech?null:previous);
   if(next===null){status('Error: No playable idle videos');return false;}
   previous=next;idleVideo=clips[next];switchVideo(idleVideo);return true;
 }
 function finish(){
   const id=machine.id;stopSource();machine.cancel();setFlag(false);overlapAt=0;
   lastReady=false;send({type:'ready',ready:false});
   if(id)send({type:'ended',id,generation});
 }
 async function receive(event){
   if(event.type==='hello'){
     owner=event.owner;generation=event.generation;cfg=event;machine.config=cfg;
     lastReady=null;send({type:'ping'});updateReady();
     if(!owner)status('プレビュー：音声再生なし');
   }
   if(event.type==='pong')heartbeatAt=performance.now();
   if(event.type==='role'){owner=event.owner;claimDenied=false;lastReady=null;updateReady();if(owner)status('● 音声再生先：このTV');}
   if(event.type==='claim_denied'){claimDenied=true;updateReady();}
   if(event.type==='clear'){cancel('cancelled',false);generation=event.generation;}
   if(event.type!=='utterance'||!owner||event.generation!==generation||seen.has(event.id))return;
   seen.add(event.id);if(seen.size>1000)seen.delete(seen.values().next().value);
   if(machine.id||loading){send({type:'failed',id:event.id,generation});return;}
   loading=event;
   try{
     const response=await fetch(event.url,{cache:'no-store'});
     if(!response.ok)throw new Error('Audio download failed');
     const decoded=await audioContext().decodeAudioData(await response.arrayBuffer());
     if(loading!==event||generation!==event.generation)return;
     if(!ready())throw new Error('TV is not ready for playback');
     buffer=decoded;machine.prepare(event.id,decoded.duration);loading=null;
     status('● 音声準備完了：動画終端を待機');
   }catch(err){if(loading===event){loading=null;send({type:'failed',id:event.id,generation});status('Error: '+err.message);}}
 }
 function startAudio(){
   if(!buffer||(!ready()&&!video.ended)){fail('Playback readiness lost');return;}
   const id=machine.id;
   source=audioContext().createBufferSource();source.buffer=buffer;source.connect(context.destination);
   startedAt=context.currentTime;overlapAt=performance.now();machine.start();setFlag(true);
   source.onended=()=>{if(machine.id===id){machine.audioEnded(id);setFlag(false);send({type:'audio_ended',id,generation});if(video===speechVideo)clearTimeout(guardTimer);}};
   source.start();send({type:'started',id,generation});
   for(const clip of videos)clip.muted=true;
   guardTimer=setTimeout(()=>{if(machine.id===id&&video!==speechVideo)fail('Speech video transition timeout');},cfg.max_idle_overlap*1000);
 }
 function tick(){
   const now=performance.now();
   if(machine.id&&machine.phase==='playing'&&now-lastTick>300){fail('Playback scheduler stalled');}
   lastTick=now;
   if(owner&&heartbeatAt&&now-heartbeatAt>2500&&(machine.id||loading))fail('Playback connection timed out');
   updateReady();
   if(!machine.id)return;
   if(overlapAt&&video!==speechVideo&&now-overlapAt>cfg.max_idle_overlap*1000){fail('Speech video transition timeout');return;}
   if(debugOn||document.hidden||!isVideo||context?.state!=='running'){fail('Playback interrupted');return;}
   if(machine.phase==='prepared'&&video!==speechVideo&&!pendingTransition&&!video.paused){
     const left=remaining(video);
     if(left<=cfg.flag_lead)setFlag(true);
     if(left<=machine.lead)startAudio();
   }
   if(machine.phase==='playing'){
     if(video!==speechVideo){if(now-overlapAt>cfg.max_idle_overlap*1000)fail('Speech video transition timeout');}
     else{
       clearTimeout(guardTimer);guardTimer=null;
       const left=Math.max(0,machine.duration-(context.currentTime-startedAt));
       if(machine.shouldOff(left,remaining(video)))setFlag(false);
       if(video.paused&&!video.ended&&!pendingTransition)fail('Speech video paused');
     }
   }
 }
 window.AITuberTV={
   beforeSwitch(){internalSeekUntil=performance.now()+500;},
   tick,
   onClipEnded(which){
     if(debugOn||!isVideo||video!==which||pendingTransition)return false;
     if(which===speechVideo){
       if(machine.id){
         if(!machine.canIdle()){switchVideo(speechVideo);return true;}
         finish();pickIdle(true);return true;
       }
       if(!speechFlag&&!custom){pickIdle(true);return true;}
       return false;
     }
     if(!clips.includes(which)||custom)return false;
     if(machine.id&&machine.phase==='prepared'){startAudio();}
     if(machine.id&&!machine.canIdle()){switchVideo(speechVideo);return true;}
     if(speechFlag&&speechReady){switchVideo(speechVideo);return true;}
     if($('loop').checked)pickIdle();
     return true;
   },
   cancel,
   snapshot(){return {phase:machine.phase,id:machine.id,owner,generation,flag:speechFlag,clip:video===speechVideo?'D':names[clips.indexOf(video)],device:context?.state};}
 };
 function connect(){
   autoClaimed=false;
   socket=new WebSocket(`${location.protocol==='https:'?'wss':'ws'}://${location.host}/ws?preview=${new URLSearchParams(location.search).get('preview')==='1'?'1':'0'}`);
   socket.onmessage=e=>{receive(JSON.parse(e.data)).catch(err=>fail(err.message));};
   socket.onclose=()=>{owner=false;lastReady=null;heartbeatAt=0;cancel('failed',false);status('Error: TV connection lost');setTimeout(connect,1500);};
 }
 // 既存操作の前に音声を停止し、エディターの操作結果を尊重する。
 const cancelIds=new Set(['pause','reset','debugFlag','debugIdle','debugSpeech','debugBlink','speechFlag','loadBtn']);
 document.addEventListener('click',e=>{
   const id=e.target.closest('[id]')?.id;
   if(cancelIds.has(id))cancel();
 },true);
 document.addEventListener('change',e=>{
   if(['mediaFile','speechFile','settingsFile'].includes(e.target.id)){cancel();if(e.target.id==='mediaFile')custom=true;}
 },true);
 document.addEventListener('visibilitychange',()=>{if(document.hidden){cancel('failed');send({type:'ready',ready:false});lastReady=false;}});
 window.addEventListener('pagehide',()=>{cancel('failed');socket?.close();});
 for(const clip of videos){
   clip.muted=true;
   clip.addEventListener('error',()=>{if(clip===speechVideo||clip===video)fail('Video decode failed');});
   clip.addEventListener('seeking',()=>{if(machine.id&&clip===video&&!pendingTransition&&!clip.ended&&performance.now()>internalSeekUntil)cancel();});
 }
 $('mute').addEventListener('change',()=>{if(machine.id)for(const clip of videos)clip.muted=true;});
 setInterval(tick,25);
 setInterval(()=>{if(socket?.readyState===1)send({type:'ping'});},500);
 if(location.protocol==='http:'||location.protocol==='https:'){
   audioContext().resume().catch(()=>{});connect();
 }
})();
