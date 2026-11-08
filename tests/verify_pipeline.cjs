// 実LLM・TTS・SoulXを呼び出す手動検証。通常のテストには含めない。
const {chromium}=require('playwright');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');

(async()=>{
 const browser=await chromium.launch({executablePath:process.env.CHROME_PATH||'C:/Program Files/Google/Chrome/Application/chrome.exe',headless:true,args:['--autoplay-policy=no-user-gesture-required']});
 const root=path.join(__dirname,'../.runtime');
 fs.mkdirSync(root,{recursive:true});
 try{
  const chat=await browser.newPage({viewport:{width:1200,height:900}});
  await chat.goto('http://127.0.0.1:17863/');
  const tv=await browser.newPage({viewport:{width:1600,height:1000}});
  const errors=[],events=[];let videoSaved=false;
  tv.on('pageerror',error=>errors.push(error.message));
  await tv.route('**/api/video/*',async route=>{
   const response=await tv.request.get(route.request().url());
   assert.equal(response.status(),200);
   const body=await response.body();
   fs.writeFileSync(path.join(root,'pipeline-video.mp4'),body);videoSaved=true;
   await route.fulfill({response,body});
  });
  await tv.goto('http://127.0.0.1:17863/'+encodeURIComponent('ブラウン管TV_配信プラットフォーム.html')+'?autoplay=1');
  await tv.waitForFunction(()=>AITuberTV.snapshot().owner&&AITuberTV.snapshot().device==='running');
  await chat.evaluate(()=>{
   window.pipelineStates=[];
   const ws=new WebSocket(`ws://${location.host}/ws?role=chat`);
   ws.onmessage=event=>{const value=JSON.parse(event.data);if(value.type==='speech_status')pipelineStates.push(value);};
  });
  await chat.locator('#maxTokens').fill('128');
  if(await chat.locator('#thinkingBtn').getAttribute('aria-pressed')==='true')await chat.locator('#thinkingBtn').click();
  const started=Date.now();
  await chat.locator('#input').fill('動作確認です。「こんにちは。」とだけ返してください。');
  await chat.locator('#send').click();
  await tv.waitForFunction(()=>AITuberTV.snapshot().mode==='lipsync'&&AITuberTV.snapshot().phase==='playing',{},{timeout:180000}).catch(async error=>{console.error({states:await chat.evaluate(()=>pipelineStates),snapshot:await tv.evaluate(()=>AITuberTV.snapshot()),status:await tv.locator('#status').textContent()});throw error;});
  await tv.waitForFunction(()=>video===speechVideo&&!pendingTransition);
  assert.equal(await tv.evaluate(()=>speechVideo.muted),false);
  await tv.screenshot({path:path.join(root,'pipeline-tv.png')});
  await chat.screenshot({path:path.join(root,'pipeline-chat.png')});
  await chat.waitForFunction(()=>window.pipelineStates.some(state=>state.phase==='completed'),{},{timeout:30000});
  const states=await chat.evaluate(()=>pipelineStates);
  assert.ok(states.some(state=>state.phase==='video_generating'));
  assert.ok(!states.some(state=>state.warning||state.phase==='failed'));
  assert.ok(videoSaved);
  assert.deepEqual(errors,[]);
  const result={elapsed_seconds:(Date.now()-started)/1000,phases:states.map(state=>state.phase),device:states.findLast(state=>state.device)?.device,errors};
  fs.writeFileSync(path.join(root,'pipeline-result.json'),JSON.stringify(result,null,2));
  console.log(result);
 }finally{await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
