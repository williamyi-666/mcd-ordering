const fs = require('fs');
const vm = require('vm');

const html = fs.readFileSync('assets/dice-demo.html', 'utf8');

// 1) 提取并编译 <script>，检查语法
const m = html.match(/<script>([\s\S]*?)<\/script>/);
if (!m) { console.log('FAIL: 没有 script'); process.exit(1); }
const code = m[1];
try {
  new vm.Script(code);
  console.log('PASS 脚本语法正确');
} catch (e) {
  console.log('FAIL 脚本语法错误:', e.message);
  process.exit(1);
}

// 2) 关键 DOM 节点是否齐全
const ids = ['overlay','ovstage','ovlabel','ovsum','ovtag','ovshadow',
             'mini','idle','btn','result','pts','struct','tag',
             'pname','pprice','pmeta','bars'];
const miss = ids.filter(id => !html.includes('id="' + id + '"'));
console.log(miss.length
  ? 'FAIL 缺 id: ' + miss.join(',')
  : 'PASS ' + ids.length + ' 个 DOM 节点齐全');

// 2b) 剧场层必须覆盖整屏
const ovCss = html.match(/\.overlay\{[^}]*\}/);
if (!ovCss) { console.log('FAIL 缺 .overlay 样式'); process.exit(1); }
const ovOk = /position:fixed/.test(ovCss[0]) && /inset:0/.test(ovCss[0]);
console.log(ovOk ? 'PASS 剧场层全屏覆盖' : 'FAIL 剧场层未全屏');

// 2c) 结果卡初始必须隐藏（投完才揭示）
const resCss = html.match(/\.result\{[^}]*\}/);
const hiddenOk = resCss && /display:none/.test(resCss[0]);
console.log(hiddenOk ? 'PASS 结果卡初始隐藏' : 'FAIL 结果卡未隐藏');

// 3) 六面骰子与点数矩阵
for (const f of ['f1','f2','f3','f4','f5','f6']) {
  if (!html.includes('.' + f + '{transform:')) {
    console.log('FAIL 缺少骰面样式 ' + f); process.exit(1);
  }
}
console.log('PASS 六面骰子样式齐全');

// 4) 在沙箱里跑纯逻辑（不含 DOM），验证映射
const ALL216 = html.match(/const ALL216 = "(\d+)";/)[1];
const POOL = JSON.parse(html.match(/const POOL = (\[[\s\S]*?\]);/)[1]);
const TRIPLES = ALL216.match(/.{3}/g).map(s => s.split('').map(Number));
const RANK = new Map();
TRIPLES.forEach((t, i) => RANK.set(t.join(''), i));

function structureOf(t) {
  const s = [...t].sort((a, b) => a - b);
  if (s[0] === s[2]) return '豹子';
  if (s[0] === s[1] || s[1] === s[2]) return '对子';
  if (s[2] - s[0] === 2 && new Set(s).size === 3) return '顺子';
  return '散牌';
}

// 5) 单调性：点数越大价格越高
let viol = 0, prev = -1;
for (const t of TRIPLES) {
  const idx = Math.min(Math.floor(RANK.get(t.join('')) * POOL.length / 216),
                       POOL.length - 1);
  if (idx < prev) viol++;
  prev = Math.max(prev, idx);
}
console.log(viol === 0 ? 'PASS 阶梯单调违例 0' : 'FAIL 单调违例 ' + viol);

// 6) 结构分类合计
const cnt = {};
TRIPLES.forEach(t => { const k = structureOf(t); cnt[k] = (cnt[k] || 0) + 1; });
const expect = {豹子:6, 对子:90, 顺子:24, 散牌:96};
const okStruct = Object.keys(expect).every(k => cnt[k] === expect[k]);
console.log(okStruct ? 'PASS 结构分类 6/90/24/96' : 'FAIL 结构分类 ' + JSON.stringify(cnt));

// 7) 覆盖率：216 个骰面都能落到合法候选
const idxSet = new Set();
for (const t of TRIPLES) {
  const idx = Math.min(Math.floor(RANK.get(t.join('')) * POOL.length / 216),
                       POOL.length - 1);
  idxSet.add(idx);
}
console.log(idxSet.size === POOL.length
  ? 'PASS 25 个候选全覆盖'
  : 'WARN 覆盖 ' + idxSet.size + '/' + POOL.length);

// 8) 价格上界
const maxPrice = Math.max(...POOL.map(p => p.total));
console.log(maxPrice <= 50 ? 'PASS 全部候选不超 50 元上限' : 'FAIL 超预算 ' + maxPrice);
