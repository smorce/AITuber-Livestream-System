const {test}=require('node:test');
const assert=require('node:assert/strict');
const {chromium}=require('playwright');
const fs=require('node:fs');
const path=require('node:path');
const base=process.env.AITUBER_TEST_URL||'http://127.0.0.1:17863';
const executable=process.env.CHROME_PATH||'C:/Program Files/Google/Chrome/Application/chrome.exe';

function wav(seconds){
 const count=Math.round(seconds*48000),b=Buffer.alloc(44+count*2);
 b.write('RIFF',0);b.writeUInt32LE(b.length-8,4);b.write('WAVEfmt ',8);b.writeUInt32LE(16,16);
 b.writeUInt16LE(1,20);b.writeUInt16LE(1,22);b.writeUInt32LE(48000,24);b.writeUInt32LE(96000,28);
 b.writeUInt16LE(2,32);b.writeUInt16LE(16,34);b.write('data',36);b.writeUInt32LE(count*2,40);
 return b;
}

test('チャットに合成進捗・待機理由・失敗・再接続後の状態を表示する',{timeout:20000},async()=>{
 const browser=await chromium.launch({executablePath:executable,headless:true});
 try{
  const page=await browser.newPage();let peer,connections=0,snapshot=[];
  const errors=[];page.on('pageerror',e=>errors.push(e.message));
  await page.route('**/api/clear',r=>r.fulfill({json:{generation:1}}));
  await page.routeWebSocket('**/ws?role=chat',ws=>{
   peer=ws;connections++;
   ws.send(JSON.stringify({type:'hello',generation:0,owner:false}));
   ws.send(JSON.stringify({type:'speech_snapshot',generation:0,states:snapshot,tv:{connected:false,ready:false}}));
  });
  await page.goto(base+'/');
  await page.waitForFunction(()=>!!window.AITuberChat);
  const state={type:'speech_status',id:'test-progress',generation:0,created_at:Date.now()/1000-7,total:3,completed:0};
  const row=page.locator('[data-speech-id="test-progress"]');
  const send=phase=>peer.send(JSON.stringify({...state,...phase}));
  send({phase:'loading'});
  await row.filter({hasText:'読み込み中'}).waitFor();
  assert.match(await row.textContent(),/0\/3文 完了.*経過\d+秒/);
  send({phase:'synthesizing',completed:1,device:'Vulkan0'});
  await row.filter({hasText:'1/3文 完了'}).waitFor();
  send({phase:'retrying_cpu',device:'cpu'});
  await row.filter({hasText:'CPUで再試行中'}).waitFor();
  send({phase:'waiting'});
  await row.filter({hasText:'TV未接続'}).waitFor();
  peer.send(JSON.stringify({type:'tv_status',connected:true,ready:false}));
  await row.filter({hasText:'TVの再生準備待ち'}).waitFor();
  send({phase:'preparing_playback'});
  await row.filter({hasText:'動画終端待ち'}).waitFor();
  send({phase:'playing'});
  await row.filter({hasText:'音声再生中'}).waitFor();
  send({phase:'finishing'});
  await row.filter({hasText:'音声終了'}).waitFor();
  send({phase:'completed'});
  await row.filter({hasText:'音声再生完了'}).waitFor();
  send({phase:'failed',message:'Synthesis timeout <test>'});
  await row.filter({hasText:'音声処理に失敗'}).waitFor();
  assert.match(await row.textContent(),/Synthesis timeout <test>/);
  assert.equal(await row.locator('test').count(),0);
  snapshot=[{...state,phase:'synthesizing',completed:2}];
  send(snapshot[0]);
  peer.close();
  await row.filter({hasText:'接続断'}).waitFor();
  await row.filter({hasText:'2/3文 完了'}).waitFor();
  await page.waitForFunction(()=>!document.querySelector('[data-speech-id]').textContent.includes('接続断'));
  assert.equal(connections,2);
  fs.mkdirSync(path.join(__dirname,'../.runtime'),{recursive:true});
  await page.screenshot({path:path.join(__dirname,'../.runtime/speech-status.png')});
  await page.locator('#clear').click();
  await page.waitForTimeout(100);
  send({phase:'playing'});
  await page.waitForTimeout(100);
  assert.equal(await page.locator('[data-speech-id]').count(),0);
  assert.deepEqual(errors,[]);
 }finally{await browser.close();}
});

for(const automatic of [false,true])test(automatic?'ボタン操作なしで音声を有効化して再生権を取得する':'再生ボタンは動画だけを再生し音声の再生先を変更しない',{timeout:40000},async()=>{
 const browser=await chromium.launch({executablePath:executable,headless:true,args:automatic?['--autoplay-policy=no-user-gesture-required']:[]});
 try{
  const page=await browser.newPage();const messages=[];let peer;
  await page.route('**/api/audio/test-auto',r=>r.fulfill({contentType:'audio/wav',body:wav(2)}));
  await page.routeWebSocket('**/ws?*',ws=>{
   peer=ws;
   ws.onMessage(raw=>{
    const e=JSON.parse(raw);messages.push(e);
    if(e.type==='ping')ws.send(JSON.stringify({type:'pong'}));
    if(e.type==='claim')ws.send(JSON.stringify({type:'role',owner:true}));
   });
   ws.send(JSON.stringify({type:'hello',owner:false,generation:0,flag_lead:.3,audio_lead:.15,off_lead:.2,max_idle_overlap:.3}));
  });
  await page.goto(base+'/'+encodeURIComponent('ブラウン管TV_映像エディター_XYZデバッグ版.html')+(automatic?'?autoplay=1':''));
  if(!automatic){
   await page.waitForFunction(()=>document.getElementById('status').textContent.includes('プレビュー'));
   await page.locator('#play').click();
   await new Promise(resolve=>setTimeout(resolve,100));
   assert.equal(messages.some(e=>e.type==='claim'),false);
   assert.equal(await page.evaluate(()=>AITuberTV.snapshot().owner),false);
   assert.equal(await page.evaluate(()=>video.paused),false);
   return;
  }
  await page.waitForFunction(()=>AITuberTV.snapshot().owner&&AITuberTV.snapshot().device==='running');
  assert.ok(messages.some(e=>e.type==='claim'));
  await page.waitForFunction(()=>speechVideo.readyState>=2&&!video.paused&&!pendingTransition);
  await new Promise(resolve=>setTimeout(resolve,100));
  assert.ok(messages.some(e=>e.type==='ready'&&e.ready));
  if(automatic){
   await page.evaluate(()=>{$('speed').value='2';$('speed').dispatchEvent(new Event('input'));video.currentTime=video.duration-1;});
   await page.waitForFunction(()=>!video.seeking);
   peer.send(JSON.stringify({type:'utterance',id:'test-auto',generation:0,url:'/api/audio/test-auto'}));
   await page.waitForFunction(()=>AITuberTV.snapshot().phase==='playing',{},{timeout:15000});
   assert.equal(messages.filter(e=>e.type==='started').length,1);
   await page.waitForFunction(()=>AITuberTV.snapshot().id===null,{},{timeout:25000});
   assert.ok(messages.some(e=>e.type==='ended'));
  }
  peer.send(JSON.stringify({type:'role',owner:false}));
  await page.waitForFunction(()=>!AITuberTV.snapshot().owner);
  assert.match(await page.locator('#status').textContent(),/プレビュー/);
 }finally{await browser.close();}
});

test('実動画で再生境界・中断・重複・切替失敗を検証する',{timeout:180000},async()=>{
 const browser=await chromium.launch({executablePath:executable,headless:true,args:['--autoplay-policy=no-user-gesture-required']});
 const results=[];
 try{
  for(const scenario of ['long','clear','transition-failure','short-transition-failure','short','pause','debug','reset','disconnect','duplicate']){
   const context=await browser.newContext({viewport:{width:1600,height:1000}});
   const page=await context.newPage();let peer;const messages=[],errors=[];
   page.on('pageerror',e=>errors.push(e.message));
   await page.route('**/api/audio/test-*',r=>r.fulfill({contentType:'audio/wav',body:wav(scenario==='long'?9:scenario.startsWith('short')?.12:2)}));
   await page.routeWebSocket('**/ws?*',ws=>{
    peer=ws;
    ws.onMessage(raw=>{const e=JSON.parse(raw);messages.push(e);if(e.type==='ping')ws.send(JSON.stringify({type:'pong'}));});
    ws.send(JSON.stringify({type:'hello',owner:true,generation:0,flag_lead:.3,audio_lead:.15,off_lead:.2,max_idle_overlap:.3}));
   });
   await page.goto(base+'/'+encodeURIComponent('ブラウン管TV_映像エディター_XYZデバッグ版.html'));
   await page.waitForFunction(()=>AITuberTV.snapshot().device==='running'&&speechVideo.readyState>=2&&videos.every(v=>v.readyState>=2));
   await page.evaluate(()=>{
    $('speed').value='2';$('speed').dispatchEvent(new Event('input'));
    video.currentTime=video.duration-1;
    window.trace=[];window.traceTimer=setInterval(()=>trace.push({t:performance.now(),...AITuberTV.snapshot()}),10);
   });
   await page.waitForFunction(()=>!video.seeking);
   if(scenario.endsWith('transition-failure'))await page.evaluate(()=>{window.switchVideo=()=>{};});
   peer.send(JSON.stringify({type:'utterance',id:'test-'+scenario,generation:0,url:'/api/audio/test-'+scenario}));
   await page.waitForFunction(()=>AITuberTV.snapshot().phase==='playing',{},{timeout:15000}).catch(async error=>{console.error({scenario,messages,snapshot:await page.evaluate(()=>AITuberTV.snapshot()),status:await page.locator('#status').textContent()});throw error;});
   if(scenario==='clear'){
    peer.send(JSON.stringify({type:'clear',generation:1}));
    await page.waitForFunction(()=>AITuberTV.snapshot().id===null);
    assert.equal(await page.evaluate(()=>speechFlag),false);
   }else if(['pause','debug','reset','disconnect'].includes(scenario)){
    if(scenario==='pause')await page.locator('#pause').click();
    if(scenario==='debug')await page.locator('#debugFlag').check();
    if(scenario==='reset')await page.locator('#reset').click();
    if(scenario==='disconnect')peer.close();
    await page.waitForFunction(()=>AITuberTV.snapshot().id===null);
    assert.equal(await page.evaluate(()=>speechFlag),false);
   }else if(scenario.endsWith('transition-failure')){
    await page.waitForFunction(()=>AITuberTV.snapshot().id===null);
    assert.ok(messages.some(m=>m.type==='failed'));
   }else{
    if(scenario==='duplicate')peer.send(JSON.stringify({type:'utterance',id:'test-'+scenario,generation:0,url:'/api/audio/test-'+scenario}));
    await page.waitForFunction(()=>AITuberTV.snapshot().phase==='draining',{},{timeout:20000});
    await page.waitForFunction(()=>AITuberTV.snapshot().id===null,{},{timeout:20000});
   }
   const trace=await page.evaluate(()=>{clearInterval(traceTimer);return window.trace;});
   const playing=trace.filter(s=>s.phase==='playing');
   if(['long','short','duplicate'].includes(scenario)){
    const start=playing[0].t;
    assert.ok(playing.some(s=>s.clip==='D'));
    assert.ok(playing.filter(s=>s.t-start>300).every(s=>s.clip==='D'));
    const draining=trace.find(s=>s.phase==='draining');assert.equal(draining.clip,'D');
    assert.ok(messages.some(m=>m.type==='ended'));
    assert.equal(messages.filter(m=>m.type==='started').length,1);
   }
   assert.deepEqual(errors,[]);
   results.push({scenario,events:messages.filter(e=>e.id),transitions:trace.filter((s,i,a)=>!i||s.phase!==a[i-1].phase||s.clip!==a[i-1].clip||s.flag!==a[i-1].flag)});
   await context.close();
  }
 }finally{await browser.close();}
 fs.mkdirSync(path.join(__dirname,'../.runtime'),{recursive:true});
 fs.writeFileSync(path.join(__dirname,'../.runtime/browser-results.json'),JSON.stringify(results,null,2));
});
