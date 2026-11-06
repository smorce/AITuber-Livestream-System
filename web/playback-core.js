(function(root){
 'use strict';
 function chooseIdle(available,previous,random=Math.random){
   if(!available.length)return null;
   const choices=available.filter(x=>x!==previous);
   const pool=choices.length?choices:available;
   return pool[Math.floor(random()*pool.length)];
 }
 class PlaybackState{
   constructor(config={}){this.config={audio_lead:.15,off_lead:.2,...config};this.cancel();}
   prepare(id,duration){this.id=id;this.duration=duration;this.lead=Math.min(this.config.audio_lead,duration*.25);this.phase='prepared';this.flag=false;this.done=false;}
   start(){this.phase='playing';this.flag=true;}
   audioEnded(id=this.id){if(id!==this.id)return;this.done=true;this.flag=false;this.phase='draining';}
   canIdle(){return !this.id||this.done;}
   shouldOff(audioRemaining,clipRemaining){return audioRemaining<=this.config.off_lead&&clipRemaining>audioRemaining+.05;}
   cancel(){this.id=null;this.phase='idle';this.flag=false;this.done=true;}
 }
 const api={PlaybackState,chooseIdle};
 if(typeof module!=='undefined')module.exports=api;else root.AITuberPlayback=api;
})(typeof globalThis!=='undefined'?globalThis:this);
