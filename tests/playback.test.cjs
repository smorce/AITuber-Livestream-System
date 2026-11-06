const {test}=require('node:test');
const assert=require('node:assert/strict');
const {PlaybackState,chooseIdle}=require('../web/playback-core.js');

test('待機素材を連続選択しない',()=>{
 for(let i=0;i<100;i++)assert.notEqual(chooseIdle([0,1,2],1),1);
 assert.equal(chooseIdle([1],1),1);
 assert.equal(chooseIdle([],1),null);
});
test('音声が終わるまでフラグOFFでも待機へ戻さない',()=>{
 const s=new PlaybackState();s.prepare('a',2);s.start();s.flag=false;
 assert.equal(s.canIdle(),false);s.audioEnded();assert.equal(s.canIdle(),true);
});
test('短い音声は先行時間を縮める',()=>{
 const s=new PlaybackState();s.prepare('a',0.1);assert.equal(s.lead,0.025);
});
test('D終端が音声終了より早ければOFFにしない',()=>{
 const s=new PlaybackState();s.prepare('a',10);s.start();
 assert.equal(s.shouldOff(0.18,0.1),false);
 assert.equal(s.shouldOff(0.18,0.3),true);
});
test('古い音声完了イベントは次の発話を終了させない',()=>{
 const s=new PlaybackState();s.prepare('a',1);s.cancel();s.prepare('b',2);s.start();
 s.audioEnded('a');assert.equal(s.canIdle(),false);
});
test('D終端と音声終了の前後200msでも早期待機を防ぐ',()=>{
 for(const audioDuration of [.05,1,14.84,15.04,15.24,30.08,45]){
  for(const speed of [.25,1,2]){
   const s=new PlaybackState();s.prepare('a',audioDuration);s.start();
   const clipDuration=15.04/speed;
   for(let t=0;t<audioDuration;t+=.01){
    const audioRemaining=audioDuration-t,clipRemaining=clipDuration-t%clipDuration;
    if(s.shouldOff(audioRemaining,clipRemaining))assert.ok(clipRemaining>audioRemaining);
    assert.equal(s.canIdle(),false);
   }
   s.audioEnded();assert.equal(s.canIdle(),true);
  }
 }
});
