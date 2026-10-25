#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""生成骰子动画演示页（全屏剧场模式 + 投后揭示）。"""
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))

embed = json.load(open(os.path.join(HERE, "embed.json"), encoding="utf-8"))
ALL216 = embed["all216"]
POOL = embed["pool"]
META = embed["meta"]

TEMPLATE = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>骰子选餐 · 三骰 216 级</title>
<style>
*{box-sizing:border-box;margin:0;padding:0}
html,body{height:100%}
body{background:#FAF8F5;color:#1C1A18;
  font-family:system-ui,-apple-system,"Segoe UI","Microsoft YaHei",sans-serif;
  display:flex;justify-content:center;padding:28px 16px 44px}
.wrap{width:100%;max-width:720px}

.head{display:flex;align-items:baseline;gap:10px;margin-bottom:4px}
.head h1{font-size:17px;font-weight:600}
.head span{font-size:12px;color:#8A8178}
.ctx{font-size:12.5px;color:#6B635A;margin-bottom:20px;line-height:1.7}
.ctx b{color:#1C1A18;font-weight:600}

.card{background:#fff;border:1px solid #E8E2D8;border-radius:16px;
  padding:24px 22px 22px;margin-bottom:14px;transition:padding .3s}
.card.compact{padding:14px 22px}

.idle{text-align:center;padding:26px 0 30px}
.idle .mini{display:flex;justify-content:center;gap:16px;margin-bottom:20px;
  perspective:700px}
.idle .mini .die{--s:52px}
.idle p{font-size:13px;color:#8A8178}

.btn{display:block;width:100%;padding:15px;border:0;border-radius:12px;
  background:#DA291C;color:#fff;font-size:15px;font-weight:600;
  font-family:inherit;cursor:pointer;letter-spacing:.5px;
  transition:background .15s,transform .1s}
.btn:hover{background:#C02215}
.btn:active{transform:scale(.99)}
.btn:disabled{background:#D9D3C9;color:#8A8178;cursor:default}
.btn.free{background:#FFC72C;color:#1C1A18}
.btn.free:hover{background:#F0B71F}

.result{display:none}
.result.reveal{display:block;animation:rise .5s cubic-bezier(.2,.9,.25,1)}
@keyframes rise{from{opacity:0;transform:translateY(16px)}to{opacity:1;transform:none}}

.rhead{display:flex;align-items:center;gap:10px;flex-wrap:wrap;
  padding-bottom:14px;border-bottom:1px solid #F0EBE2}
.points{font-size:32px;font-weight:600;line-height:1}
.points small{font-size:14px;font-weight:500;color:#8A8178;margin-left:3px}
.badge{font-size:12px;padding:4px 10px;border-radius:20px;
  background:#F5F1E9;color:#6B635A;font-weight:500}
.badge.gold{background:#FFF6DE;color:#8A6A12}
.tag{font-size:12px;color:#8A8178;margin-left:auto}

.pick{padding:16px 0 4px}
.pick .name{font-size:21px;font-weight:600;line-height:1.35;margin-bottom:8px}
.pick .price{font-size:27px;font-weight:600;color:#DA291C}
.pick .price small{font-size:13px;font-weight:500;color:#8A8178;margin-left:8px}
.meta{font-size:12.5px;color:#8A8178;margin-top:12px;line-height:1.8}
.meta b{color:#1C1A18;font-weight:600}
.meta code{font-family:ui-monospace,Consolas,monospace;background:#F5F1E9;
  padding:2px 5px;border-radius:4px;color:#6B635A}

.bar{padding:16px 0 2px}
.bar .lbl{display:flex;justify-content:space-between;font-size:11.5px;
  color:#8A8178;margin-bottom:7px}
.bars{display:flex;align-items:flex-end;gap:3px;height:44px}
.bars .b{flex:1;background:#EDE7DC;border-radius:2px 2px 0 0;
  transition:background .35s}
.bars .b.hit{background:#DA291C}
.bars .b.near{background:#F5C4B3}

.note{font-size:12px;color:#8A8178;line-height:1.75}
.note b{color:#6B635A;font-weight:600}
.note code{font-family:ui-monospace,Consolas,monospace;background:#F5F1E9;
  padding:1px 5px;border-radius:4px}

/* ---------- 全屏剧场层 ---------- */
/* 默认 display:none，显示时立即不透明（不依赖过渡，避免漏底） */
.overlay{position:fixed;inset:0;z-index:60;background:#141210;
  display:none;flex-direction:column;align-items:center;justify-content:center}
.overlay.on{display:flex}
.overlay.closing .ovstage,
.overlay.closing .ovshadow,
.overlay.closing .ovlabel,
.overlay.closing .ovtag{opacity:0;transition:opacity .26s}

.ovstage{display:flex;gap:34px;perspective:1500px;align-items:flex-start}
.ovdie{display:flex;flex-direction:column;align-items:center}
.ovdie .die{--s:118px}
.ovpip{font-size:12.5px;color:#5F5E5A;margin-top:18px;height:16px;
  transition:color .25s,opacity .25s;opacity:.35;font-variant-numeric:tabular-nums}
.ovpip.on{color:#FFC72C;opacity:1}
.ovdie.lock{animation:pop .32s ease}
@keyframes pop{0%{transform:translateY(0)}
  45%{transform:translateY(-7px)}100%{transform:translateY(0)}}

.ovshadow{width:420px;max-width:80vw;height:9px;border-radius:50%;
  background:rgba(255,255,255,.07);filter:blur(9px);margin-top:6px;
  transition:width .45s,opacity .45s;opacity:.85}
.ovshadow.small{width:300px;opacity:1}

.ovlabel{font-size:12.5px;color:#7A736A;margin-top:34px;height:18px;
  letter-spacing:.5px;transition:color .3s}
.ovlabel.hot{color:#FFC72C}

.ovsum{font-size:62px;font-weight:600;color:#FFFEFB;margin-top:6px;
  line-height:1;opacity:0;transform:scale(.92);
  transition:opacity .3s,transform .35s cubic-bezier(.2,.9,.25,1);
  font-variant-numeric:tabular-nums}
.ovsum.on{opacity:1;transform:none}
.ovsum small{font-size:19px;color:#7A736A;margin-left:8px;font-weight:500}

.ovtag{font-size:13px;padding:6px 16px;border-radius:20px;margin-top:16px;
  background:#242019;color:#FFC72C;opacity:0;transform:translateY(6px);
  transition:opacity .3s,transform .3s}
.ovtag.on{opacity:1;transform:none}

/* ---------- 骰子本体（尺寸由 --s 控制） ---------- */
.die{--s:76px;width:var(--s);height:var(--s);position:relative;
  transform-style:preserve-3d;will-change:transform}
.face{position:absolute;inset:0;background:#FFFEFB;border-radius:calc(var(--s)*.17);
  display:grid;grid-template-columns:repeat(3,1fr);grid-template-rows:repeat(3,1fr);
  padding:calc(var(--s)*.115);backface-visibility:hidden;
  box-shadow:inset 0 0 0 1px rgba(0,0,0,.05)}
.face i{display:flex;align-items:center;justify-content:center}
.face i::after{content:'';width:calc(var(--s)*.135);height:calc(var(--s)*.135);
  border-radius:50%;background:transparent;transition:background .2s}
.face i.on::after{background:#1C1A18}
.hot .face i.on::after{background:#DA291C}
.f1{transform:rotateY(0deg)    translateZ(calc(var(--s)/2))}
.f6{transform:rotateY(180deg)  translateZ(calc(var(--s)/2))}
.f2{transform:rotateY(90deg)   translateZ(calc(var(--s)/2))}
.f5{transform:rotateY(-90deg)  translateZ(calc(var(--s)/2))}
.f3{transform:rotateX(90deg)   translateZ(calc(var(--s)/2))}
.f4{transform:rotateX(-90deg)  translateZ(calc(var(--s)/2))}

@media (max-width:560px){
  .ovstage{gap:18px}
  .ovdie .die{--s:86px}
  .ovsum{font-size:46px}
}

@media (prefers-reduced-motion:reduce){
  .result.reveal{animation:none}
  .ovdie.lock{animation:none}
}
</style>
</head>
<body>

<div class="overlay" id="overlay">
  <div class="ovstage" id="ovstage"></div>
  <div class="ovshadow" id="ovshadow"></div>
  <div class="ovlabel" id="ovlabel">准备掷骰</div>
  <div class="ovsum" id="ovsum"></div>
  <div class="ovtag" id="ovtag"></div>
</div>

<div class="wrap">
  <div class="head">
    <h1>骰子选餐</h1>
    <span>三骰 · 216 级强度阶梯</span>
  </div>
  <div class="ctx">__CTX__</div>

  <div class="card">
    <div class="idle" id="idle">
      <div class="mini" id="mini"></div>
      <p>点下面开始 —— 骰子会占满屏幕</p>
    </div>
    <button class="btn" id="btn">掷 骰</button>
  </div>

  <div class="card result" id="result">
    <div class="rhead">
      <div class="points"><span id="pts">0</span><small>点</small></div>
      <div class="badge" id="struct">—</div>
      <div class="tag" id="tag"></div>
    </div>
    <div class="pick">
      <div class="name" id="pname">—</div>
      <div class="price"><span id="pprice">0</span><small>元 · 实付价</small></div>
      <div class="meta" id="pmeta"></div>
    </div>
    <div class="bar">
      <div class="lbl"><span>便宜</span><span>候选池 __N__ 个，按实付价升序</span><span>最贵</span></div>
      <div class="bars" id="bars"></div>
    </div>
  </div>

  <div class="card note">
    <b>这一掷是真算的</b>，不是随机挑一个名字。<br>
    三颗骰子给出 <b>216 种</b>等概率组合，按「总和 → 最大骰 → 中位骰 → 最小骰」
    排成强度阶梯；候选池按实付价升序，第 <code>floor(阶梯位 × N ÷ 216)</code>
    个就是结果。同一组骰面永远得到同一份餐，且<b>点数越大、价格越高</b>
    （阶梯单调违例 0）。
  </div>
</div>

<script>
const ALL216 = "__ALL216__";
const POOL = __POOL__;

const TRIPLES = ALL216.match(/.{3}/g).map(s => s.split('').map(Number));
const RANK = new Map();
TRIPLES.forEach((t, i) => RANK.set(t.join(''), i));

const FACE_ROT = {1:{x:0,y:0}, 6:{x:0,y:180}, 2:{x:0,y:-90},
                  5:{x:0,y:90}, 3:{x:-90,y:0}, 4:{x:90,y:0}};
const PIP = {1:[5], 2:[3,7], 3:[3,5,7], 4:[1,3,7,9], 5:[1,3,5,7,9], 6:[1,3,4,6,7,9]};
const LABEL = {豹子:'幸运三连', 顺子:'顺水一局', 对子:'双拼日', 散牌:'日常局'};
const REROLL = {豹子:true, 顺子:true, 对子:false, 散牌:false};

function buildDie() {
  const d = document.createElement('div');
  d.className = 'die';
  [1,2,3,4,5,6].forEach(f => {
    const face = document.createElement('div');
    face.className = 'face f' + f;
    for (let i = 1; i <= 9; i++) {
      const cell = document.createElement('i');
      if (PIP[f].includes(i)) cell.className = 'on';
      face.appendChild(cell);
    }
    d.appendChild(face);
  });
  return d;
}

function structureOf(t) {
  const s = [...t].sort((a,b)=>a-b);
  if (s[0] === s[2]) return '豹子';
  if (s[0] === s[1] || s[1] === s[2]) return '对子';
  if (s[2] - s[0] === 2 && new Set(s).size === 3) return '顺子';
  return '散牌';
}

const isReduced = () => window.matchMedia('(prefers-reduced-motion: reduce)').matches;
const sleep = ms => new Promise(r => setTimeout(r, ms));
const easeOutCubic = t => 1 - Math.pow(1 - t, 3);

function setRot(el, x, y, z) {
  el.style.transform = 'rotateX(' + x + 'deg) rotateY(' + y +
                       'deg) rotateZ(' + (z || 0) + 'deg)';
}

/* 单颗骰子：滚动 → 缓动落定 */
function spinDie(el, face, rollDur) {
  return new Promise(resolve => {
    const base = FACE_ROT[face];
    const tilt = (Math.random() - 0.5) * 6;
    if (isReduced()) { setRot(el, base.x, base.y, tilt); resolve(); return; }

    const settleDur = 760;
    const sx = 900 + Math.random() * 460;
    const sy = 1060 + Math.random() * 540;
    let cx = Math.random() * 360, cy = Math.random() * 360;
    const t0 = performance.now();
    let last = t0, settled = false;

    function frame(now) {
      const dt = (now - last) / 1000;
      last = now;
      if (now - t0 < rollDur) {
        cx = (cx + sx * dt) % 360;
        cy = (cy + sy * dt) % 360;
        setRot(el, cx, cy, 0);
        requestAnimationFrame(frame);
        return;
      }
      if (!settled) {
        settled = true;
        const tx = base.x + 360 * Math.ceil((cx - base.x) / 360 + 1);
        const ty = base.y + 360 * Math.ceil((cy - base.y) / 360 + 1);
        const s0 = now, ax = cx, ay = cy;
        function settle(n2) {
          const p = Math.min(1, (n2 - s0) / settleDur);
          const e = easeOutCubic(p);
          setRot(el, ax + (tx - ax) * e, ay + (ty - ay) * e, tilt * e);
          if (p < 1) requestAnimationFrame(settle);
          else resolve();
        }
        requestAnimationFrame(settle);
      }
    }
    requestAnimationFrame(frame);
  });
}

function countUp(el, target, dur) {
  return new Promise(resolve => {
    if (isReduced()) { el.innerHTML = target + '<small>点</small>'; resolve(); return; }
    const t0 = performance.now();
    function f(now) {
      const p = Math.min(1, (now - t0) / dur);
      const v = Math.round(easeOutCubic(p) * target);
      el.innerHTML = v + '<small>点</small>';
      if (p < 1) requestAnimationFrame(f); else resolve();
    }
    requestAnimationFrame(f);
  });
}

/* ---------- 构建 ---------- */
const mini = document.getElementById('mini');
const MINI_FACE = [3, 5, 2];
for (let i = 0; i < 3; i++) {
  const w = document.createElement('div');
  const d = buildDie();
  const fr = FACE_ROT[MINI_FACE[i]];
  d.style.transform = 'rotateX(' + fr.x + 'deg) rotateY(' + fr.y + 'deg) rotateZ(-8deg)';
  w.appendChild(d);
  mini.appendChild(w);
}

const ovstage = document.getElementById('ovstage');
const ovdies = [], ovpips = [];
for (let i = 0; i < 3; i++) {
  const wrapEl = document.createElement('div');
  wrapEl.className = 'ovdie';
  const d = buildDie();
  const pip = document.createElement('div');
  pip.className = 'ovpip';
  wrapEl.appendChild(d);
  wrapEl.appendChild(pip);
  ovstage.appendChild(wrapEl);
  ovdies.push(d);
  ovpips.push(pip);
}

const bars = document.getElementById('bars');
(function () {
  const min = POOL[0].total, max = POOL[POOL.length - 1].total;
  POOL.forEach(p => {
    const b = document.createElement('div');
    b.className = 'b';
    const h = 16 + 84 * (max === min ? .5 : (p.total - min) / (max - min));
    b.style.height = h + '%';
    bars.appendChild(b);
  });
})();

const overlay = document.getElementById('overlay');
const ovlabel = document.getElementById('ovlabel');
const ovsum = document.getElementById('ovsum');
const ovtag = document.getElementById('ovtag');
const ovshadow = document.getElementById('ovshadow');
const resultEl = document.getElementById('result');
const btn = document.getElementById('btn');
let busy = false;

/* ---------- 主流程 ---------- */
async function doRoll() {
  if (busy) return;
  busy = true;
  btn.disabled = true;
  btn.textContent = '掷骰中…';
  btn.classList.remove('free');
  resultEl.classList.remove('reveal');

  // 预先把结果算好（动画期间不展示）
  const dice = [0,0,0].map(() => 1 + Math.floor(Math.random() * 6));
  const sum = dice.reduce((a,b) => a + b, 0);
  const rank = RANK.get(dice.join(''));
  const n = POOL.length;
  const idx = Math.min(Math.floor(rank * n / 216), n - 1);
  const item = POOL[idx];
  const st = structureOf(dice);

  // --- 进入全屏剧场 ---
  ovdies.forEach((d, i) => {
    d.classList.remove('hot');
    setRot(d, Math.random() * 360, Math.random() * 360, 0);
    ovpips[i].classList.remove('on');
    ovpips[i].textContent = '';
  });
  ovsum.classList.remove('on');
  ovsum.innerHTML = '';
  ovtag.classList.remove('on');
  ovshadow.classList.remove('small');
  ovlabel.classList.remove('hot');
  ovlabel.textContent = '骰子滚动中';
  overlay.classList.add('on');

  await sleep(isReduced() ? 0 : 300);

  // --- 三颗并行滚动，逐颗落定 ---
  const durs = [980, 1140, 1060];
  let landed = 0;
  const tasks = ovdies.map((d, i) =>
    sleep(i * 110).then(() => spinDie(d, dice[i], durs[i])).then(() => {
      landed++;
      d.classList.add('hot');
      d.parentElement.classList.add('lock');
      setTimeout(() => d.parentElement.classList.remove('lock'), 340);
      ovpips[i].textContent = dice[i] + ' 点';
      ovpips[i].classList.add('on');
      ovshadow.classList.toggle('small', landed >= 3);
      ovlabel.textContent = landed < 3
        ? '已落定 ' + landed + ' / 3'
        : '全部落定';
    })
  );
  await Promise.all(tasks);

  // --- 展示点数 ---
  ovlabel.classList.add('hot');
  ovlabel.textContent = '本 次 点 数';
  ovsum.classList.add('on');
  await countUp(ovsum, sum, isReduced() ? 0 : 520);

  await sleep(isReduced() ? 0 : 220);
  ovtag.textContent = st + ' · ' + LABEL[st] +
                      (REROLL[st] ? '　可免费重投' : '');
  ovtag.classList.add('on');

  await sleep(isReduced() ? 120 : 950);

  // --- 收起剧场，揭示结果 ---
  overlay.classList.add('closing');
  await sleep(isReduced() ? 0 : 280);
  overlay.classList.remove('on');
  overlay.classList.remove('closing');

  document.getElementById('pts').textContent = sum;
  const sb = document.getElementById('struct');
  sb.textContent = st + ' · ' + LABEL[st];
  sb.className = 'badge' + (REROLL[st] ? ' gold' : '');
  document.getElementById('tag').textContent =
    '骰面 ' + dice.join('-') + '　阶梯 ' + rank + '/216';
  document.getElementById('pname').textContent = item.name;
  document.getElementById('pprice').textContent = item.total.toFixed(1);

  const total = item.total * (item.kind === '组合' ? 1 : 1);
  let meta = '合计 <b>' + total.toFixed(1) + ' 元</b>　人均 <b>' +
             (total / 1).toFixed(1) + ' 元</b>　' +
             '阶梯第 <code>' + rank + '</code> 位 → 候选第 <code>' +
             (idx + 1) + '/' + n + '</code> 位';
  if (item.memberPrice) {
    meta += '　原价 ' + item.listPrice.toFixed(1) + ' 元，有会员可省 ' +
            (item.listPrice - item.memberPrice).toFixed(1) + ' 元';
  }
  document.getElementById('pmeta').innerHTML = meta;

  document.querySelectorAll('.bars .b').forEach((b, i) => {
    b.classList.remove('hit','near');
    if (i === idx) b.classList.add('hit');
    else if (Math.abs(i - idx) === 1) b.classList.add('near');
  });

  document.getElementById('idle').style.display = 'none';
  btn.closest('.card').classList.add('compact');
  resultEl.classList.add('reveal');

  if (REROLL[st]) {
    btn.textContent = '免费重投';
    btn.classList.add('free');
  } else {
    btn.textContent = '再掷一次';
  }
  btn.disabled = false;
  busy = false;
}

btn.addEventListener('click', doRoll);
setTimeout(doRoll, 500);
</script>
</body>
</html>
"""

ctx = ("门店 <b>%s</b>　人数 <b>%d</b>　预算 <b>%s</b>　忌口 <b>%s</b>　%s"
       % (META["storeName"], META["people"], META["band"],
          "、".join(META["restrictions"]) or "无", META["channel"]))

html = (TEMPLATE
        .replace("__ALL216__", ALL216)
        .replace("__POOL__", json.dumps(POOL, ensure_ascii=False))
        .replace("__CTX__", ctx)
        .replace("__N__", str(len(POOL))))

out = os.path.join(ROOT, "assets", "dice-demo.html")
os.makedirs(os.path.dirname(out), exist_ok=True)
with open(out, "w", encoding="utf-8") as f:
    f.write(html)
print("已生成:", out)
print("大小: %.1f KB" % (len(html.encode("utf-8")) / 1024))
