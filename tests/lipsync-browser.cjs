const {test}=require('node:test');
const assert=require('node:assert/strict');
const {chromium}=require('playwright');
const fs=require('node:fs');
const path=require('node:path');
const {execFileSync}=require('node:child_process');
const base=process.env.AITUBER_TEST_URL||'http://127.0.0.1:17863';

test('生成動画は終端で切り替え音声を重複させず終了し、クリアで停止する',{timeout:120000},async()=>{
 const fixture=path.join(__dirname,'../.runtime/test-lipsync.mp4');
 execFileSync('ffmpeg',['-v','error','-y','-f','lavfi','-i','color=c=blue:s=128x128:r=25:d=2','-f','lavfi','-i','sine=frequency=440:sample_rate=48000:duration=2','-c:v','libx264','-pix_fmt','yuv420p','-c:a','aac','-shortest',fixture],{windowsHide:true});
 execFileSync('ffmpeg',['-v','error','-y','-i',fixture,'-t','0.12','-c','copy',fixture+'.short.mp4'],{windowsHide:true});
 execFileSync('ffmpeg',['-v','error','-y','-i',fixture,'-vn','-c:a','pcm_s16le',fixture+'.wav'],{windowsHide:true});
 const browser=await chromium.launch({executablePath:'C:/Program Files/Google/Chrome/Application/chrome.exe',headless:true,args:['--autoplay-policy=no-user-gesture-required']});
 try{
  for(const scenario of ['normal','clear','before-error','load-error','after-error','duplicate','short']){
   const clear=scenario==='clear',fallback=['before-error','load-error'].includes(scenario);
   const page=await browser.newPage();const messages=[],errors=[];let peer,audioRequests=0;
   page.on('pageerror',error=>errors.push(error.message));
   await page.route('**/api/audio/*',route=>{audioRequests++;return route.fulfill({contentType:'audio/wav',body:fs.readFileSync(fixture+'.wav')});});
   await page.route('**/api/video/test',route=>scenario==='load-error'?route.abort():route.fulfill({contentType:'video/mp4',body:fs.readFileSync(scenario==='short'?fixture+'.short.mp4':fixture)}));
   await page.routeWebSocket('**/ws?*',ws=>{
    peer=ws;ws.onMessage(raw=>{const event=JSON.parse(raw);messages.push(event);if(event.type==='ping')ws.send(JSON.stringify({type:'pong'}));});
    ws.send(JSON.stringify({type:'hello',owner:true,generation:0,flag_lead:.3,audio_lead:.15,off_lead:.2,max_idle_overlap:.3}));
   });
   await page.goto(base+'/'+encodeURIComponent('ブラウン管TV_配信プラットフォーム.html'));
   await page.waitForFunction(()=>window.AITuberTV?.snapshot().device==='running'&&videos.every(v=>v.readyState>=2));
   await page.evaluate(()=>{video.currentTime=video.duration-3;});
   await page.waitForFunction(()=>!video.seeking);
   peer.send(JSON.stringify({type:'utterance',id:'test',generation:0,mode:'lipsync',video_url:'/api/video/test',url:'/api/audio/test'}));
   await page.waitForFunction(()=>AITuberTV.snapshot().phase==='prepared',{},{timeout:10000}).catch(async error=>{console.error({clear,messages,errors,snapshot:await page.evaluate(()=>AITuberTV.snapshot()),status:await page.locator('#status').textContent(),src:await page.evaluate(()=>speechVideo.src)});throw error;});
   if(scenario==='before-error'){
    await page.evaluate(()=>speechVideo.dispatchEvent(new Event('error')));
    await page.waitForFunction(()=>AITuberTV.snapshot().phase==='prepared'&&AITuberTV.snapshot().mode==='fixed');
   }
   assert.equal(await page.evaluate(()=>speechVideo.muted),true);
   if(scenario==='short'){
    await page.waitForFunction(()=>AITuberTV.snapshot().id===null,{},{timeout:10000});
    assert.ok(messages.some(event=>event.type==='ended'));
    assert.equal(audioRequests,0);
    assert.ok(!messages.some(event=>event.type==='failed'));
    await page.close();continue;
   }
   await page.waitForFunction(()=>AITuberTV.snapshot().phase==='playing');
   await page.waitForFunction(()=>video===speechVideo&&!pendingTransition);
   assert.equal(await page.evaluate(()=>speechVideo.muted),fallback);
   assert.equal(await page.evaluate(()=>$('mute').checked),true);
   if(scenario==='duplicate')peer.send(JSON.stringify({type:'utterance',id:'test',generation:0,mode:'lipsync',video_url:'/api/video/test',url:'/api/audio/test'}));
   if(scenario==='after-error'){
    await page.evaluate(()=>speechVideo.dispatchEvent(new Event('error')));
    await page.waitForFunction(()=>AITuberTV.snapshot().id===null);
    assert.ok(messages.some(e=>e.type==='failed'));
   }else if(clear){
    peer.send(JSON.stringify({type:'clear',generation:1}));
    await page.waitForFunction(()=>AITuberTV.snapshot().id===null);
    assert.equal(await page.evaluate(()=>speechVideo.paused&&speechVideo.muted),true);
   }else{
    await page.evaluate(()=>{$('speed').value='1.5';$('speed').dispatchEvent(new Event('input'));});
    assert.equal(await page.evaluate(()=>speechVideo.muted),fallback);
    await page.waitForFunction(()=>AITuberTV.snapshot().id===null);
    assert.ok(messages.some(e=>e.type==='ended'));
   }
   assert.equal(audioRequests,fallback?1:0);
   assert.equal(messages.filter(e=>e.type==='started').length,1);
   if(scenario!=='after-error')assert.ok(!messages.some(e=>e.type==='failed'));
   if(fallback)assert.ok(messages.some(e=>e.type==='fallback'));
   assert.deepEqual(errors,[]);
   await page.close();
  }
 }finally{await browser.close();}
});
