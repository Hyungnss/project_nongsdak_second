// 품목 상세의 '다음 1 · 2 · 4주 예상 가격'.
//
// 약속한 API:  GET /api/forecast?item=211&kind=03&rank=상품&market=retail
//   → {item_code, kind_code, rank, unit, base_date, base_price, model,
//      points: [{h, target_date, price, change_pct}, ...]}
//   · points 가 [] 이면 그 품종은 예측이 아직 없다 → '예측 준비 중'
//   · 404 · 오류면 예측 영역만 숨기고 나머지 화면은 그대로 둔다 (load 가 null 을 돌려준다)
//   · model 이름은 바뀐다 ("blend" → "lgbm-v1" …). 받은 이름을 그대로 보여 준다.
//
// 주소에 ?mock=forecast 가 있을 때만 화면에서 만든 가짜 예측을 쓴다 (API 가 생기기 전 개발용).
// ?mock=forecast-empty 는 '예측 준비 중' 모양을 보기 위한 빈 예측이다.
// mock 이 없으면 늘 진짜 API 를 부르므로, API 가 생기면 이 파일을 고치지 않아도 된다.
(function(){
  'use strict';

  const MOCK = new URLSearchParams(location.search).get('mock');
  const esc = s => String(s).replace(/[&<>"]/g, c =>
    ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
  const won = n => Math.round(n).toLocaleString('ko-KR');
  const md = s => `${+s.slice(5, 7)}/${+s.slice(8, 10)}`;
  // 화면에 보일 기간 이름. 7 · 14 · 28 이 아니어도 대략 맞는 말로 바꾼다.
  const hName = h => h % 7 === 0 ? `${h / 7}주 뒤` : `${h}일 뒤`;
  const dirOf = p => p > 0.05 ? 'up' : (p < -0.05 ? 'down' : 'flat');
  const markOf = p => p > 0.05 ? '▲' : (p < -0.05 ? '▼' : '―');

  // ── 가짜 예측 (?mock=forecast) ────────────────────────────────────
  // 품목 · 품종 코드로 정해지는 값이라 새로고침해도 같은 숫자가 나온다.
  function mockOf(q, base){
    if(MOCK === 'forecast-empty') return {...base, model: 'blend', points: []};
    let seed = 0;
    for(const ch of q.item + (q.kind || '') + (q.market || '')) seed = (seed * 31 + ch.charCodeAt(0)) >>> 0;
    const rnd = () => (seed = (seed * 1103515245 + 12345) >>> 0) / 4294967296;
    const drift = (rnd() - 0.5) * 0.06;        // 주당 ±3% 안쪽
    const day0 = Date.parse(base.base_date);
    const points = [7, 14, 28].map(h => {
      const pct = (drift * h / 7 + (rnd() - 0.5) * 0.02) * 100;
      return {
        h,
        target_date: new Date(day0 + h * 86400000).toISOString().slice(0, 10),
        price: Math.round(base.base_price * (1 + pct / 100)),
        change_pct: Math.round(pct * 10) / 10,
      };
    });
    return {...base, model: 'blend (가짜)', points};
  }

  // 예측을 받아 온다. 보여 줄 게 없으면(404 · 오류 · 모양이 이상함) null.
  // base: 상세에서 이미 아는 값 {unit, base_date, base_price} — 가짜 예측의 출발점으로만 쓴다.
  async function load(q, base){
    const params = {item: q.item, market: q.market};
    if(q.kind) params.kind = q.kind;
    if(q.rank) params.rank = q.rank;
    if(MOCK === 'forecast' || MOCK === 'forecast-empty'){
      await new Promise(r => setTimeout(r, 150));   // 늦게 오는 응답도 흉내 낸다
      return mockOf(q, {item_code: q.item, kind_code: q.kind, rank: q.rank, ...base});
    }
    try{
      const r = await fetch('/api/forecast?' + new URLSearchParams(params));
      if(!r.ok) return null;
      const d = await r.json();
      if(!d || !Array.isArray(d.points)) return null;
      d.points = d.points
        .filter(p => p && p.price != null && p.h > 0 && p.target_date)
        .sort((a, b) => a.h - b.h);
      return d;
    }catch(e){
      return null;
    }
  }

  // 상세의 예상 가격 칸. points 가 없으면 '예측 준비 중' 한 줄.
  // wholesale 이면 단위를 더 진하게 보여 준다 (상자 · 10kg 값을 한 개 값으로 읽지 않도록).
  function panel(fc, market){
    if(!fc) return '';
    const unit = fc.unit ? esc(fc.unit) : '';
    const unitCls = market === 'wholesale' ? 'fc-u wh' : 'fc-u';
    if(!fc.points.length){
      return `<section class="fc fc-empty" aria-label="예상 가격">
        <div class="fc-head"><h3>다음 주 예상 가격</h3><span class="fc-tag">예상</span></div>
        <p class="fc-none">이 품종은 예측을 준비하고 있어요.</p></section>`;
    }
    const cells = fc.points.slice(0, 3).map(p => {
      const dir = dirOf(p.change_pct);
      const pct = p.change_pct == null ? '' :
        `<span class="fc-pct ${dir}">${markOf(p.change_pct)} ${Math.abs(p.change_pct).toFixed(1)}%</span>`;
      return `<div class="fc-c">
        <span class="fc-h">${hName(p.h)} <small>${md(p.target_date)}</small></span>
        <span class="fc-p">${won(p.price)}<small>원</small></span>
        <span class="${unitCls}">${unit ? unit + " 기준" : ""}</span>
        ${pct}</div>`;
    }).join('');
    const base = fc.base_price != null
      ? `${fc.base_date ? md(fc.base_date) + ' ' : ''}${won(fc.base_price)}원 기준` : '';
    return `<section class="fc" aria-label="다음 1·2·4주 예상 가격">
      <div class="fc-head"><h3>다음 1 · 2 · 4주 예상 가격</h3><span class="fc-tag">예상</span></div>
      <div class="fc-row">${cells}</div>
      <p class="fc-note">지난 시세로 계산한 <b>예상값</b>이에요. 날씨 · 작황 · 수입량에 따라 실제 가격은 달라질 수 있어요.</p>
      <p class="fc-meta">${base ? `<span>${base}</span>` : ''}<span>예측 모델 <code>${esc(fc.model || '—')}</code></span></p>
    </section>`;
  }

  // 차트에 덧그리는 예측 부분. index.html 의 chart() 가 좌표를 넘겨준다.
  //   x0, y0: 마지막 실제 가격 점   xEnd: 예측 구간 오른쪽 끝   T, B: 그림 위 · 아래
  //   ys: 가격 → y 좌표   hMax: 예측 구간이 나타내는 날 수
  function chartLayer(fc, g){
    if(!fc || !fc.points.length) return '';
    const xs = h => g.x0 + h / g.hMax * (g.xEnd - g.x0);
    const pts = fc.points.map(p => [xs(p.h), g.ys(p.price), p]);
    const line = [[g.x0, g.y0], ...pts].map(([x, y]) => `${x.toFixed(1)},${y.toFixed(1)}`).join('L');
    const last = pts[pts.length - 1];
    const dir = dirOf(last[2].change_pct);
    const dots = pts.map(([x, y]) =>
      `<circle class="fc-dot ${dir}" cx="${x.toFixed(1)}" cy="${y.toFixed(1)}" r="3.5"/>`).join('');
    return `<g class="fc-layer">
      <rect class="fc-zone" x="${g.x0.toFixed(1)}" y="${g.T}" width="${(g.xEnd - g.x0 + g.R).toFixed(1)}" height="${g.B - g.T}"/>
      <line class="fc-now" x1="${g.x0.toFixed(1)}" y1="${g.T}" x2="${g.x0.toFixed(1)}" y2="${g.B}"/>
      <text class="fc-zlbl" x="${(g.x0 + 6).toFixed(1)}" y="${g.T + 12}">예상</text>
      <path class="fc-line ${dir}" d="M${line}"/>${dots}
      <text class="tick" x="${(g.xEnd).toFixed(1)}" y="${g.B + g.tickDy}" text-anchor="end">${md(last[2].target_date)}</text>
    </g>`;
  }

  // 차트의 세로 범위를 잡을 때 예측 가격도 넣어야 선이 잘리지 않는다
  const prices = fc => fc && fc.points.length ? fc.points.map(p => p.price) : [];

  window.nongsdaqForecast = {load, panel, chartLayer, prices};
})();
