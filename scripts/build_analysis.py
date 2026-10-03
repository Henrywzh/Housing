"""The 人口分析 page: how a small area's make-up relates to income, jobs, crime and prices.

Writes web/data/analysis.json (one column per variable, one row per LSOA) and
web/data/analysis.html (a self-contained page that draws it). The maths -- weighted
correlation, and the same correlation after taking out density, tenure, age and
education -- is done in the browser, so the page can offer every pairing rather than
the handful a table would hold.

Income is ONS's model-based estimate for the MSOA the LSOA sits in (financial year
ending 2023, equivalised, before housing costs); the other outcomes are from the
Census, the Police and Land Registry as elsewhere on the map.
"""
import json, pathlib, sys
import numpy as np
import pandas as pd
sys.path.insert(0, str(pathlib.Path(__file__).parent))
from analyze_ethnicity import load  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parents[1]
RAW, WEB = ROOT / "data" / "raw", ROOT / "web" / "data"

COLS = ["pop", "wb", "ir", "wo", "wh", "ch", "ax", "in", "pk", "bd", "oa", "as", "af", "cb", "ob", "bk", "mx", "ar", "ot", "nb",
        "inc", "pro", "dg", "p", "br", "vi", "ld", "pr", "ow", "ag", "vs"]


def main():
    d = load()
    cob = pd.read_csv(RAW / "lsoa_cob.csv").pivot_table(index="GEOGRAPHY_CODE", columns="C2021_COB_12", values="OBS_VALUE")
    d["nb"] = 100 * (1 - cob[1] / cob[0])
    d = d.rename(columns={"net_income": "inc", "pro_pct": "pro", "degree_pct": "dg", "flat_price": "p",
                          "burglary_resid_per_1000_hh": "br", "violence_per_1000": "vi", "log_density": "ld",
                          "private_rent_pct": "pr", "owned_pct": "ow", "age_25_39_pct": "ag", "visitor_share": "vs"})
    d = d[d["pop"] >= 500]
    cols = {}
    for c in COLS:
        v = d[c].astype(float)
        nd = 0 if c in ("pop", "inc", "p") else 1
        cols[c] = [None if np.isnan(x) else round(float(x), nd) if nd else int(round(float(x))) for x in v]
    # Hong Kong and China born, by borough
    b = pd.read_csv(RAW / "lad_cob.csv").pivot_table(index="GEOGRAPHY_NAME", columns="C2021_COB_58", values="OBS_VALUE")
    bor = [{"n": n, "t": int(r[0]), "hk": int(r[35]), "cn": int(r[34]), "in": int(r[38]), "pk": int(r[39]), "bd": int(r[40]),
            "sg": int(r[45]), "my": int(r[44])} for n, r in b.iterrows()]
    (WEB / "analysis.json").write_text(json.dumps({"n": len(d), "cols": cols, "bor": bor}, separators=(",", ":")))
    (WEB / "analysis.html").write_text(PAGE)
    print(f"analysis.json: {len(d):,} LSOAs, {(WEB / 'analysis.json').stat().st_size/1e3:.0f} KB")


PAGE = r'''<!doctype html>
<html lang="zh"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>人口分析</title>
<style>
:root{--paper:#f2f4f6;--panel:#fff;--panel-2:#f7f9fa;--ink:#121b24;--ink-2:#3d4c58;--muted:#6a7884;--rule:#d9e0e6;--signal:#c2402a;--pos:#2c6f52;--neg:#a8382a;color-scheme:light}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){--paper:#0e141a;--panel:#161e26;--panel-2:#1b242d;--ink:#e7edf2;--ink-2:#b3c0cb;--muted:#8798a5;--rule:#2a353f;--signal:#e8664c;--pos:#5fb389;--neg:#e07a68;color-scheme:dark}}
*{box-sizing:border-box}
body{margin:0;background:var(--paper);color:var(--ink);font:400 14px/1.55 "Source Sans 3",-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}
.wrap{max-width:1100px;margin:0 auto;padding:16px}
h2{font:600 15px/1.3 Archivo,"Source Sans 3",sans-serif;margin:0 0 4px}
.card{background:var(--panel);border:1px solid var(--rule);border-radius:10px;padding:14px;margin-bottom:14px}
.sub{color:var(--muted);font-size:12.5px;margin:0 0 10px}
.ctl{display:flex;flex-wrap:wrap;gap:10px 16px;align-items:center;margin-bottom:10px}
.ctl label{display:flex;align-items:center;gap:6px;font-size:12.5px;color:var(--ink-2)}
select{font:inherit;font-size:13px;padding:5px 8px;border:1px solid var(--rule);border-radius:6px;background:var(--panel-2);color:var(--ink);max-width:100%}
.grid{display:grid;grid-template-columns:minmax(0,2fr) minmax(0,1fr);gap:14px}
@media (max-width:760px){.grid{grid-template-columns:1fr}}
canvas{width:100%;height:340px;display:block;border:1px solid var(--rule);border-radius:8px;background:var(--panel-2)}
.stat{display:flex;justify-content:space-between;gap:10px;padding:6px 0;border-bottom:1px solid var(--rule);font-size:13px}
.stat b{font-family:"IBM Plex Mono",monospace;font-weight:500}
.stat span{color:var(--muted)}
.big{font:600 28px/1.1 Archivo,sans-serif;margin:2px 0}
.note{font-size:12.5px;color:var(--ink-2);margin:8px 0 0}
table{border-collapse:collapse;width:100%;font-size:12.5px}
th,td{padding:5px 7px;text-align:right;border-bottom:1px solid var(--rule);white-space:nowrap}
th:first-child,td:first-child{text-align:left}
th{font-weight:600;color:var(--muted);font-size:11.5px}
td.c{cursor:pointer;font-family:"IBM Plex Mono",monospace;font-size:12px}
td.c:hover{outline:2px solid var(--signal);outline-offset:-2px}
td.sel{outline:2px solid var(--ink);outline-offset:-2px}
.scroll{overflow-x:auto}
.warn{border-left:3px solid var(--signal);padding:2px 0 2px 10px;margin:8px 0;color:var(--ink-2);font-size:13px}
</style></head><body><div class="wrap">

<div class="card">
<h2>一个地方的人口构成，和收入、职业、犯罪、房价有什么关联？</h2>
<p class="sub">伦敦 <span id="n">—</span> 个小区（LSOA，约 1500 人一块），Census 2021。按人口加权。<b>关联不是原因</b>：族裔构成背后是移民时间、当年的住房、年龄和教育，下面的「控制其他因素」就是把这些先扣掉再看。</p>
<div class="ctl">
 <label>人口构成 <select id="x"></select></label>
 <label>对照 <select id="y"></select></label>
 <label><input type="checkbox" id="adj" checked> 控制其他因素（密度、私租、自有、25–39 岁、学历）</label>
</div>
<div class="grid">
 <div><canvas id="cv"></canvas><p class="note" id="axnote"></p></div>
 <div>
  <div class="sub">关联系数 r（−1 到 1）</div>
  <div class="big" id="rbig">—</div>
  <div class="stat"><span>直接相关（不控制）</span><b id="rraw">—</b></div>
  <div class="stat"><span>控制其他因素后</span><b id="radj">—</b></div>
  <div class="stat"><span>该人群占比最高的 1/5 小区</span><b id="hi">—</b></div>
  <div class="stat"><span>占比最低的 1/5 小区</span><b id="lo">—</b></div>
  <div class="stat"><span>用到的小区数</span><b id="cnt">—</b></div>
  <p class="note" id="read"></p>
 </div>
</div>
</div>

<div class="card">
<h2>全部组合</h2>
<p class="sub">每格是相关系数 r（绿 = 正相关，红 = 负相关，越深越强）。点任意一格会在上面画出对应的散点图。<span id="hmode"></span></p>
<div class="scroll"><table id="heat"></table></div>
</div>

<div class="card">
<h2>香港出生的居民 · 按区</h2>
<p class="sub">Census 2021，出生地为香港（详细出生地只公布到区一级，所以这里不能细到小区）。同时列出中国大陆、新加坡、马来西亚出生，作对照。</p>
<div class="scroll"><table id="bor"></table></div>
</div>

<div class="card">
<h2>怎么读这些数字</h2>
<div class="warn"><b>区域不是个人。</b>一个地方平均收入低，不代表住在那里的某个人收入低。</div>
<div class="warn"><b>收入是模型估算。</b>ONS 的小区收入用了 Census 变量建模，所以和人口构成的关联有一部分是模型自带的。</div>
<div class="warn"><b>犯罪的关联大多被混杂因素吞掉。</b>点「暴力」再勾选或取消「控制其他因素」，可以看到原始关联在控制密度、私租、年龄、学历和访客型犯罪占比之后几乎消失。</div>
<div class="warn"><b>这页不进任何评分。</b>地图上的综合分里没有族裔项。</div>
</div>
</div>
<script>
const NAMES = {wb:'英国白人', ir:'爱尔兰裔白人', wo:'其他白人', wh:'白人（合计）', ch:'华裔', ax:'亚裔（不含华裔）', in:'印度裔', pk:'巴基斯坦裔', bd:'孟加拉裔', oa:'其他亚裔', as:'亚裔（合计）', af:'非洲裔', cb:'加勒比裔', ob:'其他黑人', bk:'黑人（合计）', mx:'混血', ar:'阿拉伯裔', ot:'其他族裔', nb:'海外出生'};
const GROUPS = Object.keys(NAMES);
const OUT = {inc:['家庭净收入（£/年）', v => '£' + Math.round(v / 1000) + 'k'], pro:['管理/专业职业 %', v => v.toFixed(0) + '%'], dg:['本科及以上 %', v => v.toFixed(0) + '%'],
  p:['公寓中位价', v => '£' + Math.round(v / 1000) + 'k'], br:['住宅入室 / 千户', v => v.toFixed(0)], vi:['暴力 / 千人', v => v.toFixed(0)]};
let D = null, pop = null;
const $ = id => document.getElementById(id);
const col = k => D.cols[k];
function ctrlFor(y){ const c = ['ld','pr','ow','ag','dg']; if (y === 'dg') c.splice(c.indexOf('dg'), 1); if (y === 'vi') c.push('vs'); return c; }
function wcorr(x, y, w){
  let sw = 0, mx = 0, my = 0; const n = x.length;
  for (let i = 0; i < n; i++){ sw += w[i]; mx += w[i]*x[i]; my += w[i]*y[i]; }
  mx /= sw; my /= sw; let cxy = 0, cxx = 0, cyy = 0;
  for (let i = 0; i < n; i++){ const a = x[i]-mx, b = y[i]-my; cxy += w[i]*a*b; cxx += w[i]*a*a; cyy += w[i]*b*b; }
  return cxy / Math.sqrt(cxx*cyy);
}
// weighted least squares: residuals of y on the columns of X (with an intercept)
function resid(y, X, w){
  const n = y.length, p = X.length + 1, A = Array.from({length:p}, () => new Float64Array(p + 1));
  for (let i = 0; i < n; i++){
    const r = [1, ...X.map(c => c[i])];
    for (let a = 0; a < p; a++){ for (let b = 0; b < p; b++) A[a][b] += w[i]*r[a]*r[b]; A[a][p] += w[i]*r[a]*y[i]; }
  }
  for (let a = 0; a < p; a++){            // Gauss-Jordan
    let m = a; for (let r = a+1; r < p; r++) if (Math.abs(A[r][a]) > Math.abs(A[m][a])) m = r;
    [A[a], A[m]] = [A[m], A[a]];
    const d = A[a][a]; for (let b = a; b <= p; b++) A[a][b] /= d;
    for (let r = 0; r < p; r++) if (r !== a){ const f = A[r][a]; for (let b = a; b <= p; b++) A[r][b] -= f*A[a][b]; }
  }
  const beta = A.map(r => r[p]);
  return y.map((v, i) => v - beta[0] - X.reduce((s, c, j) => s + beta[j+1]*c[i], 0));
}
// rows where every needed column exists; returns the columns restricted to them
function pick(keys){
  const idx = []; for (let i = 0; i < D.n; i++) if (keys.every(k => col(k)[i] != null)) idx.push(i);
  return {idx, get: k => idx.map(i => col(k)[i])};
}
const cache = {};
function pair(xk, yk){
  const key = xk + '|' + yk; if (cache[key]) return cache[key];
  const cs = ctrlFor(yk), P = pick([xk, yk, 'pop', ...cs]);
  const x = P.get(xk), y = P.get(yk), w = P.get('pop');
  const raw = wcorr(x, y, w);
  const X = cs.map(c => P.get(c));
  const rx = resid(x, X, w), ry = resid(y, X, w);
  const adj = wcorr(rx, ry, w);
  return cache[key] = {raw, adj, P, x, y, w, rx, ry, n: x.length};
}
function median(a){ const s = a.slice().sort((p, q) => p - q); return s[s.length >> 1]; }
function color(r){ const a = Math.min(1, Math.abs(r) / .6); return r >= 0 ? `rgba(44,111,82,${.08 + .6*a})` : `rgba(168,56,42,${.08 + .6*a})`; }
function build(){
  $('x').innerHTML = GROUPS.map(g => `<option value="${g}">${NAMES[g]}</option>`).join('');
  $('y').innerHTML = Object.entries(OUT).map(([k, v]) => `<option value="${k}">${v[0]}</option>`).join('');
  $('x').value = 'bk'; $('y').value = 'inc';
  $('n').textContent = D.n.toLocaleString();
  const bors = D.bor.slice().sort((a, b) => b.hk - a.hk);
  $('bor').innerHTML = `<tr><th>区</th><th>香港出生</th><th>占居民</th><th>中国大陆出生</th><th>新加坡</th><th>马来西亚</th></tr>` +
    bors.map(b => `<tr><td>${b.n}</td><td>${b.hk.toLocaleString()}</td><td>${(100*b.hk/b.t).toFixed(2)}%</td><td>${b.cn.toLocaleString()}</td><td>${b.sg.toLocaleString()}</td><td>${b.my.toLocaleString()}</td></tr>`).join('');
  for (const id of ['x','y','adj']) $(id).addEventListener('input', draw);
  addEventListener('resize', draw);
}
function heat(){
  const ys = Object.keys(OUT), adj = $('adj').checked, xk = $('x').value, yk = $('y').value;
  $('hmode').textContent = adj ? ' 当前显示：控制其他因素之后。' : ' 当前显示：直接相关。';
  $('heat').innerHTML = `<tr><th>人口构成</th>${ys.map(y => `<th>${OUT[y][0]}</th>`).join('')}</tr>` +
    GROUPS.map(g => `<tr><td>${NAMES[g]}</td>${ys.map(y => { const p = pair(g, y), r = adj ? p.adj : p.raw;
      return `<td class="c${g === xk && y === yk ? ' sel' : ''}" style="background:${color(r)}" data-x="${g}" data-y="${y}">${r.toFixed(2)}</td>`; }).join('')}</tr>`).join('');
  for (const td of $('heat').querySelectorAll('td.c')) td.onclick = () => { $('x').value = td.dataset.x; $('y').value = td.dataset.y; draw(); };
}
// residual ticks: signed, and in thousands when the scale is large (income, price)
const sgn = (v, span) => (v > 0 ? '+' : v < 0 ? '−' : '') + (span > 2000 ? Math.abs(v / 1000).toFixed(0) + 'k' : Math.abs(v).toFixed(span > 20 ? 0 : 1));
function scatter(p, adj){
  const cv = $('cv'), dpr = devicePixelRatio || 1, W = cv.clientWidth, H = cv.clientHeight;
  cv.width = W*dpr; cv.height = H*dpr; const g = cv.getContext('2d'); g.scale(dpr, dpr);
  const xs = adj ? p.rx : p.x, ys = adj ? p.ry : p.y, m = {l:58, r:22, t:10, b:34};
  const lo = a => { const s = a.slice().sort((u, v) => u - v); return [s[Math.floor(.005*s.length)], s[Math.ceil(.995*s.length) - 1]]; };
  const [x0, x1] = lo(xs), [y0, y1] = lo(ys);
  const sx = v => m.l + (v - x0) / (x1 - x0) * (W - m.l - m.r), sy = v => H - m.b - (v - y0) / (y1 - y0) * (H - m.t - m.b);
  const css = getComputedStyle(document.documentElement), ink = css.getPropertyValue('--muted').trim(), rule = css.getPropertyValue('--rule').trim(), sig = css.getPropertyValue('--signal').trim();
  g.font = '11px "IBM Plex Mono",monospace'; g.fillStyle = ink; g.strokeStyle = rule; g.lineWidth = 1;
  for (let i = 0; i <= 4; i++){
    const vy = y0 + (y1 - y0) * i / 4, vx = x0 + (x1 - x0) * i / 4;
    g.beginPath(); g.moveTo(m.l, sy(vy)); g.lineTo(W - m.r, sy(vy)); g.stroke();
    g.textAlign = 'right'; g.fillText(adj ? sgn(vy, y1 - y0) : OUT[$('y').value][1](vy), m.l - 5, sy(vy) + 4);
    g.textAlign = 'center'; g.fillText(adj ? sgn(vx, x1 - x0) + '%' : vx.toFixed(0) + '%', sx(vx), H - m.b + 15);
  }
  g.fillStyle = 'rgba(70,110,150,.28)';
  const wmax = Math.max(...p.w);
  for (let i = 0; i < xs.length; i++){
    if (xs[i] < x0 || xs[i] > x1 || ys[i] < y0 || ys[i] > y1) continue;
    g.beginPath(); g.arc(sx(xs[i]), sy(ys[i]), 1.2 + 2.2*Math.sqrt(p.w[i]/wmax), 0, 6.283); g.fill();
  }
  // weighted least-squares line
  let sw = 0, mx = 0, my = 0; for (let i = 0; i < xs.length; i++){ sw += p.w[i]; mx += p.w[i]*xs[i]; my += p.w[i]*ys[i]; } mx /= sw; my /= sw;
  let cxy = 0, cxx = 0; for (let i = 0; i < xs.length; i++){ cxy += p.w[i]*(xs[i]-mx)*(ys[i]-my); cxx += p.w[i]*(xs[i]-mx)**2; }
  const b = cxy / cxx, a = my - b*mx;
  g.strokeStyle = sig; g.lineWidth = 2; g.beginPath(); g.moveTo(sx(x0), sy(a + b*x0)); g.lineTo(sx(x1), sy(a + b*x1)); g.stroke();
}
function draw(){
  const xk = $('x').value, yk = $('y').value, adj = $('adj').checked, p = pair(xk, yk);
  const r = adj ? p.adj : p.raw;
  $('rbig').textContent = r.toFixed(2);
  $('rraw').textContent = p.raw.toFixed(2); $('radj').textContent = p.adj.toFixed(2);
  const sorted = p.x.map((v, i) => [v, p.y[i]]).sort((a, b) => a[0] - b[0]), k = Math.floor(sorted.length / 5);
  const hi = median(sorted.slice(-k).map(a => a[1])), lo = median(sorted.slice(0, k).map(a => a[1])), f = OUT[yk][1];
  $('hi').textContent = f(hi); $('lo').textContent = f(lo); $('cnt').textContent = p.n.toLocaleString();
  const mag = Math.abs(r) < .1 ? '几乎没有关联' : Math.abs(r) < .3 ? '关联较弱' : Math.abs(r) < .5 ? '有中等关联' : '关联较强';
  $('read').textContent = `${NAMES[xk]}占比越高的小区，${OUT[yk][0]}${r > 0 ? '往往越高' : '往往越低'}（${mag}）。` +
    (adj ? '这是把密度、私租、自有、25–39 岁、学历的影响先扣掉之后的结果。' : '这是直接相关，没有扣掉其他因素。') +
    (Math.abs(p.raw) - Math.abs(p.adj) > .12 ? ' 控制之后明显变弱，说明原来的关联大多来自这些因素。' : '');
  $('axnote').textContent = adj ? `横轴、纵轴都是扣掉控制变量后的残差（0 = 该因素下的预期值）。每个点是一个小区，点大 = 人口多，红线 = 加权拟合。`
    : `横轴 = ${NAMES[xk]}占小区居民的比例，纵轴 = ${OUT[yk][0]}。每个点是一个小区，点大 = 人口多，红线 = 加权拟合。`;
  scatter(p, adj); heat();
}
fetch('analysis.json').then(r => r.json()).then(d => { D = d; build(); draw(); });
</script></body></html>
'''

if __name__ == "__main__":
    main()
