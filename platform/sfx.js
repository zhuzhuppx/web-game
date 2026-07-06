// 🎵 sfx.js - 游戏音效系统 (Web Audio API 合成，无需音频文件)
var SFX = (function(){
  var ctx = null;
  var enabled = true;
  var volume = 0.3;

  function getCtx(){
    if(!ctx){ ctx = new (window.AudioContext||window.webkitAudioContext)(); }
    if(ctx.state==='suspended') ctx.resume();
    return ctx;
  }

  // ===== 工具函数 =====
  function noise(dur){
    var c=getCtx(), len=c.sampleRate*dur;
    var buf=c.createBuffer(1,len,c.sampleRate);
    var d=buf.getChannelData(0);
    for(var i=0;i<len;i++) d[i]=(Math.random()*2-1)*0.3;
    return buf;
  }

  function playBuf(buf,opt){
    opt=opt||{};
    var c=getCtx(), s=c.createBufferSource();
    s.buffer=buf;
    var g=c.createGain();
    g.gain.value=(opt.vol!=null?opt.vol:1)*volume;
    if(opt.detune) s.detune.value=opt.detune;
    g.connect(c.destination);
    s.connect(g);
    s.start(c.currentTime+(opt.delay||0));
    if(opt.loop){s.loop=true;return s}
    s.stop(c.currentTime+(opt.dur||buf.duration)+(opt.delay||0));
  }

  function tone(freq,dur,type,opt){
    opt=opt||{};
    var c=getCtx(), o=c.createOscillator();
    o.type=type||'square';
    o.frequency.value=freq;
    var g=c.createGain();
    g.gain.setValueAtTime((opt.vol!=null?opt.vol:1)*volume, c.currentTime+(opt.delay||0));
    g.gain.exponentialRampToValueAtTime(0.001, c.currentTime+(opt.delay||0)+dur);
    g.connect(c.destination);
    o.connect(g);
    o.start(c.currentTime+(opt.delay||0));
    o.stop(c.currentTime+(opt.delay||0)+dur);
  }

  // ===== 音效预设 =====

  // UI 点击
  function click(){ tone(800,0.05,'sine'); }
  function tap(){ tone(600,0.04,'sine'); }

  // 收集/拾取
  function collect(){
    tone(880,0.08,'sine');
    setTimeout(function(){tone(1320,0.08,'sine')},60);
  }

  // 射击
  function shoot(){
    var buf=noise(0.06);
    playBuf(buf,{vol:0.4});
    tone(200,0.1,'square',{vol:0.3});
  }

  // 爆炸
  function boom(){
    var buf=noise(0.25);
    playBuf(buf,{vol:0.6});
    tone(60,0.3,'sawtooth',{vol:0.5,detune:-300});
  }

  // 受伤
  function hurt(){
    tone(200,0.15,'sawtooth',{vol:0.4,detune:-200});
  }

  // 得分
  function score(){
    tone(523,0.1,'sine');
    setTimeout(function(){tone(659,0.1,'sine')},80);
    setTimeout(function(){tone(784,0.15,'sine')},160);
  }

  // 成功
  function success(){
    tone(523,0.1,'sine');
    setTimeout(function(){tone(659,0.1,'sine')},100);
    setTimeout(function(){tone(784,0.1,'sine')},200);
    setTimeout(function(){tone(1047,0.2,'sine')},300);
  }

  // 失败/错误
  function fail(){
    tone(300,0.15,'sawtooth',{vol:0.3});
    setTimeout(function(){tone(200,0.2,'sawtooth',{vol:0.3})},120);
  }

  // 跳跃
  function jump(){
    tone(400,0.06,'sine');
    setTimeout(function(){tone(600,0.06,'sine')},40);
  }

  // 升级/强化
  function powerup(){
    tone(440,0.08,'sine');
    setTimeout(function(){tone(554,0.08,'sine')},70);
    setTimeout(function(){tone(659,0.08,'sine')},140);
    setTimeout(function(){tone(880,0.15,'sine')},210);
  }

  // 倒计时 tick
  function tick(){ tone(1000,0.03,'sine'); }

  // 消息提示
  function notify(){ tone(1200,0.06,'sine');tone(1600,0.06,'sine',{delay:0.04}); }

  // 移动/滑动
  function whoosh(){
    var buf=noise(0.1);
    playBuf(buf,{vol:0.2,detune:800});
  }

  // 闪现/瞬移
  function teleport(){
    tone(300,0.15,'sine',{detune:1200});
  }

  // ===== 公共 API =====
  return {
    enabled: function(v){ if(v!==undefined) enabled=v; return enabled; },
    volume: function(v){ if(v!==undefined) volume=Math.max(0,Math.min(1,v)); return volume; },
    resume: function(){ var c=getCtx(); if(c.state==='suspended') c.resume(); },
    // 预设
    click: click, tap: tap, collect: collect, shoot: shoot, boom: boom,
    hurt: hurt, score: score, success: success, fail: fail, jump: jump,
    powerup: powerup, tick: tick, notify: notify, whoosh: whoosh, teleport: teleport,
    // 自定义音效
    tone: tone, noise: function(d){return playBuf(noise(d))}
  };
})();
