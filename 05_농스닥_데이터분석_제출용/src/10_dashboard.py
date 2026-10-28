"""
10단계 — Q1~Q4 를 한 화면에  (웹페이지 생성)

실행:
    python 10_dashboard.py

입력  data/processed/dashboard_data_week.json    (09_analyze.py 결과)
      data/processed/dashboard_data_month.json
      data/processed/dashboard_data_day.json
      셋 중 있는 것만 읽는다. 하나도 없으면 예전 이름(dashboard_data.json)을 찾는다.

출력  reports/dashboard.html


자립형입니다
    CSS·JS·데이터를 전부 파일 안에 넣습니다.
    서버도 인터넷도 필요 없습니다. 더블클릭하면 열립니다.
    USB 로 옮기거나 메일로 보내도 그대로 열립니다.


화면 구성
    맨 위에서 일별 · 주별 · 월별을 골라 같은 화면을 갈아 끼운다.
    세 주기를 나란히 보면 결론이 주기에 흔들리는지 아닌지 바로 보인다.

    Q1  계절 패턴          — 평년 밴드차트 · 계절 달력 · 진폭 순위
    Q2  기온·강수량        — 뚜렷한 상품 목록 · 시차 곡선 · 폭염/호우
                             (계절을 걷어내지 않은 값으로 비교한다)
    Q3  물가와 실질가격    — 명목 vs 실질 막대 · 물가 설명 비율
    Q4  미래 가격 예측     — 분포 위치 게이지

    주기 단추와 Q1~Q4 차례는 스크롤 중에도 맨 위에 붙는다.
    평년 밴드 · 진폭 순위 · Q3 · Q4 표에는 검색창이,
    계절 달력에는 몇 개까지 볼지 고르는 칸이 있다.
    상품이 수백 개여도 원하는 것만 골라 볼 수 있다.


그림은 전부 그 자리에서 SVG 로 그립니다.
    이미지 파일을 붙이지 않아 용량이 작고, 화면 크기에 따라 늘어납니다.
"""

import html
import json
from pathlib import Path


CURRENT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = CURRENT_DIR.parent

DATA_DIR = PROJECT_ROOT / "data" / "processed"
OUT_DIR = PROJECT_ROOT / "reports"

OUT_DIR.mkdir(parents=True, exist_ok=True)

FREQS = [("day", "일별"), ("week", "주별"), ("month", "월별")]

LEGACY_FILE = DATA_DIR / "dashboard_data.json"
OUT_FILE = OUT_DIR / "dashboard.html"

TITLE = "농스닥"
SUBTITLE = "계절 · 날씨 · 물가 · 현재 수준"


# 이 줄을 보고 "지금 도는 게 새 파일이 맞나" 를 바로 확인할 수 있습니다.
# 파일을 옮겨 놓고 옛 파일을 돌리는 실수가 제일 잦습니다.
VERSION = "2026-08-19c  (Q2 계절 포함 · 뚜렷한 상품만 판)"

print("=" * 60)
print(f"대시보드 생성   {VERSION}")
print("=" * 60)
print("  이 판에 있는 것: 일별-주별-월별 차례 · 주기단추 상단고정 · 검색창")
print("                   계절달력 개수조절 · 순위 번호 · 등급/단위 열")
print("                   Q2 계절 포함 비교 · 뚜렷한 상품만 나열 (재배 특성 메모 없음)")
print("  위 줄이 안 보이면 예전 10_dashboard.py 가 도는 중입니다.")

bundle = {}

for freq, label in FREQS:

    path = DATA_DIR / f"dashboard_data_{freq}.json"

    if not path.exists():
        print(f"{label:<4} 없음 — python 09_analyze.py {freq} 로 만들 수 있습니다")
        continue

    bundle[freq] = json.loads(path.read_text(encoding="utf-8"))

if not bundle and LEGACY_FILE.exists():
    print("예전 이름(dashboard_data.json)을 읽습니다.")
    bundle["week"] = json.loads(LEGACY_FILE.read_text(encoding="utf-8"))

if not bundle:
    raise FileNotFoundError(
        f"분석 결과가 없습니다. 먼저 09_analyze.py 를 실행하세요.\n"
        f"  찾은 곳: {DATA_DIR}/dashboard_data_<주기>.json")

for freq, data in bundle.items():

    meta = data["meta"]
    label = meta.get("freqLabel", freq)

    print(f"\n{label}  {meta['period']}년 · 상품 {meta['products']:,}개 "
          f"· 품목 {meta['items']:,}개 · 관측 {meta['rows']:,}건")

    if meta.get("dropped"):
        print(f"  화면에는 {meta['shown']:,}개만 (나머지 {meta['dropped']:,}개는 csv 에)")

    # Q1 은 available 플래그를 따로 두지 않습니다. 상품이 하나라도 잡혔으면 있는 것입니다.
    # 목록에서 빼 두면 "Q1 이 안 나왔나?" 로 오해하기 쉬워 함께 찍습니다.
    ok = {"Q1": bool(data.get("q1", {}).get("products"))}
    for key, name in (("q2", "Q2"), ("q3", "Q3"), ("q4", "Q4")):
        ok[name] = bool(data.get(key, {}).get("available"))

    have = [n for n, v in ok.items() if v]
    lack = [n for n, v in ok.items() if not v]

    print(f"  있음 {', '.join(have) if have else '-'}"
          + (f" / 없음 {', '.join(lack)}" if lack else ""))


# ---------------------------------------------------------
# HTML — f-string 을 쓰지 않습니다.
#   CSS·JS 에 중괄호가 많아 f-string 으로 쓰면 이스케이프가 얽힙니다.
#   자리표시자를 replace 로 바꾸는 편이 안전합니다.
# ---------------------------------------------------------

TEMPLATE = r"""<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>__TITLE__</title>
<style>
  :root {
    --bg:#f6f7f9; --card:#fff; --ink:#16191d; --muted:#6b7280; --line:#e5e7eb;
    --hot:#c0392b; --cold:#2563eb; --accent:#0f766e; --amber:#d97706;
  }
  * { box-sizing:border-box; }
  body {
    margin:0; background:var(--bg); color:var(--ink); line-height:1.6;
    font-family:-apple-system,BlinkMacSystemFont,"Malgun Gothic",
                "Apple SD Gothic Neo","Noto Sans KR",sans-serif;
  }
  .wrap { max-width:1120px; margin:0 auto; padding:36px 20px 90px; }

  header h1 { font-size:29px; margin:0 0 6px; letter-spacing:-.6px; }
  header p { margin:0; color:var(--muted); font-size:14.5px; }

  .topbar {
    position:sticky; top:0; z-index:30; margin:18px -20px 0; padding:9px 20px 0;
    background:rgba(246,247,249,.94); backdrop-filter:blur(8px);
    border-bottom:1px solid var(--line);
  }
  .freqbar { display:flex; gap:8px; flex-wrap:wrap; align-items:center; }
  .freqbar button {
    padding:9px 18px; border:1px solid var(--line); border-radius:9px;
    background:#fff; cursor:pointer; font-size:14px; font-family:inherit;
    font-weight:600; color:var(--muted);
  }
  .freqbar button:hover { color:var(--ink); }
  .freqbar button.on { background:var(--accent); color:#fff; border-color:var(--accent); }
  .freqbar .hint { font-size:12.5px; color:var(--muted); margin-left:4px; }

  nav { display:flex; gap:8px; flex-wrap:wrap; padding:9px 0 7px; }
  nav a {
    text-decoration:none; color:var(--muted); font-size:13.5px; font-weight:500;
    padding:7px 14px; border-radius:20px; border:1px solid transparent;
  }
  nav a:hover { color:var(--ink); border-color:var(--line); background:#fff; }
  nav a.on { background:var(--ink); color:#fff; }

  section { background:var(--card); border:1px solid var(--line);
            border-radius:14px; padding:26px 28px; margin-top:22px;
            scroll-margin-top:118px; }
  section > h2 { font-size:20px; margin:0 0 3px; }
  section > h2 .q { color:var(--accent); font-weight:700; margin-right:8px; }
  section > .lead { color:var(--muted); margin:0 0 20px; font-size:14.5px; }

  h3 { font-size:15.5px; margin:26px 0 10px; }
  h3:first-of-type { margin-top:6px; }

  .grid { display:grid; gap:14px;
          grid-template-columns:repeat(auto-fit,minmax(180px,1fr)); }
  .stat { border:1px solid var(--line); border-radius:10px;
          padding:15px 17px; background:#fcfcfd; }
  .stat .label { font-size:12.5px; color:var(--muted); margin-bottom:5px; }
  .stat .value { font-size:25px; font-weight:660; letter-spacing:-.5px; }
  .stat .note { font-size:12.5px; color:var(--muted); margin-top:3px; }
  .stat.hot .value { color:var(--hot); }
  .stat.cold .value { color:var(--cold); }
  .stat.calm .value { color:var(--accent); }

  .answer {
    font-size:17px; font-weight:600; line-height:1.55; padding:15px 18px;
    border-radius:10px; margin:0 0 20px; border-left:4px solid var(--accent);
    background:#f0fdfa;
  }
  .answer.warn { border-color:var(--amber); background:#fffbeb; }
  .answer.none { border-color:var(--muted); background:#f3f4f6; }
  .answer small { display:block; font-weight:400; font-size:13.5px;
                  color:var(--muted); margin-top:6px; }

  select, input[type=search] {
    padding:8px 12px; border:1px solid var(--line); border-radius:8px;
    font-size:14px; font-family:inherit; background:#fff; max-width:100%;
  }
  .row { display:flex; gap:10px; align-items:center; flex-wrap:wrap; margin-bottom:12px; }

  /* border-collapse:collapse 를 쓰면 테두리가 셀이 아니라 표에 그려진다.
     그래서 position:sticky 로 붙여 둔 머리줄이 자기 테두리를 데려가지 못하고,
     스크롤할 때 그 틈으로 뒷줄이 비쳐 머리줄이 들뜬 것처럼 보인다.
     separate + spacing 0 으로 두면 테두리가 셀에 붙어 머리줄과 함께 고정된다.
     아래 테두리만 쓰고 있어서 겉모습은 그대로다. */
  table { width:100%; border-collapse:separate; border-spacing:0; font-size:13.5px; }
  th,td { padding:8px 10px; border-bottom:1px solid var(--line); text-align:left; }
  th { font-size:12px; color:var(--muted); font-weight:600; white-space:nowrap;
       cursor:pointer; position:sticky; top:0; z-index:2;
       background:var(--card); background-clip:padding-box; }
  th.num,td.num { text-align:right; font-variant-numeric:tabular-nums; }
  tbody tr { cursor:pointer; }
  tbody tr:hover { background:#f9fafb; }
  tbody tr.on { background:#ecfeff; }
  .scroll { max-height:420px; overflow:auto; border:1px solid var(--line);
            border-radius:8px; }

  td.rank { color:var(--muted); width:44px; }
  td.rank.top { color:var(--accent); font-weight:700; }

  .track { position:relative; width:92px; height:13px; background:#f3f4f6;
           border-radius:3px; display:inline-block; vertical-align:middle; }
  .track::before { content:''; position:absolute; left:50%; top:0; bottom:0;
                   width:1px; background:#d1d5db; }
  .track i { position:absolute; top:3px; height:7px; border-radius:2px; }
  .track i.pos { left:50%; background:var(--hot); }
  .track i.neg { right:50%; background:var(--cold); }
  .track u { position:absolute; top:0; bottom:0; width:1px;
             background:var(--amber); opacity:.5; }

  .gauge { position:relative; width:120px; height:14px; border-radius:7px;
           display:inline-block; vertical-align:middle;
           background:linear-gradient(90deg,#2563eb,#e5e7eb 50%,#c0392b); }
  .gauge b { position:absolute; top:-3px; width:3px; height:20px;
             background:#16191d; border-radius:2px; }

  .hm { border-collapse:separate; border-spacing:2px; font-size:12px; }
  .hm td.c { width:44px; height:26px; text-align:center; border-radius:4px;
             color:#fff; font-weight:600; font-size:11.5px; border:none; }
  .hm td.name { white-space:nowrap; padding-right:10px; font-size:13px;
                border:none; }
  .hm th { position:static; background:none; cursor:default;
           text-align:center; font-size:11.5px; border:none; padding:2px; }

  .legend { display:flex; gap:14px; flex-wrap:wrap; font-size:12.5px;
            color:var(--muted); margin-top:10px; align-items:center; }
  .legend span.key { display:inline-block; width:11px; height:11px;
                     border-radius:3px; margin-right:5px; vertical-align:-1px; }

  .detail { margin-top:14px; padding:18px; border:1px solid var(--line);
            border-radius:10px; background:#fcfcfd; }
  .detail h4 { margin:0 0 3px; font-size:15.5px; }
  .detail .meta { color:var(--muted); font-size:13px; margin-bottom:12px; }

  .muted { color:var(--muted); }
  .small { font-size:13px; }
  .callout { border-left:3px solid var(--amber); background:#fffbeb;
             padding:11px 15px; border-radius:6px; font-size:13.5px; margin-top:14px; }
  .missing { border:1px dashed var(--line); border-radius:10px; padding:22px;
             text-align:center; color:var(--muted); font-size:14px; }

  ul.notes { margin:0; padding-left:19px; font-size:14px; }
  ul.notes li { margin-bottom:7px; }

  footer { margin-top:26px; text-align:center; color:var(--muted); font-size:12.5px; }

  svg text { font-family:inherit; }
</style>
</head>
<body>
<div class="wrap">

<header>
  <h1>__TITLE__</h1>
  <p>__SUBTITLE__ &nbsp;·&nbsp; <span id="metaLine"></span></p>
  <p class="small muted" style="margin:5px 0 0">
</header>

<div class="topbar">
  <div class="freqbar" id="freqBar"></div>
  <nav>
    <a href="#q1" class="on">Q1 계절 패턴</a>
    <a href="#q2">Q2 기온·강수</a>
    <a href="#q3">Q3 물가</a>
    <a href="#q4">Q4 가격 예측</a>
  </nav>
</div>

<!-- ================= Q1 ================= -->
<section id="q1">
  <h2><span class="q">Q1</span>품목별 가격에 계절 패턴이 있는가</h2>

  <div id="q1Answer"></div>
  <div class="grid" id="q1Stats"></div>

  <h3>평년 밴드</h3>
  <div class="row">
    <input type="search" id="q1BandQ" placeholder="품목·품종 검색">
    <select id="q1Pick"></select>
    <span class="muted small" id="q1BandHit"></span>
  </div>
  <p class="muted small" style="margin:-4px 0 12px">
    회색 띠가 평년 범위(10~90%), 굵은 선이 평년값</p>
  <div id="q1Band"></div>

  <h3>계절 달력</h3>
  <div class="row">
    <select id="q1CalN">
      <option value="10" selected>10개만</option>
      <option value="20">20개만</option>
      <option value="30">30개만</option>
      <option value="40">40개만</option>
      <option value="50">50개만</option>
      <option value="0">전체</option>
    </select>
    <span class="muted small" id="q1CalHit"></span>
  </div>
  <div id="q1Cal"></div>
  <div class="legend">
    <span><span class="key" style="background:#2563eb"></span>평년보다 쌈</span>
    <span><span class="key" style="background:#e5e7eb"></span>보통</span>
    <span><span class="key" style="background:#c0392b"></span>평년보다 비쌈</span>
  </div>


  <h3>계절을 크게 타는 상품 순위</h3>
  <div class="row">
    <input type="search" id="q1Q" placeholder="품목·품종 검색">
    <span class="muted small" id="q1TblHit"></span>
  </div>
  <div class="scroll">
    <table id="q1Tbl">
      <thead><tr>
        <th class="num">순위</th>
        <th data-k="item">품목</th><th data-k="variety">품종</th>
        <th>등급</th><th>단위</th>
        <th class="num" data-k="amplitude">계절 진폭</th>
        <th class="num" data-k="cheapMonth">가장 싼 달</th>
        <th class="num" data-k="dearMonth">가장 비싼 달</th>
        <th class="num" data-k="savingPct">싼 시기에 사면</th>
      </tr></thead>
      <tbody></tbody>
    </table>
  </div>
</section>

<!-- ================= Q2 ================= -->
<section id="q2">
  <h2><span class="q">Q2</span>기온과 강수량은 가격 변동과 어떤 관계인가</h2>

  <div id="q2Body"></div>
</section>

<!-- ================= Q3 ================= -->
<section id="q3">
  <h2><span class="q">Q3</span>10년간의 가격 상승은 물가로 얼마나 설명되는가</h2>

  <div id="q3Body"></div>
</section>

<!-- ================= Q4 ================= -->
<section id="q4">
  <h2><span class="q">Q4</span>과거 분포로 미래 가격을 예측할 수 있는가</h2>
  <div id="q4Body"></div>
</section>



<footer>09_analyze.py → 10_dashboard.py 로 생성</footer>
</div>

<script>
const ALL = __DATA_JSON__;
const ORDER = [["day","일별"],["week","주별"],["month","월별"]];
const HAVE = ORDER.filter(([k]) => ALL[k]);

// Q3·Q4 검색어는 여기에 담아 둔다.
// 두 절은 그릴 때마다 상자째 새로 만들어져 검색창도 같이 태어난다.
// 그냥 두면 주기를 바꿀 때 Q1·Q2 검색어만 남고 Q3·Q4 만 지워져 고장으로 보인다.
let q3Query='', q4Query='';

let CUR = HAVE[0][0];
let D = ALL[CUR];
let M = D.q1.monthNames;

const $ = s => document.querySelector(s);
const nf = (v,d=2) => v===null||v===undefined ? '—' : (v>=0?'+':'')+v.toFixed(d);
const pf = (v,d=1) => v===null||v===undefined ? '—' : v.toFixed(d)+'%';

/* 상품을 가르는 기준은 품목·품종·등급·단위 네 가지다 (09_analyze.py 의 PRODUCT_KEYS).
   이름표에서 등급을 빼면 등급만 다른 두 상품이 똑같은 글자로 보여
   "중복 제거를 했는데 왜 2개씩 나오지" 로 읽힌다. 실제로는 다른 상품이다.

   예전에 만든 결과에는 Q2·Q4 에 grade 가 없다.
   그때는 pkey 에서 꺼내 쓴다 — 09_analyze.py 를 다시 돌리지 않아도 되게. */
const PKEY_GRADE_AT = 2;          // pkey = 품목 | 품종 | 등급 | 단위크기 | 단위명

function gradeOf(p){
  if(p.grade) return p.grade;
  const parts = String(p.pkey||'').split(' | ');
  return parts.length===5 ? parts[PKEY_GRADE_AT] : '';
}

const isBlank = v => !v || v==='-' || v==='nan' || v==='None';

/* 검색·표시에 쓰는 전체 이름. 빈 값(등급 없음 등)은 조용히 뺀다. */
function fullName(p){
  const g = gradeOf(p);
  const tail = [isBlank(p.variety)?'':p.variety, isBlank(g)?'':g]
    .filter(Boolean).join(' · ');
  return `${p.item}${tail?' / '+tail:''}${isBlank(p.unit)?'':' ('+p.unit+')'}`;
}

const searchText = p =>
  `${p.item} ${p.variety||''} ${gradeOf(p)} ${p.unit||''}`.toLowerCase();

function median(arr){
  const a = arr.filter(v=>v!==null&&v!==undefined).sort((x,y)=>x-y);
  if(!a.length) return 0;
  const m = Math.floor(a.length/2);
  return a.length%2 ? a[m] : (a[m-1]+a[m])/2;
}

function svg(w,h,inner,extra){
  return `<svg viewBox="0 0 ${w} ${h}" style="width:100%;max-width:${w}px;height:auto"
    ${extra||''}>${inner}</svg>`;
}

function trackBar(v,max,guide){
  if(v===null||v===undefined) return '<span class="muted">—</span>';
  const half=46, w=Math.min(Math.abs(v)/max,1)*half;
  const g = guide ? (guide/max)*half : null;
  const marks = g===null ? '' :
    `<u style="left:${half+g}px"></u><u style="left:${half-g}px"></u>`;
  return `<span class="track">${marks}
    <i class="${v>0?'pos':'neg'}" style="width:${w}px"></i></span>
    <span style="margin-left:8px">${nf(v)}</span>`;
}

function heatColor(v){
  const t = Math.max(-1,Math.min(1,(v-1)/0.35));
  if(t<=0){ const k=-t;
    return `rgb(${Math.round(229-192*k)},${Math.round(231-132*k)},${Math.round(235+20*k)})`; }
  return `rgb(${Math.round(229-37*t)},${Math.round(231-174*t)},${Math.round(235-192*t)})`;
}

/* ================= 주기 전환 바 ================= */

$('#freqBar').innerHTML =
  HAVE.map(([k,label]) =>
    `<button data-f="${k}">${label}</button>`).join('');

$('#freqBar').addEventListener('click', e => {
  const b = e.target.closest('button'); if(!b) return;
  CUR = b.dataset.f; D = ALL[CUR]; M = D.q1.monthNames;
  render();
});

/* ================= 전체 그리기 ================= */

function render(){
  document.querySelectorAll('#freqBar button')
    .forEach(b => b.classList.toggle('on', b.dataset.f===CUR));

  const m = D.meta;
  $('#metaLine').textContent =
    `${m.freqLabel||''} · ${m.period}년 · 상품 ${m.products.toLocaleString()}개 · `
    + `품목 ${m.items.toLocaleString()}개 · 관측 ${m.rows.toLocaleString()}건`;



  renderQ1(); renderQ2(); renderQ3(); renderQ4();
}

/* ================= Q1 ================= */

function renderQ1(){
  const q1 = D.q1, prods = q1.products, cycle = D.meta.cycle;
  const share = q1.totalCount ? q1.strongCount/q1.totalCount*100 : 0;

  const tone = share>=50 ? '' : share>=20 ? 'warn' : 'none';
  const msg = share>=50
    ? `그렇다. 상품의 ${share.toFixed(0)}% 가 뚜렷한 계절 패턴을 보인다`
    : share>=20
      ? `품목에 따라 다르다 — ${share.toFixed(0)}% 에서만 뚜렷한 계절 패턴이 보인다`
      : `이 자료에서는 뚜렷한 계절 패턴을 가진 상품이 적다 (${share.toFixed(0)}%)`;

  const q1Line = q1.strongLine ?? 0.50;

  $('#q1Answer').innerHTML =
    `<div class="answer ${tone}">${msg}</div>`;

  $('#q1Stats').innerHTML = `
    <div class="stat calm"><div class="label">뚜렷한 계절 패턴</div>
      <div class="value">${q1.strongCount.toLocaleString()}<span
        style="font-size:15px;color:var(--muted)"> / ${q1.totalCount.toLocaleString()}</span></div>
      <div class="note">진폭 ${q1Line.toFixed(2)} 이상</div></div>
    <div class="stat"><div class="label">계절 진폭 중앙값</div>
      <div class="value">${q1.medianAmplitude.toFixed(2)}</div>
      <div class="note">연중 ${(q1.medianAmplitude*100).toFixed(0)}%p 오르내림
        (물가 포함)</div></div>
    <div class="stat cold"><div class="label">싼 시기에 사면 (중앙값)</div>
      <div class="value">${median(prods.map(p=>p.savingPct)).toFixed(0)}%</div>
      <div class="note">가장 비싼 시기 대비 절약</div></div>
    <div class="stat"><div class="label">계절 칸</div>
      <div class="value">${cycle}</div>
      <div class="note">${cycle===12?'달 단위 평년값':'주차 단위 평년값'}</div></div>`;

  const pick = $('#q1Pick'), bandQ = $('#q1BandQ');

  // option 의 value 는 걸러낸 뒤에도 prods 의 원래 위치를 그대로 담는다.
  // 걸러진 목록에서의 자리를 담으면 검색어가 바뀔 때마다 다른 상품을 가리킨다.
  function fillPick(){
    const q = (bandQ.value||'').trim().toLowerCase();
    const hits = prods.map((p,i)=>({p,i}))
      .filter(({p}) => !q || searchText(p).includes(q));

    if(!hits.length){
      pick.innerHTML = '';
      $('#q1BandHit').textContent = '검색 결과 없음';
      $('#q1Band').innerHTML =
        `<p class="muted">'${bandQ.value}' 에 맞는 상품이 없다.</p>`;
      return;
    }

    const keep = pick.value;                    // 고르고 있던 상품을 되도록 유지
    pick.innerHTML = hits.map(({p,i}) =>
      `<option value="${i}">${fullName(p)}</option>`).join('');
    pick.value = hits.some(h => String(h.i)===keep) ? keep : String(hits[0].i);

    $('#q1BandHit').textContent =
      q ? `${prods.length}개 중 ${hits.length}개` : `상품 ${prods.length}개`;
    drawBand();
  }

  pick.onchange = drawBand;
  bandQ.oninput = fillPick;
  fillPick();

  function bandChart(p){
    const W=900,H=260,L=46,R=14,T=16,B=34;
    const iw=W-L-R, ih=H-T-B;
    const xs=p.slots, lo=p.p10, mid=p.p50, hi=p.p90;
    const vals = lo.concat(hi).filter(v=>v!==null);
    let vmin=Math.min(...vals), vmax=Math.max(...vals);
    const pad=(vmax-vmin)*0.12||0.1; vmin-=pad; vmax+=pad;

    const X = slot => L + (slot-1)/(cycle-1)*iw;
    const Y = v => T + (1-(v-vmin)/(vmax-vmin))*ih;

    const top=[],bot=[];
    xs.forEach((sl,i)=>{ if(lo[i]===null||hi[i]===null) return;
      top.push(`${X(sl)},${Y(hi[i])}`); bot.unshift(`${X(sl)},${Y(lo[i])}`); });
    const area = top.length
      ? `<polygon points="${top.concat(bot).join(' ')}" fill="#94a3b8" opacity=".28"/>` : '';

    const line = xs.map((sl,i)=> mid[i]===null?null:`${X(sl)},${Y(mid[i])}`)
      .filter(Boolean).join(' ');

    const base = (vmin<1&&vmax>1)
      ? `<line x1="${L}" y1="${Y(1)}" x2="${W-R}" y2="${Y(1)}"
          stroke="#111" stroke-dasharray="4 4" opacity=".35"/>
         <text x="${L+6}" y="${Y(1)-6}" font-size="10.5" fill="#6b7280">그 해 중앙값 1.0</text>` : '';

    const slotOfMonth = mo => cycle===12 ? mo : (mo-1)*4.345+1;

    let ticks='';
    for(let mo=1; mo<=12; mo++){
      const x=X(slotOfMonth(mo));
      ticks += `<line x1="${x}" y1="${T}" x2="${x}" y2="${T+ih}" stroke="#eef0f3"/>
        <text x="${x}" y="${H-12}" font-size="10.5" fill="#9aa1ab"
        text-anchor="middle">${mo}</text>`;
    }

    const mark=(mo,color,label)=>{
      const x=X(slotOfMonth(mo));
      return `<line x1="${x}" y1="${T}" x2="${x}" y2="${T+ih}"
        stroke="${color}" stroke-width="2" opacity=".5"/>
        <text x="${x}" y="${T-4}" font-size="11" fill="${color}"
        text-anchor="middle" font-weight="600">${label}</text>`;
    };

    const yl=[vmin,(vmin+vmax)/2,vmax].map(v=>
      `<text x="${L-8}" y="${Y(v)+4}" font-size="10.5" fill="#9aa1ab"
        text-anchor="end">${v.toFixed(2)}</text>`).join('');

    return svg(W,H, ticks+area+base+
      `<polyline points="${line}" fill="none" stroke="#0f766e" stroke-width="2.4"/>`+
      mark(p.cheapMonth,'#2563eb','싼 시기')+mark(p.dearMonth,'#c0392b','비싼 시기')+yl+
      `<text x="${L+iw/2}" y="${H-1}" font-size="10.5" fill="#9aa1ab"
        text-anchor="middle">월</text>`);
  }

  function drawBand(){
    const p = prods[+pick.value||0];
    if(!p){ $('#q1Band').innerHTML='<p class="muted">그릴 상품이 없다.</p>'; return; }
    $('#q1Band').innerHTML = bandChart(p) + `
      <p class="muted small" style="margin:6px 0 0">
        ${fullName(p)} · 관측 ${p.n.toLocaleString()}${D.meta.unit} ·
        가장 싼 시기 <strong style="color:#2563eb">${M[p.cheapMonth-1]}</strong> ·
        가장 비싼 시기 <strong style="color:#c0392b">${M[p.dearMonth-1]}</strong> ·
        싼 시기에 사면 비싼 시기보다 <strong>${pf(p.savingPct)}</strong> 저렴</p>`;
  }

  /* 계절 달력 — 달력은 '연중 가장 크게 비싸지는 순' 으로 이미 정렬돼 온다.
     그래서 앞에서 N 개를 자르면 계절색이 가장 진한 것들만 남는다. */
  const calN = $('#q1CalN');

  function drawCal(){
    const all = q1.calendar;
    const lim = +calN.value || all.length;
    const shown = all.slice(0, lim);

    const rows = shown.map(c=>{
      const cells = c.months.map(v=>{
        const bg = v===null ? '#f3f4f6' : heatColor(v);
        const fg = v===null ? '#9aa1ab' : (Math.abs(v-1)>0.12 ? '#fff' : '#4b5563');
        return `<td class="c" style="background:${bg};color:${fg}">${v===null?'':v.toFixed(2)}</td>`;
      }).join('');
      const sub = [c.variety, c.grade, c.unit].filter(v=>v&&!isBlank(v)).join(' · ');
      return `<tr><td class="name">${c.item} <span class="muted"
        style="font-size:11.5px">${sub}</span></td>${cells}</tr>`;
    }).join('');

    $('#q1Cal').innerHTML = `<div style="overflow-x:auto"><table class="hm">
      <thead><tr><th></th>${M.map(m=>`<th>${m}</th>`).join('')}</tr></thead>
      <tbody>${rows}</tbody></table></div>`;

    $('#q1CalHit').textContent = shown.length >= all.length
      ? `전체 ${all.length}개`
      : `${all.length}개 중 계절색이 진한 ${shown.length}개`;
  }

  calN.onchange = drawCal;
  drawCal();

  /* 순위표 */
  const tb = $('#q1Tbl tbody'), tblQ = $('#q1Q');
  let key='amplitude', dir=-1;

  // 순위는 계절 진폭 기준으로 한 번만 매겨 고정한다.
  // 화면에 보이는 줄 번호로 매기면 검색하거나 다른 열로 정렬할 때마다
  // 같은 상품이 1위가 됐다 8위가 됐다 해서 순위라는 말이 무의미해진다.
  const rankOf = new Map();
  prods.slice()
    .sort((a,b)=>(b.amplitude??-1e9)-(a.amplitude??-1e9))
    .forEach((p,i)=>rankOf.set(p, i+1));

  function draw(){
    const q = (tblQ.value||'').trim().toLowerCase();
    const list = prods
      .filter(p => !q || searchText(p).includes(q))
      .sort((a,b)=>{
        const x=a[key], y=b[key];
        if(typeof x==='string') return dir*x.localeCompare(y,'ko');
        return dir*((x??-1e9)-(y??-1e9));
      });

    tb.innerHTML = list.length
      ? list.map(p=>{
          const r = rankOf.get(p);
          return `<tr data-i="${prods.indexOf(p)}">
            <td class="num rank${r<=3?' top':''}">${r}</td>
            <td>${p.item}</td><td>${p.variety}</td>
            <td class="muted">${gradeOf(p)||'—'}</td>
            <td class="muted">${p.unit||'—'}</td>
            <td class="num">${p.amplitude.toFixed(2)}</td>
            <td class="num" style="color:#2563eb">${M[p.cheapMonth-1]}</td>
            <td class="num" style="color:#c0392b">${M[p.dearMonth-1]}</td>
            <td class="num"><strong>${pf(p.savingPct)}</strong> 저렴</td></tr>`;
        }).join('')
      : `<tr><td colspan="9" class="muted"
           style="text-align:center;padding:20px">검색 결과 없음</td></tr>`;

    $('#q1TblHit').textContent =
      q ? `${prods.length}개 중 ${list.length}개` : `상품 ${prods.length}개`;
  }

  tblQ.oninput = draw;

  $('#q1Tbl').querySelectorAll('th[data-k]').forEach(th=>{
    th.style.cursor='pointer';
    th.onclick = ()=>{ const k=th.dataset.k;
      if(key===k) dir*=-1; else { key=k; dir=-1; } draw(); };
  });

  tb.onclick = e=>{
    const tr=e.target.closest('tr'); if(!tr||!tr.dataset.i) return;
    const i = tr.dataset.i;
    pick.value = i;
    // 밴드 쪽 검색어에 걸려 그 상품이 목록에 없으면 value 가 빈 값이 된다.
    // 그때는 검색어를 지워 목록을 되살린 뒤 다시 고른다.
    if(pick.value !== i){ bandQ.value=''; fillPick(); pick.value=i; }
    drawBand();
    $('#q1Band').scrollIntoView({behavior:'smooth',block:'center'}); };

  draw();
}

/* ================= Q2 ================= */
/*
   계절을 걷어내지 않고 비교한다.

   09_analyze.py 가 상대가격(그 시점 가격 ÷ 그 해 중앙값 — 물가만 걷어낸 값)을
   기온·강수량과 바로 견준 결과를 그린다. 여름에 기온이 높고 여름 배추가 비싸면
   그 동행까지 관계로 센다.

   화면에는 전체 상품 중 '뚜렷한 관계' 로 잡힌 상품만 올린다.
   나머지 상품은 q2_weather_<주기>.csv 에 전부 있다.
*/

function renderQ2(){
  const box=$('#q2Body'), q2=D.q2, unit=D.meta.unit;

  if(!q2.available){
    box.innerHTML = `<div class="missing">이 주기에는 기상 자료가 없어 비어 있다.<br>
      입력 파일에 기온·강수량 컬럼이 있는지 확인하세요.</div>`;
    return;
  }

  const o = q2.overall || {}, c = q2.counts || {};
  const rows0 = q2.products || [];

  const weakLine = q2.weakLine, strongLine = q2.strongLine;
  const listedLine = (q2.listedLine !== undefined && q2.listedLine !== null)
    ? q2.listedLine : strongLine;
  const onlyWeak = q2.listedKind === 'weak';

  /* 옛 결과 파일은 계절을 걷어낸(이탈도) 값이라 숫자의 뜻이 다르다.
     조용히 그리면 "왜 값이 이렇게 작지" 로 읽히므로 눈에 보이게 알린다. */
  const stale = (q2.basis !== 'raw')
    ? `<div class="callout"><strong>읽어 들인 결과가 옛 방식이다.</strong>
        이 화면은 계절을 걷어내지 않은 값을 그리도록 되어 있는데,
        json 은 계절을 걷어낸(이탈도) 기준으로 만들어져 있다.
        <code>python 09_analyze.py</code> 를 다시 돌려야 숫자가 맞는다.</div>`
    : '';

  const strength = p => Math.max(Math.abs(p.tCorr ?? 0), Math.abs(p.rCorr ?? 0));
  const has = v => v !== null && v !== undefined && Math.abs(v) >= weakLine;

  const share = c.total ? (c.strong || 0) / c.total * 100 : 0;

  const msg = (c.strong)
    ? `그렇다. 상품 ${c.strong}개에서 기온·강수량과 뚜렷한 관계가 나타났다.`
    : (c.weak
        ? `뚜렷한 상품은 없다. 약한 관계가 보이는 상품이 ${c.weak}개 있다.`
        : '이 자료에서는 날씨와 가격이 함께 움직인다는 근거를 찾지 못했다.');

  const tone = c.strong ? '' : c.weak ? 'warn' : 'none';

  const lagText = v => v===null||v===undefined ? '—'
    : (v===0 ? `같은 ${unit}` : `${v}${unit} 뒤`);

  box.innerHTML = `
    ${stale}
    <div class="answer ${tone}">${msg}
    </div>


    <h3>전체를 한 덩어리로 묶으면</h3>
    <div class="grid">
      <div class="stat hot"><div class="label">기온 vs 가격</div>
        <div class="value">${nf(o.temp)}</div></div>
      <div class="stat cold"><div class="label">강수량 vs 가격</div>
        <div class="value">${nf(o.rain)}</div></div>
      <div class="stat"><div class="label">뚜렷 / 약하지만 있음</div>
        <div class="value">${c.strong||0} / ${c.weak||0}</div></div>
      <div class="stat"><div class="label">폭염·호우 기준</div>
        <div class="value" style="font-size:19px">${q2.thresholds.hot}도 · ${q2.thresholds.wet}mm</div>
        </div>
    </div>

    <h3 id="q2ListHead"></h3>
    <p class="muted small" id="q2ListNote" style="margin:-4px 0 10px"></p>
    <div class="row">
      <input type="search" id="q2Q" placeholder="품목·품종 검색">
      <span class="muted small" id="q2Hit"></span>
    </div>
    <div class="scroll"><table id="q2Tbl">
      <thead><tr>
        <th></th>
        <th data-k="item">품목</th><th data-k="variety">품종</th>
        <th>등급</th><th>단위</th>
        <th class="num" data-k="tCorr">기온과 같이 움직인 정도</th>
        <th class="num" data-k="tLag">기온 반응 시점</th>
        <th class="num" data-k="rCorr">비와 같이 움직인 정도</th>
        <th class="num" data-k="rLag">비 반응 시점</th>
        <th data-k="dir">함께 움직인 방향</th>
        <th class="num" data-k="n">관측</th>
      </tr></thead><tbody></tbody></table></div>
    <div class="detail" id="q2Detail" style="display:none"></div>


    <h3>폭염·호우 이후 ${q2.thresholds.window}${unit}, 그 해 평균 대비</h3>
    <div class="grid" id="q2Events"></div>`;

  /* ---- 뚜렷한 관계를 보인 상품 목록 ---- */

  $('#q2ListHead').textContent = onlyWeak
    ? `뚜렷한 상품이 없어 약한 관계라도 보이는 상품 ${rows0.length.toLocaleString()}개`
    : `뚜렷한 관계를 보인 상품 ${rows0.length.toLocaleString()}개`;

  $('#q2ListNote').innerHTML =
   (q2.cut ? ` 상위 ${rows0.length.toLocaleString()}개까지만 실었고
        나머지 ${q2.cut.toLocaleString()}개는 q2_weather_${D.meta.freq}.csv 에 있다.` : '');

  if(!rows0.length){
    $('#q2Tbl').closest('.scroll').innerHTML =
      `<div class="missing">기온·강수량과 함께 움직인 상품이 없다.<br>
        판정선은 약함 ${weakLine} · 뚜렷 ${strongLine} 이다.</div>`;
    drawEvents();
    return;
  }

  // 순위는 관계가 센 순서로 한 번만 매겨 고정한다.
  // 검색하거나 다른 열로 정렬해도 번호가 따라 바뀌면 "몇 등인지" 를 알 수 없다.
  const ranked = rows0.slice().sort((a,b) => strength(b) - strength(a));
  const RANK = new Map(ranked.map((p,i) => [p.pkey, i+1]));

  // 부호와 시차를 짧은 말로 바꾼다. 상관의 부호는 '같이 움직였다' 는 뜻뿐이다.
  function dirText(p){
    const bits = [];
    if(has(p.tCorr)) bits.push(p.tCorr > 0 ? '기온 높을 때 비쌈' : '기온 높을 때 쌈');
    if(has(p.rCorr)) bits.push(p.rCorr > 0 ? '비 많을 때 비쌈' : '비 많을 때 쌈');
    return bits.join(' · ') || '—';
  }

  const tb=$('#q2Tbl tbody');
  let key='str', dir=-1;

  function list(){
    const q=($('#q2Q').value||'').trim().toLowerCase();
    return rows0.filter(p=>!q||searchText(p).includes(q));
  }

  function draw(){
    const hits=list();

    const sorted = hits.slice().sort((a,b)=>{
      if(key==='str') return dir*(strength(a)-strength(b));
      if(key==='dir') return dir*dirText(a).localeCompare(dirText(b),'ko');
      let x=a[key], y=b[key];
      if(typeof x==='string') return dir*x.localeCompare(y,'ko');
      if(key==='tCorr'||key==='rCorr'){ x=Math.abs(x??0); y=Math.abs(y??0); }
      return dir*((x??-1e9)-(y??-1e9));
    });

    tb.innerHTML = sorted.length
      ? sorted.map(p=>{
          const r=RANK.get(p.pkey);
          return `<tr data-k="${p.pkey}">
            <td class="rank ${r<=10?'top':''}">${r}</td>
            <td>${p.item}</td><td>${p.variety}</td>
            <td class="muted">${gradeOf(p)||'—'}</td>
            <td class="muted">${p.unit||'—'}</td>
            <td class="num">${trackBar(p.tCorr,0.9,strongLine)}</td>
            <td class="num muted">${lagText(p.tLag)}</td>
            <td class="num">${trackBar(p.rCorr,0.9,strongLine)}</td>
            <td class="num muted">${lagText(p.rLag)}</td>
            <td class="small">${dirText(p)}</td>
            <td class="num muted">${(p.n||0).toLocaleString()}</td></tr>`;
        }).join('')
      : `<tr><td colspan="11" class="muted"
           style="text-align:center;padding:20px">검색 결과 없음</td></tr>`;

    const q=($('#q2Q').value||'').trim();
    $('#q2Hit').textContent = q
      ? `${rows0.length.toLocaleString()}개 중 ${sorted.length.toLocaleString()}개`
      : `상품 ${rows0.length.toLocaleString()}개`;
  }

  $('#q2Tbl').querySelectorAll('th').forEach(th=>{
    const k=th.dataset.k; if(!k) return;
    th.onclick=()=>{ if(key===k) dir*=-1; else { key=k; dir=-1; } draw(); };
  });

  $('#q2Q').oninput = draw;

  tb.onclick = e=>{
    const tr=e.target.closest('tr'); if(!tr||!tr.dataset.k) return;
    tb.querySelectorAll('tr').forEach(x=>x.classList.remove('on'));
    tr.classList.add('on');
    showLag(rows0.find(p=>p.pkey===tr.dataset.k));
  };

  function showLag(p){
    if(!p) return;
    const n=q2.maxLag+1, W=620, H=190, L=40, B=26;
    const all=(p.tLags||[]).concat(p.rLags||[]).filter(v=>v!==null).map(Math.abs);
    const top=Math.max(0.3, Math.ceil(Math.max(...all,0.1)*10)/10);
    const X=i=>L+i*(W-L-14)/(n-1);
    const Y=v=>(H-B)/2-(v/top)*((H-B)/2-14)+6;

    const series=(arr,color)=>{
      const pts=(arr||[]).map((v,i)=>v===null?null:`${X(i)},${Y(v)}`).filter(Boolean).join(' ');
      if(!pts) return '';
      return `<polyline points="${pts}" fill="none" stroke="${color}" stroke-width="2.2"/>`
        + (arr||[]).map((v,i)=>v===null?'':`<circle cx="${X(i)}" cy="${Y(v)}" r="3.2" fill="${color}"/>`).join('');
    };

    const guides=[strongLine,-strongLine].map(v=>
      `<line x1="${L}" y1="${Y(v)}" x2="${W-14}" y2="${Y(v)}" stroke="#d97706"
        stroke-dasharray="3 3" opacity=".6"/>`).join('');

    const step = Math.max(1, Math.round(n/10));
    const ticks=Array.from({length:n},(_,i)=>
      (i%step===0||i===n-1)
        ? `<text x="${X(i)}" y="${H-8}" font-size="10.5" fill="#9aa1ab"
            text-anchor="middle">${i}</text>` : '').join('');

    $('#q2Detail').style.display='block';
    $('#q2Detail').innerHTML = `
      <h4>${fullName(p)}</h4>
      <div class="meta">관측 ${(p.n||0).toLocaleString()}${unit} ·
        기온 ${nf(p.tCorr)} (${lagText(p.tLag)}) ·
        강수 ${nf(p.rCorr)} (${lagText(p.rLag)}) · ${dirText(p)}</div>
      ${svg(W,H, `<line x1="${L}" y1="${Y(0)}" x2="${W-14}" y2="${Y(0)}" stroke="#d1d5db"/>
        ${guides}${series(p.tLags,'#c0392b')}${series(p.rLags,'#2563eb')}${ticks}
        <text x="6" y="${Y(top)+4}" font-size="10.5" fill="#9aa1ab">${top.toFixed(1)}</text>
        <text x="6" y="${Y(-top)+4}" font-size="10.5" fill="#9aa1ab">-${top.toFixed(1)}</text>`)}
      <p class="muted small" style="margin:6px 0 0">
        가로축은 시차(${unit}) — 기상이 몇 ${unit} 앞서는가.
        <span style="color:#c0392b">■</span> 기온
        <span style="color:#2563eb;margin-left:6px">■</span> 강수량 ·
        주황 점선은 뚜렷하다고 본 선(±${strongLine})</p>`;
  }

  function drawEvents(){
    $('#q2Events').innerHTML = ['폭염','호우'].map(kind=>{
      const rows=(q2.events[kind]||[]);
      if(!rows.length) return `<div class="stat"><div class="label">${kind}</div>
        <div class="note">자료가 모자라 계산하지 못했다</div></div>`;
      const body=rows.slice(0,7).map(r=>`<tr><td>${r.item}</td>
        <td class="num" style="color:${r.pct>0?'#c0392b':'#2563eb'}">${nf(r.pct,1)}%</td>
        <td class="num muted">${r.n}회</td></tr>`).join('');
      return `<div class="stat" style="grid-column:span 2">
        <div class="label">${kind} 직후 ${q2.thresholds.window}${unit} — 그 해 평균 대비</div>
        <table style="margin-top:6px"><tbody>${body}</tbody></table></div>`;
    }).join('');
  }

  drawEvents();
  draw();
}

/* ================= Q3 ================= */

function renderQ3(){
  const box=$('#q3Body'), q3=D.q3;

  if(!q3.available){
    box.innerHTML = `<div class="missing">
      소비자물가지수가 없어 이 절은 비어 있다.<br>
      ${q3.reason||''}<br>
      KOSIS 에서 받아 <code>data/raw/cpi.csv</code> 로 두면 채워진다.</div>`;
    return;
  }

  const faster=q3.fasterCount, total=q3.totalItems;
  const share = total ? faster/total*100 : 0;
  const msg = share>=60
    ? `대부분의 품목이 물가보다 더 올랐다. ${total}개 중 ${faster}개.`
    : share>=30
      ? `절반 가까이가 물가보다 더 올랐다 — ${total}개 중 ${faster}개`
      : `대부분은 물가만큼 또는 그보다 덜 올랐다 — 물가보다 더 오른 건 ${faster}개`;

  /* '물가로 설명되는 몫' 을 낼 수 없는 품목은 표에서 뺀다.
     몫 = 물가상승률 / 명목상승률 이라 명목이 0 이하면 뜻을 잃는다.
     그런 자리를 그대로 그리면 화면에 'NaN%' 가 찍힌다.
     조용히 빼면 개수가 안 맞아 보이므로, 몇 개를 뺐는지는 표 위에 적는다. */
  const q3all = q3.items.slice();
  //  999 는 09_analyze.py 가 씌운 상한이다. 명목이 거의 오르지 않아
  //  몫이 무한대에 가깝게 튄 자리라, 숫자로서 뜻이 없으므로 함께 뺀다.
  const rows = q3all
    .filter(r => Number.isFinite(r.explained) && r.explained < 999)
    .sort((a,b)=>b.nominal-a.nominal);
  const q3hidden = q3all.length - rows.length;

  const maxAbs=Math.max(...rows.flatMap(r=>[Math.abs(r.nominal),Math.abs(r.real)]),10);

  // 막대 길이는 걸러내기 전 전체 기준으로 맞춘다.
  // 검색할 때마다 기준을 다시 잡으면 같은 +50% 가 검색어에 따라 길어졌다 짧아졌다 한다.
  const barRow=r=>{
    const w=v=>Math.min(Math.abs(v)/maxAbs,1)*120;
    const c=v=>v>=0?'#c0392b':'#2563eb';
    return `<tr><td>${r.item}</td>
      <td class="num"><span style="display:inline-block;width:${w(r.nominal)}px;height:9px;
        background:${c(r.nominal)};border-radius:2px;vertical-align:middle"></span>
        <span style="margin-left:7px">${nf(r.nominal,1)}%</span></td>
      <td class="num"><span style="display:inline-block;width:${w(r.real)}px;height:9px;
        background:${c(r.real)};opacity:.55;border-radius:2px;vertical-align:middle"></span>
        <span style="margin-left:7px">${nf(r.real,1)}%</span></td>
      <td class="num">${r.explained===null?'—':r.explained.toFixed(0)+'%'}</td></tr>`;
  };

  const cs=q3.cpiSeries, W=620,H=150,L=44,B=26;
  const cmin=Math.min(...cs.map(d=>d.cpi)), cmax=Math.max(...cs.map(d=>d.cpi));
  const X=i=>L+i*(W-L-14)/Math.max(1,cs.length-1);
  const Y=v=>12+(1-(v-cmin)/(cmax-cmin||1))*(H-B-20);
  const cline=cs.map((d,i)=>`${X(i)},${Y(d.cpi)}`).join(' ');
  const cticks=cs.map((d,i)=>(i%2===0||i===cs.length-1)
    ? `<text x="${X(i)}" y="${H-8}" font-size="10.5" fill="#9aa1ab"
        text-anchor="middle">${d.year}</text>` : '').join('');

  box.innerHTML = `
    <div class="answer">${msg}</div>

    <div class="grid">
      <div class="stat"><div class="label">소비자물가 상승 </div>
        <div class="value">${nf(q3.cpiGrowth,1)}%</div></div>
      <div class="stat hot"><div class="label">명목 상승률 중앙값</div>
        <div class="value">${nf(q3.medianNominal,1)}%</div>
        </div>
      <div class="stat calm"><div class="label">실질 상승률 중앙값</div>
        <div class="value">${nf(q3.medianReal,1)}%</div>
        </div>
      <div class="stat"><div class="label">물가보다 더 오른 품목</div>
        <div class="value">${faster}<span style="font-size:15px;color:var(--muted)"> / ${total}</span></div>
        </div>
    </div>

    <h3>소비자물가지수 추이</h3>
    ${svg(W,H,`<polyline points="${cline}" fill="none" stroke="#0f766e" stroke-width="2.4"/>
      ${cs.map((d,i)=>`<circle cx="${X(i)}" cy="${Y(d.cpi)}" r="3" fill="#0f766e"/>`).join('')}
      ${cticks}
      <text x="6" y="${Y(cmax)+4}" font-size="10.5" fill="#9aa1ab">${cmax.toFixed(0)}</text>
      <text x="6" y="${Y(cmin)+4}" font-size="10.5" fill="#9aa1ab">${cmin.toFixed(0)}</text>`)}

    <h3>품목별 명목 vs 실질 상승률</h3>
    <div class="row">
      <input type="search" id="q3Q" placeholder="품목 검색">
      <span class="muted small" id="q3Hit"></span>
    </div>
    <div class="scroll"><table>
      <thead><tr><th>품목</th><th class="num">명목 (체감 가격)</th>
        <th class="num">실질 (물가 제거)</th>
        <th class="num">물가로 설명되는 몫</th></tr></thead>
      <tbody id="q3Tbody"></tbody></table></div>
    </div>`;

  const q3tb=$('#q3Tbody'), q3q=$('#q3Q');
  q3q.value = q3Query;

  function drawQ3(){
    q3Query = q3q.value;
    const q=(q3q.value||'').trim().toLowerCase();
    const hits=rows.filter(r=>!q||String(r.item).toLowerCase().includes(q));
    q3tb.innerHTML = hits.length
      ? hits.map(barRow).join('')
      : `<tr><td colspan="4" class="muted" style="text-align:center;padding:20px">${
          rows.length ? '검색 결과 없음'
                      : '물가로 설명되는 몫을 낼 수 있는 품목이 없다'}</td></tr>`;
    $('#q3Hit').textContent =
      q ? `${rows.length}개 중 ${hits.length}개` : `품목 ${rows.length}개`;
  }

  q3q.oninput=drawQ3;
  drawQ3();
}

/* ================= Q4 ================= */

function renderQ4(){
  const box=$('#q4Body'), q4=D.q4, unit=D.meta.unit;

  if(!q4.available){
    box.innerHTML = `<div class="missing">과거 분포와 비교할 수 있는 상품이 없다.<br>
      같은 자리에 최소 3개 연도가 필요하다.</div>`;
    return;
  }

  const order=['매우 쌈','쌈','보통','비쌈','매우 비쌈'];
  const colors={'매우 쌈':'#1d4ed8','쌈':'#60a5fa','보통':'#d1d5db',
                '비쌈':'#f87171','매우 비쌈':'#b91c1c'};
  const inkOf={'매우 쌈':'#1d4ed8','쌈':'#2563eb','보통':'#6b7280',
               '비쌈':'#dc2626','매우 비쌈':'#b91c1c'};

  const total=order.reduce((s,k)=>s+(q4.counts[k]||0),0)||1;

  const stack=order.map(k=>{
    const n=q4.counts[k]||0;
    return n ? `<div title="${k} ${n}개" style="flex:${n};background:${colors[k]};height:100%"></div>` : '';
  }).join('');

  const legend=order.map(k=>
    `<span><span class="key" style="background:${colors[k]}"></span>${k}
      ${(q4.counts[k]||0).toLocaleString()}개</span>`).join('');

  /* 위치는 하나뿐이다.
     예전에는 '계절 위치'(물가 걷어낸 값)와 '명목 위치'(그대로의 값)를 나란히 뒀지만,
     이제 물가를 걷어내지 않으므로 두 값이 같아진다. 한 열로 합쳤다. */
  const rows=q4.products.slice().sort((a,b)=>b.posPct-a.posPct);
  const posRow=p=>`<tr>
    <td>${p.item}</td><td>${p.variety}</td>
    <td class="muted">${gradeOf(p)||'—'}</td>
    <td class="muted">${p.unit||'—'}</td>
    <td class="num">${p.price.toLocaleString()}원</td>
    <td class="num"><span class="gauge"><b style="left:${p.posPct*1.2}px"></b></span>
      <span style="margin-left:8px">${p.posPct.toFixed(0)}</span></td>
    <td class="num muted">${p.pastYears!==undefined ? p.pastYears+'년' : p.pastN+'건'}</td>
    <td class="num"><strong style="color:${inkOf[p.verdict]}">${p.verdict}</strong></td>
  </tr>`;

  box.innerHTML = `
    <div class="answer">앞날의 값을 맞히지는 못한다.
      해마다 같은 시기에 같은 자리로 돌아오는지까지 말할 수 있다.
      ${q4.asOf.label||q4.asOf.year} 기준 ${total.toLocaleString()}개 상품을 판정했다.
      </div>

    <h3>${q4.asOf.label||q4.asOf.year} 기준, 예년 같은 시기 대비 어디쯤인가</h3>
    <div style="display:flex;height:26px;border-radius:6px;overflow:hidden;
      border:1px solid var(--line)">${stack}</div>
    <div class="legend">${legend}</div>

    <h3>상품별 위치</h3>
    <div class="row">
      <input type="search" id="q4Q" placeholder="품목·품종 검색">
      <span class="muted small" id="q4Hit"></span>
    </div>
    <div class="scroll"><table>
      <thead><tr><th>품목</th><th>품종</th><th>등급</th><th>단위</th>
        <th class="num">현재 가격</th>
        <th class="num">가격 위치 (판정 근거)</th>
        <th class="num">비교한 과거 연수</th><th class="num">판정</th></tr></thead>
      <tbody id="q4Tbody"></tbody></table></div>

    </div>`;

  const q4tb=$('#q4Tbody'), q4q=$('#q4Q');
  q4q.value = q4Query;

  function drawQ4(){
    q4Query = q4q.value;
    const q=(q4q.value||'').trim().toLowerCase();
    const hits=rows.filter(p=>!q||searchText(p).includes(q));
    q4tb.innerHTML = hits.length
      ? hits.map(posRow).join('')
      : `<tr><td colspan="8" class="muted"
           style="text-align:center;padding:20px">검색 결과 없음</td></tr>`;
    $('#q4Hit').textContent =
      q ? `${rows.length}개 중 ${hits.length}개` : `상품 ${rows.length}개`;
  }

  q4q.oninput=drawQ4;
  drawQ4();
}

/* ================= 네비게이션 ================= */

const links=[...document.querySelectorAll('nav a')];
const secs=links.map(a=>document.querySelector(a.getAttribute('href')));

const topbar=document.querySelector('.topbar');

addEventListener('scroll',()=>{
  const y=scrollY+(topbar?topbar.offsetHeight:80)+40; let idx=0;
  secs.forEach((s,i)=>{ if(s&&s.offsetTop<=y) idx=i; });
  links.forEach((a,i)=>a.classList.toggle('on', i===idx));
},{passive:true});

render();
</script>
</body>
</html>
"""

page = (TEMPLATE
        .replace("__TITLE__", html.escape(TITLE))
        .replace("__SUBTITLE__", html.escape(SUBTITLE))
        .replace("__DATA_JSON__", json.dumps(bundle, ensure_ascii=False)))

OUT_FILE.write_text(page, encoding="utf-8")

size = OUT_FILE.stat().st_size / 1024

print("\n" + "=" * 60)
print("저장")
print("=" * 60)

print(f"{OUT_FILE}  ({size:,.0f} KB)")
print(f"담긴 주기: " + " · ".join(
    bundle[f]["meta"].get("freqLabel", f) for f in bundle))
print("\n더블클릭하면 브라우저에서 열립니다. 서버도 인터넷도 필요 없습니다.")
print("화면 맨 위에서 일별 · 주별 · 월별을 갈아 끼울 수 있습니다.")
