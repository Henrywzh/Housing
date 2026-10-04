"""web/data/radar.html: the 市场雷达 page, drawn from radar.json (build_radar.py). One self-contained file."""
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[1]

PAGE = r'''<!doctype html>
<html lang="zh"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>市场雷达</title>
<style>
:root{--paper:#f2f4f6;--panel:#fff;--panel-2:#f7f9fa;--ink:#121b24;--ink-2:#3d4c58;--muted:#6a7884;--rule:#d9e0e6;--signal:#c2402a;--pos:#2c6f52;--neg:#a8382a;--blue:#3b6a9a;--amber:#b0781a;color-scheme:light}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){--paper:#0e141a;--panel:#161e26;--panel-2:#1b242d;--ink:#e7edf2;--ink-2:#b3c0cb;--muted:#8798a5;--rule:#2a353f;--signal:#e8664c;--pos:#5fb389;--neg:#e07a68;--blue:#7fa8d1;--amber:#d9a640;color-scheme:dark}}
*{box-sizing:border-box}
body{margin:0;background:var(--paper);color:var(--ink);font:400 14px/1.55 "Source Sans 3",-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}
.wrap{max-width:1120px;margin:0 auto;padding:16px}
h1{font:700 20px/1.25 Archivo,"Source Sans 3",sans-serif;margin:0 0 4px}
h2{font:600 15px/1.3 Archivo,"Source Sans 3",sans-serif;margin:0 0 4px}
h3{font:600 12.5px/1.3 Archivo,sans-serif;margin:14px 0 6px;color:var(--ink-2)}
.card{background:var(--panel);border:1px solid var(--rule);border-radius:10px;padding:14px 16px;margin-bottom:14px}
.sub{color:var(--muted);font-size:12.5px;margin:0 0 10px}
.note{font-size:12.5px;color:var(--ink-2);margin:8px 0 0}
.warn{border-left:3px solid var(--signal);padding:2px 0 2px 10px;margin:8px 0;color:var(--ink-2);font-size:13px}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(210px,1fr));gap:10px}
.tile{border:1px solid var(--rule);border-radius:8px;padding:10px 12px;background:var(--panel-2)}
.tile .l{font-size:11.5px;color:var(--muted)}
.tile .v{font:600 22px/1.2 Archivo,sans-serif;margin:2px 0}
.tile .d{font-size:12px;color:var(--ink-2)}
.up{color:var(--neg)} .dn{color:var(--pos)}      /* for rates and prices a rise is a headwind for a buyer: red */
.pb{height:5px;border-radius:3px;background:var(--rule);margin:6px 0 2px;position:relative}
.pb i{position:absolute;top:-2px;width:9px;height:9px;border-radius:50%;background:var(--ink)}
canvas{display:block;width:100%}
table{border-collapse:collapse;width:100%;font-size:12.5px}
th,td{padding:5px 8px;text-align:right;border-bottom:1px solid var(--rule);white-space:nowrap}
th:first-child,td:first-child{text-align:left}
th{font-weight:600;color:var(--muted);font-size:11.5px}
.scroll{overflow-x:auto}
.cols{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1fr);gap:16px}
@media (max-width:820px){.cols{grid-template-columns:1fr}}
.ctl{display:flex;flex-wrap:wrap;gap:8px 18px;align-items:center;margin:6px 0 10px}
.ctl label{display:flex;align-items:center;gap:6px;font-size:12.5px;color:var(--ink-2)}
.ctl input[type=number]{width:96px;font:inherit;padding:4px 6px;border:1px solid var(--rule);border-radius:6px;background:var(--panel-2);color:var(--ink)}
.ctl input[type=range]{width:150px}
.pill{display:inline-block;padding:1px 7px;border-radius:9px;font-size:11.5px;border:1px solid var(--rule);background:var(--panel-2);color:var(--ink-2)}
.big{font:600 28px/1.1 Archivo,sans-serif}
.kv{display:flex;justify-content:space-between;gap:10px;padding:5px 0;border-bottom:1px solid var(--rule);font-size:13px}
.kv span{color:var(--muted)}
.bar{display:flex;align-items:center;gap:8px;font-size:12px;margin:3px 0}
.bar .n{width:128px;color:var(--ink-2)} .bar .t{flex:1;height:10px;position:relative;background:var(--panel-2);border-radius:3px}
.bar .t i{position:absolute;top:0;height:10px;border-radius:2px}
.bar .x{width:48px;text-align:right;font-family:"IBM Plex Mono",monospace}
</style></head><body><div class="wrap">

<div class="card">
<h1>市场雷达 <span class="pill" id="asof">—</span></h1>
<p class="sub">目的：判断未来一年什么时候买合适，以及五年后房价和租金大致往哪走。这里的所有数字都是<b>领先指标、历史回测和情景推演</b>，不是对价格的预言——回测的结果也会如实写在下面，包括模型不灵的地方。不构成投资建议，买房决定请咨询持牌顾问。</p>
<div id="oneline" class="note" style="font-size:14px"></div>
</div>

<div class="card">
<h2>1 · 现在在周期的哪个位置</h2>
<p class="sub">每格：最新值、三个月和十二个月的变化、在 2005 年以来的历史里处于哪个分位（圆点越靠右越高）。红 = 对买家不利的方向（利率、房价上升），绿 = 有利。</p>
<div class="grid" id="tiles"></div>
<h3>RICS 住宅市场调查（<span id="ricsm"></span>）· 全国净差额 %</h3>
<div class="scroll"><table id="rics"></table></div>
<p class="note" id="ricsn"></p>
</div>

<div class="card">
<h2>2 · 未来 12 个月：伦敦房价往哪走</h2>
<p class="sub">从 <b id="fo">—</b>（伦敦 HPI 的最新一个月）起算，往后 12 个月的变化。几种读法放在一起，因为它们并不一致——<b>中位数从 −3% 到 +6% 都有</b>，这本身就是结论的一部分。</p>
<div class="cols">
 <div>
  <canvas id="range" height="250"></canvas>
  <div class="kv"><span>主读法：分位数回归（只用 Nationwide 近三个月走势）中位</span><b id="f_pt">—</b></div>
  <div class="kv"><span>　80% 区间（10%–90% 分位）</span><b id="f_rg">—</b></div>
  <div class="kv"><span>　下跌的概率（由分位数插值）</span><b id="f_pf">—</b></div>
  <div class="kv"><span>旧的 8 项岭回归：中位 / 80% 区间</span><b id="f_old">—</b></div>
  <div class="kv"><span>历史相似月份之后的实际结果（中位）</span><b id="f_an">—</b></div>
  <div class="kv"><span>1995 年以来伦敦任意 12 个月（中位 / 10–90%）</span><b id="f_un">—</b></div>
  <div class="kv"><span>「和过去一年一样」</span><b id="f_nv">—</b></div>
 </div>
 <div>
  <h3 style="margin-top:0">这个简单模型在说什么</h3>
  <div id="simple_eq"></div>
  <p class="note">它只有一个输入。Nationwide 的近三个月走势是各家模型里在 2005–2017 年表现最好的单个信号（见下面 2b）；它其实是在说「房价最近的势头会持续一段时间」，不是一个独立于房价的领先指标。</p>
 </div>
</div>
<h3>回测：8 项岭回归（旧的主模型）过去有多准？</h3>
<p class="sub">每个月只用当时已经公布的数据，预测之后 12 个月伦敦 HPI 的变化，和「房价继续做过去一年做的事」比较。RMSE 越小越准，单位是百分点。更简单的模型和留出检验见 2b。</p>
<div class="scroll"><table id="bt"></table></div>
<canvas id="rec" height="210" style="margin-top:10px"></canvas>
<p class="note" id="btn"></p>
</div>

<div class="card" id="simple">
<h2>2b · 8 个输入太多吗？更简单的模型、留出检验和分位数回归</h2>
<p class="sub">三个问题：输入之间是不是重复了？有没有更简单、更好解释的模型？样本外检验有没有做对？答案分别在下面。</p>
<h3 style="margin-top:4px">① 输入之间的相关性</h3>
<div class="scroll"><table id="sx_corr"></table></div>
<p class="note" id="sx_corr_n"></p>
<h3>② 一堆更简单的模型，样本外比较（每月重新拟合，只用当时已公布的数据）</h3>
<p class="sub">选模型只用<b>到 2017-12 为止</b>的月份（它们的结果到 2018-12 已知）；<b>2019-01 起是锁住的留出样本</b>，选完之后才看一次。选择规则：误差在最好那个的一个标准误之内、输入最少的那个。</p>
<div class="scroll"><table id="sx_models"></table></div>
<p class="note" id="sx_models_n"></p>
<h3>③ 分位数回归：直接预测区间</h3>
<p class="sub">在选出的输入上，分别回归第 10、25、50、75、90 百分位。对照两种更简单的做法：只用历史上的分布（不看任何输入），以及「线性回归 + 它自己的残差分位数」。看<b>覆盖率</b>（实际落进区间的比例，80% 区间理想是 80%）和<b>分位损失</b>（越低越好）。</p>
<div class="scroll"><table id="sx_q"></table></div>
<canvas id="sx_band" height="230" style="margin-top:10px"></canvas>
<p class="note" id="sx_q_n"></p>
</div>

<div class="card" id="exp">
<h2>2c · 两个改进实验：调参，以及「房价相对收入是否太贵」</h2>
<p class="sub">规则在看结果之前就定好了（见下），所有模型在<b>完全相同的月份</b>上比较。结果是真实的，包括没有改善的。</p>
<h3 style="margin-top:4px">① 岭回归的惩罚强度（λ）</h3>
<p class="sub">之前固定用 30，是拍脑袋定的。λ 越大，模型越保守，越接近「只看平均水平」。<b>规则：</b>每个预测月只用当时的训练数据，向前滚动选 λ（嵌套交叉验证）；只要不比固定 30 更差就采用。</p>
<div class="scroll"><table id="exp_pen"></table></div>
<p class="note" id="exp_pen_n"></p>
<h3>② 估值项：房价/收入、月供/收入</h3>
<p class="sub">两个估值项都用「相对自己迄今平均值的偏离」（只用当时已有的数据算均值）：房价÷全国平均周薪，以及按当时 2 年固定利率算的月供÷全国平均周薪。<b>规则：</b>总误差更低，<b>并且</b>三个子时期中至少两个更低，<b>并且</b>在「同去年」错得最离谱（≥ 8 个百分点）的转折月里不更差，才加入预测。</p>
<div class="scroll"><table id="exp_val"></table></div>
<p class="note" id="exp_val_n"></p>
<div class="grid" id="exp_now" style="margin-top:10px"></div>
</div>

<div class="card">
<h2>3 · 什么时候买：利率、季节和价格一起算</h2>
<p class="sub">按揭利率取央行的 2 年期固定（75% LTV）当前水平，之后每个月按<b>掉期远期曲线</b>（市场对未来利率的定价）推算；价格用上面模型的区间，再叠加季节因素。</p>
<div class="ctl">
 <label>房价 £<input type="number" id="price" value="500000" step="10000" min="100000"></label>
 <label>首付 %<input type="number" id="dep" value="25" min="5" max="90"></label>
 <label>年限<input type="number" id="term" value="25" min="5" max="40"> 年</label>
</div>
<div class="cols">
 <div><canvas id="pay" height="240"></canvas><p class="note" id="payn"></p></div>
 <div class="scroll"><table id="paytab"></table>
 <h3>季节因素（Nationwide，2000 年至今，相对季调趋势）</h3><canvas id="season" height="110"></canvas></div>
</div>
<p class="note" id="timing"></p>
</div>

<div class="card">
<h2>4 · 五年：房价和租金的情景推演</h2>
<p class="sub">五年后没有可靠的点预测：1995 年以来只有约 6 个互不重叠的五年窗口，拟合不出东西。这里改成「你设定假设，我算后果」，并把历史范围放在旁边做参照。</p>
<div class="ctl">
 <label>名义收入年增长 <input type="range" id="eg" min="0" max="7" step="0.25" value="3.5"><b id="egv"></b></label>
 <label>五年后的 2 年固定按揭利率 <input type="range" id="r5" min="2" max="8" step="0.1" value="4.5"><b id="r5v"></b></label>
 <label>利率变化传导到房价的比例 <input type="range" id="pt" min="0" max="60" step="5" value="15"><b id="ptv"></b></label>
 <label>租金相对收入的额外增长 <input type="range" id="rx" min="-2" max="3" step="0.25" value="0.5"><b id="rxv"></b></label>
</div>
<div class="cols">
 <div>
  <div class="kv"><span>房价（伦敦平均，现在）</span><b id="p0">—</b></div>
  <div class="kv"><span>五年后（情景）</span><b id="p5">—</b></div>
  <div class="kv"><span>年均</span><b id="pg">—</b></div>
  <div class="kv"><span>月租（伦敦平均，现在）</span><b id="r0">—</b></div>
  <div class="kv"><span>五年后（情景）</span><b id="r5o">—</b></div>
  <div class="kv"><span>公寓毛收益率：现在 → 五年后</span><b id="yl">—</b></div>
  <p class="note" id="scn"></p>
 </div>
 <div>
  <h3 style="margin-top:0">历史参照：伦敦 HPI 任意五年的年均涨幅（1995–2021 起点）</h3>
  <canvas id="five" height="170"></canvas>
  <p class="note" id="epi"></p>
 </div>
</div>
</div>

<div class="card">
<h2>5 · 数据与局限</h2>
<div class="warn"><b>预测的天花板。</b>没有一个模型在选择期（2005–2017）和锁住的留出期（2019 年起）都显著赢过「和去年一样」。选中的简单模型在前一个时期明显更好，后一个时期反而更差（见 2b）：这些指标在拐点（2008、2022）有用，在平稳期没有额外信息。区间预测比点预测靠谱一些——它在两个时期都比「只看历史分布」好，80% 区间覆盖率接近 80%，但中间 50% 部分偏窄。</div>
<div class="warn"><b>最新的数据都是临时的。</b>房价指数滞后约三个月，最近几个月的成交会被上修；按揭批贷和 Nationwide 比官方早，但不是伦敦专属（伦敦以外的全国数据）。RICS 的伦敦分项只以图表发布，这里只能读到文字部分。</div>
<div class="warn"><b>利率对房价的传导无法从历史里干净地估出来。</b>利率和房价都受经济状况同时推动，直接回归得出的符号是反的。所以情景里的「传导比例」是你设定的假设，而不是估计值；上面的例子（2021–23 年利率暴涨，可借额骤降，伦敦名义房价几乎没动）说明实际传导往往很小，但那一次通胀也很高。</div>
<div class="warn"><b>没有挂牌量和成交周期。</b>Land Registry 不记录，Rightmove、Zoopla 要买授权，抓取违反条款，所以这里没有。</div>
<div class="warn"><b>政策冲击没有进模型。</b>预算案、印花税、非居民附加税、租客权益法案、EPC 要求等，历史上常常比利率影响更大，但无法回测。</div>
<p class="note" id="srcs"></p>
</div>
</div>
<script>
const $ = id => document.getElementById(id);
const fmt = (v, d = 1) => v == null ? '—' : v.toLocaleString('en-GB', {minimumFractionDigits: d, maximumFractionDigits: d});
const sg = (v, d = 1) => { if (v == null) return '—'; const t = Math.abs(v).toFixed(d); return (+t === 0 ? '' : v > 0 ? '+' : '−') + t; };
const css = n => getComputedStyle(document.documentElement).getPropertyValue(n).trim();
const MONTHS_ZH = ['1月','2月','3月','4月','5月','6月','7月','8月','9月','10月','11月','12月'];
let R = null;

// ---------- tiny canvas helpers ----------
function canvas(id){ const c = $(id), dpr = devicePixelRatio || 1, w = c.clientWidth, h = +c.getAttribute('height');
  c.width = w * dpr; c.height = h * dpr; c.style.height = h + 'px'; const g = c.getContext('2d'); g.scale(dpr, dpr); g.font = '11px "IBM Plex Mono",monospace'; return {g, w, h}; }
function axes(g, w, h, m, x0, x1, y0, y1, xf, yf, nx = 4, ny = 4){
  g.strokeStyle = css('--rule'); g.fillStyle = css('--muted'); g.lineWidth = 1;
  for (let i = 0; i <= ny; i++){ const v = y0 + (y1 - y0) * i / ny, y = h - m.b - (v - y0) / (y1 - y0) * (h - m.t - m.b);
    g.beginPath(); g.moveTo(m.l, y); g.lineTo(w - m.r, y); g.stroke(); g.textAlign = 'right'; g.fillText(yf(v), m.l - 5, y + 4); }
  for (let i = 0; i <= nx; i++){ const v = x0 + (x1 - x0) * i / nx, x = m.l + (v - x0) / (x1 - x0) * (w - m.l - m.r);
    g.textAlign = 'center'; g.fillText(xf(v), x, h - m.b + 14); }
}
function spark(g, vals, x, y, w, h, color){
  const v = vals.filter(a => a != null), lo = Math.min(...v), hi = Math.max(...v), r = hi - lo || 1;
  g.strokeStyle = color; g.lineWidth = 1.5; g.beginPath();
  vals.forEach((a, i) => { const px = x + i / (vals.length - 1) * w, py = y + h - (a - lo) / r * h; i ? g.lineTo(px, py) : g.moveTo(px, py); }); g.stroke();
}
const annuity = (r, n) => { const i = r / 1200; return i / (1 - Math.pow(1 + i, -n * 12)); };
const payment = (P, r, n) => P * annuity(r, n);
const gbp = v => '£' + Math.round(v).toLocaleString('en-GB');

// ---------- 1 · where things are ----------
function tiles(){
  const order = ['bank_rate', 'mort2y75', 'mort5y75', 'glc_spot2y', 'glc_spot5y', 'approvals', 'nw_sa', 'hmrc_eng'];
  const rateLike = new Set(['bank_rate', 'mort2y75', 'mort5y75', 'glc_spot2y', 'glc_spot5y']);
  $('tiles').innerHTML = order.filter(k => R.current[k]).map(k => { const c = R.current[k], isRate = rateLike.has(k);
    const unit = c.unit, v = unit === '%' ? fmt(c.value, 2) + '%' : unit === '指数' ? fmt(c.value, 0) : fmt(c.value, 0);
    const d = (x) => x == null ? '—' : (unit === '%' ? sg(x, 2) + ' pp' : unit === '指数' ? sg(x / (c.value - x) * 100, 1) + '%' : sg(x / (c.value - x) * 100, 0) + '%');
    const cls = x => x == null ? '' : (isRate || k === 'nw_sa' ? (x > 0 ? 'up' : 'dn') : (x > 0 ? 'dn' : 'up'));
    return `<div class="tile"><div class="l">${c.label} · ${c.month}</div><div class="v">${v}</div>
      <div class="d">3 个月 <span class="${cls(c.chg3)}">${d(c.chg3)}</span> · 12 个月 <span class="${cls(c.chg12)}">${d(c.chg12)}</span></div>
      ${unit === '指数' ? '<div class="d" style="color:var(--muted);margin-top:8px">指数长期上行，所以不看分位</div>' : `<div class="pb"><i style="left:calc(${c.pct}% - 4px)"></i></div><div class="d" style="color:var(--muted)">2005 年以来第 ${Math.round(c.pct)} 百分位</div>`}
      <canvas height="34" data-k="${k}"></canvas></div>`; }).join('');
  for (const cv of document.querySelectorAll('#tiles canvas')){
    const {g, w, h} = canvas2(cv); spark(g, R.current[cv.dataset.k].spark, 0, 3, w, h - 6, css('--blue')); }
}
function canvas2(c){ const dpr = devicePixelRatio || 1, w = c.clientWidth, h = +c.getAttribute('height'); c.width = w * dpr; c.height = h * dpr; c.style.height = h + 'px';
  const g = c.getContext('2d'); g.scale(dpr, dpr); return {g, w, h}; }
function rics(){
  if (!R.rics){ $('rics').innerHTML = ''; return; }
  $('ricsm').textContent = R.rics.survey;
  $('rics').innerHTML = '<tr><th>指标</th><th>最新</th><th>上月</th><th>说明</th></tr>' + R.rics.readings.map(r =>
    `<tr><td>${r.label}</td><td><b>${sg(r.v, 0)}</b></td><td>${r.prev == null ? '—' : sg(r.prev, 0)}</td><td style="text-align:left;white-space:normal">${r.note || ''}</td></tr>`).join('');
  $('ricsn').innerHTML = `${R.rics.london_text} ${R.rics.context} <br><span style="color:var(--muted)">手工读自 RICS 当月报告的文字部分（<a href="${R.rics.published_from}" target="_blank" rel="noopener">原文 PDF</a>）：净差额 = 认为上升的比例 − 认为下降的比例。</span>`;
}

// ---------- 2 · twelve months ----------
function pfall(q){          // probability of a fall, by interpolating between the quantiles
  const pts = [[0.1, q['0.1']], [0.25, q['0.25']], [0.5, q['0.5']], [0.75, q['0.75']], [0.9, q['0.9']]];
  if (pts[0][1] >= 0) return '< 10%';
  if (pts[4][1] <= 0) return '> 90%';
  for (let i = 0; i < 4; i++){ const [t0, v0] = pts[i], [t1, v1] = pts[i + 1]; if (v0 <= 0 && v1 > 0) return Math.round((t0 + (t1 - t0) * (0 - v0) / (v1 - v0)) * 100) + '%'; }
  return '—';
}
function forecast(){
  const f = R.forecast, an = R.analogues, L = R.london, S = R.simple, q = S.now.quantiles, un = S.now.unconditional;
  $('fo').textContent = S.now.origin;
  $('f_pt').textContent = sg(q['0.5']) + '%';
  $('f_rg').textContent = `${sg(q['0.1'])}% … ${sg(q['0.9'])}%`;
  $('f_pf').textContent = pfall(q);
  $('f_old').textContent = `${sg(f.p50)}%（${sg(f.p10)} … ${sg(f.p90)}）`;
  $('f_an').textContent = `${sg(an.p50)}%（${sg(an.p10)} … ${sg(an.p90)}，${Math.round(an.share_up * 100)}% 上涨）`;
  $('f_un').textContent = `${sg(un['0.5'])}%（${sg(un['0.1'])} … ${sg(un['0.9'])}）`;
  $('f_nv').textContent = sg(L.price_yoy) + '%';
  const {g, w, h} = canvas('range'), m = {l: 112, r: 14, t: 10, b: 24};
  const rows = [['分位数回归（主）', q['0.1'], q['0.9'], q['0.5'], css('--blue'), q['0.25'], q['0.75']], ['8 项岭回归（旧）', f.p10, f.p90, f.p50, css('--amber'), f.p25, f.p75],
    ['历史相似月份', an.p10, an.p90, an.p50, css('--muted')], ['历史上任意 12 个月', un['0.1'], un['0.9'], un['0.5'], css('--ink-2'), un['0.25'], un['0.75']], ['和去年一样', L.price_yoy, L.price_yoy, L.price_yoy, css('--neg')]];
  const lo = Math.min(...rows.map(r => r[1])) - 3, hi = Math.max(...rows.map(r => r[2])) + 3;
  const X = v => m.l + (v - lo) / (hi - lo) * (w - m.l - m.r);
  g.strokeStyle = css('--rule'); g.fillStyle = css('--muted'); g.textAlign = 'center';
  for (let v = Math.ceil(lo / 5) * 5; v <= hi; v += 5){ g.beginPath(); g.moveTo(X(v), m.t); g.lineTo(X(v), h - m.b); g.stroke(); g.fillText(v + '%', X(v), h - m.b + 14); }
  g.strokeStyle = css('--ink'); g.beginPath(); g.moveTo(X(0), m.t); g.lineTo(X(0), h - m.b); g.stroke();
  rows.forEach(([n, a, b, mid, col, a2, b2], i) => { const y = m.t + 22 + i * 44;
    g.fillStyle = css('--ink-2'); g.textAlign = 'right'; g.fillText(n, m.l - 8, y + 4);
    g.fillStyle = col; g.globalAlpha = .28; g.fillRect(X(a), y - 8, Math.max(X(b) - X(a), 2), 16);
    if (a2 != null){ g.globalAlpha = .35; g.fillRect(X(a2), y - 8, X(b2) - X(a2), 16); }
    g.globalAlpha = 1; g.beginPath(); g.arc(X(mid), y, 5, 0, 6.283); g.fill(); });
  const c = S.now.ols_coef, nwv = S.now.input_values.nw3 * 0.75;       // nw3 is the 3-month % change times 4/3
  $('simple_eq').innerHTML = `<div class="kv"><span>London 12 个月涨幅 ≈</span><b>${fmt(c.intercept, 1)}% + ${fmt(c.nw3 * 4 / 3, 1)} × Nationwide 近三个月涨幅(%)</b></div>
    <div class="kv"><span>Nationwide 近三个月（现在）</span><b>${sg(nwv, 1)}%</b></div>
    <div class="kv"><span>线性回归的点预测</span><b>${sg(S.now.ols_point, 1)}%</b></div>
    <div class="kv"><span>「截距」的含义</span><span>Nationwide 持平时，伦敦历史上平均仍涨约 ${fmt(c.intercept, 1)}%（长期涨幅的拖拽）</span></div>
    <div class="kv"><span>训练样本</span><span>${S.now.n_train} 个月（实际约 ${Math.round(S.now.n_train / 12)} 个互相独立的 12 个月）</span></div>`;
}
function simple(){
  const S = R.simple; if (!S){ $('simple').hidden = true; return; }
  const I = S.inputs, nm = {mom12: '过去一年涨幅', mom36: '三年趋势', appr: '批贷同比', mort: '按揭利率', mort_chg6: '利率半年变', bank_chg12: 'Bank Rate 年变', slope: '曲线斜率', nw3: 'Nationwide 3 月'};
  const col = r => { const a = Math.min(1, Math.abs(r)); return r >= 0 ? `rgba(44,111,82,${.08 + .6 * a})` : `rgba(168,56,42,${.08 + .6 * a})`; };
  $('sx_corr').innerHTML = `<tr><th></th>${I.names.map(n => `<th>${nm[n]}</th>`).join('')}<th>VIF</th><th>与结果相关</th></tr>`
    + I.names.map((n, i) => `<tr><td>${nm[n]}</td>${I.corr[i].map((v, j) => `<td style="background:${i === j ? 'transparent' : col(v)}">${i === j ? '' : v.toFixed(2)}</td>`).join('')}<td>${fmt(I.vif[n], 1)}</td><td>${sg(I.corr_with_y[n], 2)}</td></tr>`).join('');
  $('sx_corr_n').innerHTML = `${I.n_rows} 个月，但相邻月份的 12 个月结果高度重叠，<b>实际只有约 ${I.n_outcomes_independent} 个互相独立的结果</b>。`
    + `<b>相关性不是主要问题：</b>最大 VIF ${fmt(Math.max(...Object.values(I.vif)), 1)}（经验上超过 5–10 才算严重），条件数 ${Math.round(I.condition)}。最像的一对是一年涨幅和三年趋势（${I.corr[0][1].toFixed(2)}），以及批贷和 Nationwide（${I.corr[2][7].toFixed(2)}）。`
    + `<b>真问题是 8 个自由系数配 ~${I.n_outcomes_independent} 个独立结果</b>，容易过拟合——这和前面「惩罚越大越好」的结果是一回事。`;
  const T = S.models, order = Object.keys(T).sort((a, b) => T[a].rmse_sel - T[b].rmse_sel), ch = S.selection.chosen;
  const pp = x => x == null ? '—' : x < 0.01 ? '<0.01' : fmt(x, 2);
  const zh = {'same as last year': '和去年一样（基准）', 'zero': '不变（0%）', 'long-run mean': '历史平均涨幅', 'momentum + lenders': '动量 + 贷款机构', 'momentum + rates': '动量 + 利率', 'lenders + rates': '贷款机构 + 利率',
    'momentum + lenders + rates': '动量 + 贷款机构 + 利率', 'average of the 2- and 3-input models': '上面几个组合模型取平均', 'lasso (8 inputs)': 'Lasso（8 项）', '2 principal components': '2 个主成分（8 项）', 'ridge (8 inputs)': '岭回归（8 项，旧模型）'};
  const label = n => n.startsWith('only ') ? '只用「' + nm[n.slice(5)] + '」' : (zh[n] || n);
  $('sx_models').innerHTML = `<tr><th>模型</th><th>输入数</th><th>选择期误差<br>到 2017-12</th><th>留出期误差<br>2019-01 起</th><th>方向对<br>选择/留出</th><th>对「和去年一样」p<br>选择/留出</th></tr>`
    + order.map(n => { const v = T[n], isNv = n === 'same as last year', isCh = n === ch;
      return `<tr${isNv ? ' style="color:var(--muted)"' : isCh ? ' style="font-weight:600"' : ''}><td>${label(n)}${isCh ? '（选中）' : ''}</td><td>${v.k}</td><td>${fmt(v.rmse_sel, 2)}</td><td style="color:${!isNv && v.rmse_hold < T['same as last year'].rmse_hold ? 'var(--pos)' : isNv ? 'inherit' : 'var(--neg)'}">${fmt(v.rmse_hold, 2)}</td><td>${n === 'zero' ? '—' : Math.round(v.hit_sel * 100) + '% / ' + Math.round(v.hit_hold * 100) + '%'}</td><td>${isNv ? '—' : pp(v.dm_sel_p) + ' / ' + pp(v.dm_hold_p)}</td></tr>`; }).join('');
  const c = T[ch], nv = T['same as last year'], r8 = T['ridge (8 inputs)'];
  $('sx_models_n').innerHTML = `共 ${S.n_common} 个月（${S.common_from} 至 ${S.common_to}）：选择期 ${S.n_sel} 个月，留出期 ${S.n_hold} 个月。<b>读法：</b>`
    + `1）8 项岭回归在选择期误差 ${fmt(r8.rmse_sel, 2)}，<b>只用 Nationwide 近三个月走势这一个输入</b>是 ${fmt(c.rmse_sel, 2)}，更好；「和去年一样」是 ${fmt(nv.rmse_sel, 2)}。输入越多并没有越准。`
    + `2）按规则选出的是「${label(ch)}」。<b>但在锁住的留出期它是 ${fmt(c.rmse_hold, 2)}，输给了「和去年一样」的 ${fmt(nv.rmse_hold, 2)}；</b>留出期里只有「不变」${fmt(T['zero'].rmse_hold, 2)} 和「三年趋势」${fmt(T['only mom36'].rmse_hold, 2)} 赢了——2019 年以来伦敦房价几乎原地不动，任何带漂移的模型都吃亏。`
    + `3）绿色 = 留出期比「和去年一样」更准。<b>在两个时期误差都更小的，只有「三年趋势」和没有信息的「不变」，而且差异都不显著；</b>在选择期显著的几个（p≈0.05），到留出期都输了。所以这些预测只是弱证据。`;
  const Q = S.quantile, mq = ['quantile regression', 'OLS + residual quantiles', 'unconditional history'], zq = {'quantile regression': '分位数回归', 'OLS + residual quantiles': '线性回归 + 残差分位数', 'unconditional history': '只用历史分布（不看输入）'};
  $('sx_q').innerHTML = `<tr><th>方法</th><th colspan="4">选择期（${S.n_sel} 个月）</th><th colspan="4">留出期（${S.n_hold} 个月）</th></tr><tr><th></th>`
    + ['分位损失', '80% 覆盖', '50% 覆盖', '80% 宽度'].map(h => `<th>${h}</th>`).join('') + ['分位损失', '80% 覆盖', '50% 覆盖', '80% 宽度'].map(h => `<th>${h}</th>`).join('') + '</tr>'
    + mq.map(m => { const a = Q.selection[m], b = Q.holdout[m];
      return `<tr${m === 'quantile regression' ? ' style="font-weight:600"' : ''}><td>${zq[m]}</td><td>${fmt(a.pinball_mean, 2)}</td><td>${Math.round(a.cov80 * 100)}%</td><td>${Math.round(a.cov50 * 100)}%</td><td>${fmt(a.width80, 1)}</td><td>${fmt(b.pinball_mean, 2)}</td><td>${Math.round(b.cov80 * 100)}%</td><td>${Math.round(b.cov50 * 100)}%</td><td>${fmt(b.width80, 1)}</td></tr>`; }).join('');
  const qa = Q.selection['quantile regression'], qb = Q.holdout['quantile regression'], ua = Q.selection['unconditional history'], ub = Q.holdout['unconditional history'], oa = Q.selection['OLS + residual quantiles'];
  $('sx_q_n').innerHTML = `输入：${S.quantile_inputs.map(n => nm[n]).join('、')}。<b>读法：</b>`
    + `1）把 Nationwide 近三个月走势放进去，分位损失比「只看历史分布」低 ${Math.round((1 - qa.pinball_mean / ua.pinball_mean) * 100)}%（选择期）和 ${Math.round((1 - qb.pinball_mean / ub.pinball_mean) * 100)}%（留出期），在<b>两个时期都成立</b>。区间预测比点预测更站得住。`
    + `2）80% 区间的覆盖率 ${Math.round(qa.cov80 * 100)}% 和 ${Math.round(qb.cov80 * 100)}%，接近理想的 80%；但 50% 区间在留出期只覆盖了 ${Math.round(qb.cov50 * 100)}%（理想 50%），说明<b>中间部分偏窄、过于自信</b>。`
    + `3）<b>分位数回归并没有比「线性回归 + 残差分位数」更好</b>（分位损失 ${fmt(qa.pinball_mean, 2)} 对 ${fmt(oa.pinball_mean, 2)}），它的好处是不需要假设误差对称。数据这么少，两者基本一样。`;
  const rec = S.record, {g, w, h} = canvas('sx_band'), mg = {l: 44, r: 10, t: 24, b: 22};
  const vals = rec.flatMap(r => [r.q10, r.q90, r.y]), lo = Math.floor(Math.min(...vals) / 10) * 10, hi = Math.ceil(Math.max(...vals) / 10) * 10;
  axes(g, w, h, mg, 0, rec.length - 1, lo, hi, v => (rec[Math.round(v)] || {s: ''}).s.slice(0, 4), v => v + '%', 5, (hi - lo) / 10);
  const X = i => mg.l + i / (rec.length - 1) * (w - mg.l - mg.r), Y = v => h - mg.b - (v - lo) / (hi - lo) * (h - mg.t - mg.b);
  g.fillStyle = css('--blue'); g.globalAlpha = .2; g.beginPath(); rec.forEach((r, i) => i ? g.lineTo(X(i), Y(r.q90)) : g.moveTo(X(i), Y(r.q90)));
  for (let i = rec.length - 1; i >= 0; i--) g.lineTo(X(i), Y(rec[i].q10)); g.closePath(); g.fill(); g.globalAlpha = 1;
  [['q50', css('--blue'), 1.4], ['y', css('--ink'), 2]].forEach(([k, col, lw]) => { g.strokeStyle = col; g.lineWidth = lw; g.beginPath(); rec.forEach((r, i) => i ? g.lineTo(X(i), Y(r[k])) : g.moveTo(X(i), Y(r[k]))); g.stroke(); });
  g.textAlign = 'left'; [['实际（之后 12 个月）', css('--ink')], ['分位数回归中位', css('--blue')], ['10–90% 区间', css('--blue')]].forEach(([t, col], i) => { g.fillStyle = col; g.fillText('— ' + t, mg.l + 8 + i * 190, 12); });
}

function backtest(){
  const bt = R.backtest, names = {all: '全部指标', 'momentum only': '只用动量', 'rates only': '只用利率', 'approvals + Nationwide': '只用批贷 + Nationwide', 'no momentum': '不含动量'};
  const per = ['至 2008', '2009–2015', '2016–'];
  $('bt').innerHTML = `<tr><th>模型</th>${per.map(p => `<th>${p} 误差</th><th>「同去年」</th>`).join('')}<th>全期 误差</th><th>全期 「同去年」</th><th>方向对的比例</th></tr>` +
    Object.entries(bt).map(([k, v]) => `<tr><td>${names[k] || k}</td>${per.map(p => { const s = v.periods[p], better = s.rmse < s.rmse_naive;
      return `<td style="color:${better ? 'var(--pos)' : 'var(--neg)'}"><b>${fmt(s.rmse)}</b></td><td>${fmt(s.rmse_naive)}</td>`; }).join('')}<td><b>${fmt(v.rmse)}</b></td><td>${fmt(v.rmse_naive)}</td><td>${Math.round(v.hit * 100)}% / ${Math.round(v.hit_naive * 100)}%</td></tr>`).join('');
  const a = bt.all;
  $('btn').innerHTML = `共 ${a.n} 个月的样本外预测（${R.backtest_from} 起，之前的月份要先留出 8 年训练）。绿色 = 比「和去年一样」准，红色 = 更差。<b>全期看模型赢，但分阶段看，2016 年之后输了。</b>方向对的比例：模型 ${Math.round(a.hit * 100)}%，「同去年」${Math.round(a.hit_naive * 100)}%。`;
  const {g, w, h} = canvas('rec'), m = {l: 44, r: 10, t: 26, b: 22}, rec = R.record;
  const ys = rec.flatMap(r => [r.pred, r.y, r.naive]);
  const lo = Math.floor(Math.min(...ys) / 10) * 10, hi = Math.ceil(Math.max(...ys) / 10) * 10;
  axes(g, w, h, m, 0, rec.length - 1, lo, hi, v => (rec[Math.round(v)] || {s: ''}).s.slice(0, 4), v => v + '%', 5, (hi - lo) / 10);
  const X = i => m.l + i / (rec.length - 1) * (w - m.l - m.r), Y = v => h - m.b - (v - lo) / (hi - lo) * (h - m.t - m.b);
  [['y', css('--ink'), 2], ['pred', css('--blue'), 1.6], ['naive', css('--amber'), 1.2]].forEach(([k, col, lw]) => {
    g.strokeStyle = col; g.lineWidth = lw; g.beginPath(); rec.forEach((r, i) => i ? g.lineTo(X(i), Y(r[k])) : g.moveTo(X(i), Y(r[k]))); g.stroke(); });
  g.textAlign = 'left'; [['实际（之后 12 个月的变化）', css('--ink')], ['模型预测', css('--blue')], ['同去年', css('--amber')]].forEach(([t, col], i) => { g.fillStyle = col; g.fillText('— ' + t, m.l + 8 + i * 200, 12); });
}

// ---------- 3 · when to buy ----------
function timing(){
  const P0 = +$('price').value, dep = +$('dep').value / 100, n = +$('term').value, q = R.simple.now.quantiles, f = {p10: q['0.1'], p50: q['0.5'], p90: q['0.9']};
  const loan = P0 * (1 - dep), now = new Date(), m0 = now.getMonth();
  const pathR = R.rate_path, season = R.season;
  const sc = [['乐观：房价 ' + sg(f.p90, 0) + '%', f.p90, css('--pos')], ['中位：' + sg(f.p50, 0) + '%', f.p50, css('--blue')], ['悲观：' + sg(f.p10, 0) + '%', f.p10, css('--neg')]];
  const rows = pathR.map(p => { const mo = (m0 + p.m) % 12 + 1, seas = (season[mo] - season[m0 % 12 + 1]);
    const cells = sc.map(([, g]) => { const price = P0 * (1 + (g * p.m / 12 + seas) / 100); return {price, pay: payment(price * (1 - dep), p.fixed2y, n)}; });
    return {m: p.m, label: MONTHS_ZH[mo - 1], r: p.fixed2y, cells}; });
  const {g, w, h} = canvas('pay'), mg = {l: 62, r: 10, t: 12, b: 24};
  const all = rows.flatMap(r => r.cells.map(c => c.pay)), lo = Math.floor(Math.min(...all) / 50) * 50, hi = Math.ceil(Math.max(...all) / 50) * 50;
  axes(g, w, h, mg, 0, 12, lo, hi, v => rows[Math.round(v)] ? rows[Math.round(v)].label : '', v => gbp(v), 6, 4);
  const X = i => mg.l + i / 12 * (w - mg.l - mg.r), Y = v => h - mg.b - (v - lo) / (hi - lo) * (h - mg.t - mg.b);
  sc.forEach(([t, , col], j) => { g.strokeStyle = col; g.lineWidth = 2; g.beginPath(); rows.forEach((r, i) => i ? g.lineTo(X(i), Y(r.cells[j].pay)) : g.moveTo(X(i), Y(r.cells[j].pay))); g.stroke();
    g.fillStyle = col; g.textAlign = 'left'; g.fillText(t, mg.l + 8 + j * 150, mg.t + 2); });
  $('payn').innerHTML = `横轴 = 在哪个月买。纵轴 = 月供（${gbp(P0)} 的房，首付 ${Math.round(dep * 100)}%，${n} 年还本付息）。三条线对应模型对未来 12 个月房价的三种结果；利率按掉期远期曲线推算。`;
  const pick = [0, 3, 6, 9, 12];
  $('paytab').innerHTML = '<tr><th>买入时间</th><th>2 年固定利率（推算）</th><th>月供（中位）</th><th>较现在</th><th>月供范围</th></tr>' + pick.map(i => { const r = rows[i], base = rows[0].cells[1].pay, c = r.cells[1].pay;
    const lo_ = Math.min(...r.cells.map(c => c.pay)), hi_ = Math.max(...r.cells.map(c => c.pay));
    return `<tr><td>${i === 0 ? '现在' : '+' + i + ' 个月（' + r.label + '）'}</td><td>${fmt(r.r, 2)}%</td><td><b>${gbp(c)}</b></td><td class="${c > base ? 'up' : 'dn'}">${sg((c / base - 1) * 100, 1)}%</td><td>${gbp(lo_)} – ${gbp(hi_)}</td></tr>`; }).join('');
  // seasonality
  const {g: g2, w: w2, h: h2} = canvas('season'), v = Array.from({length: 12}, (_, i) => season[i + 1]), mx = Math.max(...v.map(Math.abs));
  v.forEach((x, i) => { const bw = (w2 - 20) / 12, xx = 10 + i * bw, y0 = h2 / 2 - 8; g2.fillStyle = x >= 0 ? css('--neg') : css('--pos'); g2.globalAlpha = .75;
    g2.fillRect(xx + 3, x >= 0 ? y0 - x / mx * (y0 - 8) : y0, bw - 6, Math.abs(x) / mx * (y0 - 8)); g2.globalAlpha = 1;
    g2.fillStyle = css('--muted'); g2.textAlign = 'center'; g2.fillText(MONTHS_ZH[i], xx + bw / 2, h2 - 2); });
  const cheapest = v.indexOf(Math.min(...v)) + 1, dearest = v.indexOf(Math.max(...v)) + 1;
  const cur = R.rate_path[0], end = R.rate_path[12];
  $('timing').innerHTML = `<b>怎么读：</b>1）市场隐含的 2 年固定利率从现在的 ${fmt(cur.fixed2y, 2)}% 到 12 个月后的 ${fmt(end.fixed2y, 2)}%，${end.fixed2y > cur.fixed2y ? '<b>市场在定价利率上行</b>，晚买的利率更高' : '市场在定价利率下行，晚买的利率更低'}。`
    + ` 2）房价模型的中位只有 ${sg(f.p50, 0)}%，但区间很宽（${sg(f.p10, 0)}% 到 ${sg(f.p90, 0)}%），等待既可能便宜也可能更贵。`
    + ` 3）季节：全英国平均，${MONTHS_ZH[cheapest - 1]}的房价比季调趋势低 ${fmt(-v[cheapest - 1], 1)}%，${MONTHS_ZH[dearest - 1]}高 ${fmt(v[dearest - 1], 1)}%，差约 ${fmt(v[dearest - 1] - v[cheapest - 1], 1)} 个百分点——幅度有限，而且是全国数据。`
    + ` 4）10 月 28 日的预算案是 RICS 受访者普遍提到的不确定因素。<span style="color:var(--muted)">这些都是历史规律与市场定价，不能替代你对居住时间和资金的判断。</span>`;
}

// ---------- 4 · five years ----------
function five(){
  const eg = +$('eg').value, r5 = +$('r5').value, pt = +$('pt').value / 100, rx = +$('rx').value, L = R.london, n = +$('term').value || 25;
  $('egv').textContent = eg.toFixed(2) + '%'; $('r5v').textContent = r5.toFixed(1) + '%'; $('ptv').textContent = Math.round(pt * 100) + '%'; $('rxv').textContent = sg(rx, 2) + '%';
  const rNow = R.mort_now, cap = annuity(rNow, 25) / annuity(r5, 25) - 1;     // borrowing power at the same payment
  const capYr = Math.pow(1 + cap, 1 / 5) - 1, g = (1 + eg / 100) * (1 + pt * capYr) - 1;
  const p5 = L.price * Math.pow(1 + g, 5), rg = (1 + (eg + rx) / 100), rent5 = L.rent * Math.pow(rg, 5);
  $('p0').textContent = gbp(L.price) + '（' + L.month + '）'; $('p5').textContent = gbp(p5); $('pg').textContent = sg(g * 100, 1) + '% / 年';
  $('r0').textContent = gbp(L.rent) + '（' + L.rent_month + '）'; $('r5o').textContent = gbp(rent5);
  const y0 = L.rent_flat * 12 / L.flat_price * 100, y5 = L.rent_flat * Math.pow(rg, 5) * 12 / (L.flat_price * Math.pow(1 + g, 5)) * 100;
  $('yl').textContent = fmt(y0, 1) + '% → ' + fmt(y5, 1) + '%';
  $('scn').innerHTML = `情景含义：同样的月供，利率从 ${fmt(rNow, 2)}% 变成 ${fmt(r5, 1)}%，可借额变化 ${sg(cap * 100, 0)}%；其中 ${Math.round(pt * 100)}% 传导到房价（每年 ${sg(pt * capYr * 100, 1)}%），再叠加收入增长 ${fmt(eg, 2)}%。`;
  const f = R.five_year, e = R.episode;
  const {g: gg, w, h} = canvas('five'), mg = {l: 36, r: 8, t: 8, b: 22}, d = R.five_year_by_start, ks = Object.keys(d);
  const mx = Math.ceil(Math.max(...Object.values(d), 16) / 2) * 2;
  axes(gg, w, h, mg, 0, ks.length, 0, mx, () => '', v => v + '%', 1, 4);
  const bw = (w - mg.l - mg.r) / ks.length;
  gg.fillStyle = css('--muted'); gg.textAlign = 'center'; gg.font = '10px "IBM Plex Mono",monospace';
  ks.forEach((k, i) => gg.fillText(k.slice(2, 4), mg.l + i * bw + bw / 2, h - mg.b + 14));
  ks.forEach((k, i) => { gg.fillStyle = css('--blue'); gg.globalAlpha = .75; const hh = d[k] / mx * (h - mg.t - mg.b); gg.fillRect(mg.l + i * bw + 3, h - mg.b - hh, bw - 6, hh); gg.globalAlpha = 1; });
  const y = v => h - mg.b - v / mx * (h - mg.t - mg.b); gg.strokeStyle = css('--signal'); gg.setLineDash([4, 3]); gg.beginPath(); gg.moveTo(mg.l, y(g * 100)); gg.lineTo(w - mg.r, y(g * 100)); gg.stroke(); gg.setLineDash([]);
  gg.fillStyle = css('--signal'); gg.textAlign = 'right'; gg.fillText('你的情景 ' + sg(g * 100, 1) + '%', w - mg.r, y(g * 100) - 4);
  $('epi').innerHTML = `1995 年以来的任意五年窗口：年均 ${sg(f.p10, 1)}% 到 ${sg(f.p90, 1)}%（10–90 分位），中位 ${sg(f.p50, 1)}%，没有一个窗口是负的。<b>这是一个偏乐观的样本</b>——只有约 ${f.independent_windows} 个互不重叠的窗口，起点都在 1995 年之后的上行期，2008 年后的下跌被后面的涨幅覆盖。`
    + `<br>传导系数的参照：${e.from} 到 ${e.to}，2 年固定利率从 ${fmt(e.r_from, 1)}% 升到 ${fmt(e.r_to, 1)}%，同样月供的可借额减少 ${fmt(-e.capacity, 0)}%，而到 ${e.end} 伦敦名义房价只变了 ${sg(e.london_price, 1)}%（同期通胀很高，实际价格是下降的）。所以 15% 左右的传导比例并不离谱，但这是一次观测，不是估计。`;
}

function sources(){
  $('srcs').innerHTML = `来源：Bank of England（Bank Rate、按揭批贷、2/5 年固定按揭利率、国债收益率曲线、SONIA 掉期曲线与远期）、Nationwide HPI、HMRC 月度房产交易（${'英格兰'}）、HM Land Registry UK HPI、ONS 私人租金指数、RICS 住宅市场调查。生成于 ${R.generated}。`;
  $('asof').textContent = '房价数据到 ' + R.asof_hpi + ' · 利率到 ' + R.mort_now_month;
  const f = R.forecast, e = R.rate_path[12], c = R.current, S = R.simple, q = S.now.quantiles, T = S.models;
  const rateWord = e.fixed2y > R.mort_now + .05 ? `市场定价一年后升到 ${fmt(e.fixed2y, 2)}%` : e.fixed2y < R.mort_now - .05 ? `市场定价一年后降到 ${fmt(e.fixed2y, 2)}%` : `市场定价一年后大体不变（${fmt(e.fixed2y, 2)}%）`;
  const ap = c.approvals ? (c.approvals.chg12 < 0 ? `按揭批贷同比减少 ${fmt(-c.approvals.chg12 / (c.approvals.value - c.approvals.chg12) * 100, 0)}%` : `按揭批贷同比增加 ${fmt(c.approvals.chg12 / (c.approvals.value - c.approvals.chg12) * 100, 0)}%`) : '';
  const nw = c.nw_sa ? `Nationwide 近三个月 ${sg(c.nw_sa.chg3 / c.nw_sa.value * 100, 1)}%` : '';
  const beat = T[S.selection.chosen].rmse_hold < T['same as last year'].rmse_hold;
  $('oneline').innerHTML = `<b>一句话：</b>2 年固定按揭利率 ${fmt(R.mort_now, 2)}%，${rateWord}；${ap}；${nw}。简单模型对未来 12 个月伦敦房价的中位预测是 <b>${sg(q['0.5'], 0)}%</b>，80% 区间 ${sg(q['0.1'], 0)}% 到 ${sg(q['0.9'], 0)}%；旧的 8 项模型是 ${sg(f.p50, 0)}%。各种读法的中位数相差好几个百分点，${beat ? '' : '而且在 2019 年以来的留出样本里，没有任何模型显著赢过「和去年一样」，'}所以更该看区间而不是中位数。租金同比 ${sg(R.london.rent_yoy, 1)}%，公寓毛收益率约 ${fmt(R.london.yield_flat, 1)}%。`;
}

function experiments(){
  const E = R.experiments; if (!E){ $('exp').hidden = true; return; }
  const pen = E.penalty, keys = ['lam0.3', 'lam1', 'lam3', 'lam10', 'lam30', 'lam100', 'lam300', 'lam1000'];
  const best = keys.reduce((a, k) => pen[k].rmse < pen[a].rmse ? k : a, keys[0]);
  $('exp_pen').innerHTML = '<tr><th>惩罚强度 λ</th><th>总误差 RMSE</th><th>2016 年以来</th><th>转折月误差</th><th>方向对</th></tr>'
    + keys.map(k => { const v = pen[k], lam = k.slice(3);
      return `<tr${k === best ? ' style="font-weight:600"' : ''}><td>${lam}${lam === '30' ? '（原来）' : ''}${k === best ? '（事后最优）' : ''}</td><td>${fmt(v.rmse, 2)}</td><td>${fmt(v.post2016, 2)}</td><td>${fmt(v.turn.rmse, 2)}</td><td>${Math.round(v.hit * 100)}%</td></tr>`; }).join('')
    + `<tr style="font-weight:600"><td>每月重新选择（嵌套）</td><td>${fmt(pen.nested.rmse, 2)}</td><td>${fmt(pen.nested.post2016, 2)}</td><td>${fmt(pen.nested.turn.rmse, 2)}</td><td>${Math.round(pen.nested.hit * 100)}%</td></tr>`
    + `<tr style="color:var(--muted)"><td>「和去年一样」</td><td>${fmt(E.naive_rmse, 2)}</td><td>${fmt(E.naive_post2016, 2)}</td><td>—</td><td>—</td></tr>`;
  const ch = E.nested_lambda_choices, tot = Object.values(ch).reduce((a, b) => a + b, 0), big = (ch['100.0'] || 0) + (ch['300.0'] || 0) + (ch['1000.0'] || 0);
  $('exp_pen_n').innerHTML = `共 ${E.common_n} 个月（${E.common_from} 至 ${E.common_to}）。<b>结论：</b>`
    + `1）λ 越大越好，到 100–300 最低（${fmt(pen[best].rmse, 2)}，比原来的 30 低 ${fmt((1 - pen[best].rmse / pen.lam30.rmse) * 100, 0)}%），说明原来的模型<b>确实过拟合了</b>。`
    + `2）但「每月自己选」（${fmt(pen.nested.rmse, 2)}）几乎和固定 30 一样（差异不显著，p = ${fmt(E.nested_vs_30.p, 2)}）：它在 ${Math.round(big / tot * 100)}% 的月份选了 100 以上，其余月份（多在训练数据少的早期）选得很小。按规则它「不比 30 差」所以被采用，但<b>事后最优的 λ 是看过测试结果才知道的，不能当作样本外成绩</b>。`
    + `3）所有 λ 在 2016 年以后都还是不如「和去年一样」（${fmt(E.naive_post2016, 2)}）。最新一次预测选出的 λ = ${R.forecast.lambda}。`;
  const V = E.valuation, names = Object.keys(V), per = Object.keys(V[names[0]].periods), vn = E.valuation_naive;
  $('exp_val').innerHTML = `<tr><th>输入</th><th>总误差</th>${per.map(p => `<th>${p}</th>`).join('')}<th>转折月误差</th><th>方向对</th><th>对现有模型 p</th><th>是否采用</th></tr>`
    + names.map(k => { const v = V[k], base = k === names[0], vd = E.verdict[k];
      return `<tr${base ? ' style="font-weight:600"' : ''}><td>${k}</td><td>${fmt(v.rmse, 2)}</td>${per.map(p => { const x = v.periods[p].rmse, b0 = V[names[0]].periods[p].rmse;
        return `<td style="color:${!base && x < b0 ? 'var(--pos)' : !base ? 'var(--neg)' : 'inherit'}">${fmt(x, 2)}</td>`; }).join('')}<td>${fmt(v.turn.rmse, 2)}</td><td>${Math.round(v.hit * 100)}%</td><td>${v.dm_vs_base ? fmt(v.dm_vs_base.p, 2) : '—'}</td><td>${base ? '基准' : vd.adopt ? '<b style="color:var(--pos)">采用</b>' : '不采用（' + vd.period_wins + '/3 时期更好）'}</td></tr>`; }).join('')
    + `<tr style="color:var(--muted)"><td>「和去年一样」</td><td>${fmt(vn.rmse, 2)}</td>${per.map(p => `<td>${fmt(vn.periods[p], 2)}</td>`).join('')}<td>${fmt(vn.turn, 2)}</td><td>—</td><td>—</td><td>—</td></tr>`;
  const v1 = V['+ 两个估值项'], b0 = V[names[0]];
  $('exp_val_n').innerHTML = `共 ${E.valuation_n} 个月（${E.valuation_from} 至 ${E.valuation_to}，要等到有 5 年训练数据才开始，所以比上面的主回测短）。绿 = 比现有模型更准。`
    + `<b>结论：加了估值项，总误差反而变大（${fmt(v1.rmse, 2)} 对 ${fmt(b0.rmse, 2)}），转折月也更差（${fmt(v1.turn.rmse, 2)} 对 ${fmt(b0.turn.rmse, 2)}），所以不加入预测。</b>`
    + `唯一的亮点是 2020 年以后：估值项把误差从 ${fmt(b0.periods['2020–'].rmse, 2)} 降到 ${fmt(v1.periods['2020–'].rmse, 2)}，但 2008–2015 年反而更差，而且所有差异在统计上都不显著（p ≥ 0.27）。一次利率冲击的好成绩，不足以说明它是稳定的规律。`;
  const vnow = R.valuation_now, sgn = x => x > 0 ? '偏贵' : '偏便宜';
  $('exp_now').innerHTML = `<div class="tile"><div class="l">房价 ÷ 收入 · ${vnow.month}</div><div class="v">${sg(vnow.pe_gap, 1)}%</div><div class="d">相对自 2000 年以来平均：${sgn(vnow.pe_gap)}。五年前是 ${sg(vnow.pe_gap_5y_ago, 0)}%。</div></div>
    <div class="tile"><div class="l">月供 ÷ 收入 · ${vnow.month}</div><div class="v">${sg(vnow.pti_gap, 1)}%</div><div class="d">相对自 2000 年以来平均：${sgn(vnow.pti_gap)}。利率比过去二十年的平均高，月供压力比房价本身显示的更大。</div></div>`;
}

function draw(){ tiles(); rics(); forecast(); backtest(); experiments(); simple(); timing(); five(); sources(); }
fetch('radar.json').then(r => r.json()).then(d => { R = d; draw();
  for (const id of ['price', 'dep', 'term']) $(id).addEventListener('input', timing);
  for (const id of ['eg', 'r5', 'pt', 'rx']) $(id).addEventListener('input', five);
  // redraw on a real width change only: laying the page out can add or remove the scrollbar, and a
  // resize handler that redraws unconditionally then triggers itself
  let lastW = innerWidth, tm = 0;
  addEventListener('resize', () => { clearTimeout(tm); tm = setTimeout(() => { if (Math.abs(innerWidth - lastW) > 2){ lastW = innerWidth; draw(); } }, 150); }); });
</script></body></html>
'''

if __name__ == "__main__":
    (ROOT / "web" / "data" / "radar.html").write_text(PAGE)
    print("radar.html written")
