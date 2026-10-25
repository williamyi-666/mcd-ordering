const fs=require('fs');
const html=fs.readFileSync('../assets/mcdcraft.html','utf8');
const js=html.match(/<script>([\s\S]*)<\/script>/)[1];
const noop=()=>{};
const ctxStub=new Proxy({},{get:(t,k)=>k==='measureText'?(()=>({width:10})):noop,set:()=>true});
const els={};
function mkEl(id){return{id,classList:{toggle(){},add(){},remove(){},contains(){return false}},style:{},textContent:'',innerHTML:'',onclick:null,getContext:()=>ctxStub,width:880,height:440};}
global.document={getElementById(id){if(!els[id])els[id]=mkEl(id);return els[id];},addEventListener(){}};
global.window={close(){},addEventListener(){}};
global.localStorage={_d:{},getItem(){return null;},setItem(){}};
global.requestAnimationFrame=()=>0;
global.setTimeout=()=>0;
global.clearTimeout=noop;
global.location={search:''};

const EX = fs.readFileSync('./exports.js','utf8');
const tail = '\n})();';
const idx = js.lastIndexOf('\n})();');
const patched = js.slice(0, idx) + '\n' + EX + tail;
eval(patched);

const M = global.__MCD;
if(!M){ console.log('导出失败'); process.exit(1); }

let totalUnreachable = 0, totalItems = 0, worst = null;
const GY = M.getGroundY();

for(let round=0; round<20; round++){
  M.startGame();
  const items = M.getItems().map(function(i){ return Object.assign({}, i); });
  const plats = M.getPlatforms();
  const stands = [{x:0, y:GY-26}];
  for(const p of plats) stands.push({x:p.x, y:p.y-26});

  for(const it of items){
    totalItems++;
    let reachable = false;
    for(const st of stands){
      const px = Math.max(0, Math.min(it.x - 9, 862));
      M.setPlayer({x:px, y:st.y, vx:0, vy:0, onGround:true, inv:0, face:1});
      const k = M.getKeys();
      for(let f=0; f<80; f++){
        k[' '] = (f < 3);
        M.update();
        if(M.rectHit(M.getPlayer(), it)){ reachable = true; break; }
      }
      k[' '] = false;
      if(reachable) break;
    }
    if(!reachable){
      totalUnreachable++;
      const near = plats.filter(function(pl){ return it.x >= pl.x-30 && it.x <= pl.x+pl.w+30; })
        .map(function(pl){ return {x:Math.round(pl.x),y:Math.round(pl.y),w:pl.w,itemY:Math.round(it.y)}; });
      console.log('   不可达:', it.name, 'x='+Math.round(it.x), 'y='+Math.round(it.y), '| 相关平台:', JSON.stringify(near));
      const onPlat = plats.filter(pl => Math.abs((it.y+16)-pl.y) < 30).map(pl=>({x:Math.round(pl.x),y:Math.round(pl.y),w:pl.w}));
      console.log('  不可达:', it.name, 'x='+Math.round(it.x), 'y='+Math.round(it.y),
                  '| 所属平台:', JSON.stringify(onPlat),
                  '| 落脚点:', JSON.stringify(stands.map(s=>({x:Math.round(s.x),y:Math.round(s.y)}))));
      if(!worst || it.y < worst.y) worst = it;
    }
  }
}

console.log('总食材数  :', totalItems);
console.log('不可达数  :', totalUnreachable);
if(worst) console.log('最差样本  :', worst.name, 'x='+Math.round(worst.x), 'y='+Math.round(worst.y));
console.log(totalUnreachable===0 ? 'PASS: 全部食材可达' : 'FAIL: 存在不可达食材');
process.exit(totalUnreachable===0?0:1);
