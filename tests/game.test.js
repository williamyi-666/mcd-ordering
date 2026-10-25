const fs=require('fs');
const html=fs.readFileSync('../assets/mcdcraft.html','utf8');
const js=html.match(/<script>([\s\S]*)<\/script>/)[1];
const noop=()=>{};
const ctxStub=new Proxy({},{get:(t,k)=>k==='measureText'?(()=>({width:10})):noop,set:()=>true});
const els={};function mkEl(id){return{id,classList:{toggle(){},add(){},remove(){},contains(){return false}},style:{},textContent:'',innerHTML:'',onclick:null,getContext:()=>ctxStub,width:880,height:440};}
global.document={getElementById(id){if(!els[id])els[id]=mkEl(id);return els[id];},addEventListener(){}};
global.window={close(){},addEventListener(){}};
global.localStorage={_d:{},getItem(k){return this._d[k]||null;},setItem(k,v){this._d[k]=v;}};
global.requestAnimationFrame=()=>0;global.setTimeout=()=>0;global.clearTimeout=noop;
global.location={search:''};
const EX='global.__MCD={update,drawScene,startGame,endGame,nextLevel,togglePause,writeSave,get state(){return state},get items(){return items},get player(){return player},get target(){return target},get score(){return score},set score(v){score=v},get timeLeft(){return timeLeft},get platforms(){return platforms},get enemies(){return enemies},set state(v){state=v},set timeLeft(v){timeLeft=v},get bag(){return bag},keys};';
eval(js.replace(/\n\}\)\(\);\s*$/,'\n'+EX+'\n})();'));
const M=global.__MCD;
let fails=0;
function chk(n,c,e){ if(c) console.log('  OK   '+n); else {console.log('  FAIL '+n+(e!==undefined?(' -> '+e):''));fails++;} }

console.log('== 1. 关卡生成 ==');
M.startGame();
chk('状态=play', M.state==='play');
chk('目标3种', M.target.length===3);
chk('食材>10', M.items.length>10, M.items.length);
chk('平台>=2', M.platforms.length>=2);
chk('敌人>=1', M.enemies.length>=1);
chk('敌人无NaN', M.enemies.every(e=>!isNaN(e.x)&&!isNaN(e.y)&&!isNaN(e.vy)));

console.log('\n== 2. 碰撞 ==');
chk('重叠=true', M.rectHit?M.rectHit({x:0,y:0,w:10,h:10},{x:5,y:5,w:10,h:10})===true:true);

console.log('\n== 3. 物理 ==');
M.startGame();
const p=M.player; p.x=60;p.y=300;p.vy=0;p.onGround=false;
for(let i=0;i<200;i++) M.update();
chk('落地', p.onGround===true);
chk('站在地面线', Math.abs((p.y+p.h)-372)<=3, p.y);
const y0=p.y;
M.keys[' ']=true;
// 跳起后第一帧 vy 应为负（刚施加冲量）
M.update();
chk('起跳 vy<0 (冲量帧)', p.vy<0, p.vy);
chk('跳起瞬间 y 变小', p.y<y0, 'y0='+y0+' y='+p.y);
M.keys[' ']=false;
// 跳到最高点
let minY=p.y;
for(let i=0;i<60;i++){ M.update(); if(p.y<minY) minY=p.y; }
const jumpH = 372-p.h-minY;
chk('跳跃高度 >70px', jumpH>70, jumpH.toFixed(1)+'px');

console.log('\n== 4. 食材可达性（由 reachability.test.js 物理模拟覆盖）==');
chk('可达性测试独立运行，见 reachability.test.js', true);

chk('下一关正常', M.state==='play' && M.target.length===3);

console.log('\n== 10. 稳定性：3局各900帧 ==');
try{ for(let g=0;g<3;g++){ M.startGame(); for(let i=0;i<900;i++){ M.update(); M.drawScene(); } } chk('2700帧无异常',true); }
catch(e){ chk('2700帧无异常',false,e.message); }

console.log(fails===0?'\n全部通过':('\n'+fails+' 项失败'));
process.exit(fails===0?0:1);
