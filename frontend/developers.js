// 개발자 페이지 (/developers) — 공개 API 소개 · 키 발급 · 사용량 · 문서.
//
// 로그인은 auth.js(window.nongsdaqAuth)를 그대로 쓴다. 키 관리는 /api/keys/* (로그인 쿠키),
// 데이터 상태는 /api/v1/status (키 없이) 를 부른다.
// 키 원문은 발급 직후 화면(과 예시 코드)에만 잠깐 두고 어디에도 저장하지 않는다.
(() => {
  const $ = s => document.querySelector(s);
  const esc = s => String(s ?? '').replace(/[&<>"']/g, c =>
    ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const fmt = n => Number(n).toLocaleString('ko-KR');
  const BASE = location.origin + '/api/v1';
  let issuedKey = null;          // 방금 발급한 키 — 예시 코드에 잠깐 넣는다 (새로고침하면 사라진다)

  // ── 테마 (메인 화면과 같은 키) ──────────────────────────────────────────
  const themeBtn = $('#themebtn');
  const curTheme = () => document.documentElement.getAttribute('data-theme') === 'dark' ? 'dark' : 'light';
  function paintTheme(){
    const dark = curTheme() === 'dark';
    themeBtn.textContent = dark ? '☀️' : '🌙';
    themeBtn.setAttribute('aria-label', dark ? '라이트 모드로 바꾸기' : '다크 모드로 바꾸기');
  }
  themeBtn.addEventListener('click', () => {
    const t = curTheme() === 'dark' ? 'light' : 'dark';
    document.documentElement.setAttribute('data-theme', t);
    try{ localStorage.setItem('nongsdaq-theme', t); }catch(e){}
    paintTheme();
  });
  paintTheme();

  // ── 예시 코드 ───────────────────────────────────────────────────────────
  const SAMPLES = {
    latest: {path: '/prices/latest', query: {item: '211', market: 'retail'}},
    history: {path: '/prices/history', query: {item: '211', kind: '03', rank: '상품', start: '2026-10-01'}},
  };
  function sample(name, lang){
    const s = SAMPLES[name];
    const key = issuedKey || 'YOUR_API_KEY';
    const url = `${BASE}${s.path}`;
    const q = Object.entries(s.query);
    if(lang === 'python'){
      const params = Object.entries(s.query).map(([k, v]) => `"${k}": "${v}"`).join(', ');
      return [
        '<span class="c"># pip install requests</span>',
        'import requests',
        '',
        'r = requests.get(',
        `    "${BASE}${s.path}",`,
        `    params={${esc(params)}},`,
        `    headers={"X-API-Key": "${esc(key)}"},`,
        '    timeout=10,',
        ')',
        'r.raise_for_status()',
        'for row in r.json()["data"]:',
        '    print(row["survey_date"], row["item_name"], row["rank"], row["price"], row["unit"])',
      ].join('\n');
    }
    if(lang === 'js'){
      return [
        `const params = new URLSearchParams({ ${esc(q.map(([k, v]) => `${k}: "${v}"`).join(', '))} });`,
        `const res = await fetch("${esc(url)}?" + params, {`,
        `  headers: { "X-API-Key": "${esc(key)}" },`,
        '});',
        'if (!res.ok) throw new Error((await res.json()).error.message);',
        'const { data, meta } = await res.json();',
        'console.log(meta.count, data[0]);',
        '',
        '<span class="c">// 키가 브라우저에 드러나므로, 공개 웹사이트라면 서버에서 부르세요</span>',
      ].join('\n');
    }
    // -G : --data-urlencode 값을 주소 뒤 ?a=b 로 붙인다 (한글도 알아서 인코딩)
    return [
      `curl -G "${esc(url)}" \\`,
      `  -H "X-API-Key: ${esc(key)}" \\`,
      ...q.map(([k, v], i) => `  --data-urlencode "${esc(k)}=${esc(v)}"` + (i < q.length - 1 ? ' \\' : '')),
    ].join('\n');
  }
  function paintSamples(){
    document.querySelectorAll('[data-tabs]').forEach(box => {
      const lang = box.querySelector('[aria-selected="true"]').dataset.lang;
      box.querySelector('pre').innerHTML = sample(box.querySelector('pre').dataset.sample, lang);
    });
  }
  document.querySelectorAll('[data-tabs]').forEach(box => {
    box.addEventListener('click', async e => {
      const tab = e.target.closest('[data-lang]');
      if(tab){
        box.querySelectorAll('[data-lang]').forEach(b => b.setAttribute('aria-selected', b === tab));
        paintSamples();
      }
      if(e.target.closest('[data-copy]')){
        await copy(box.querySelector('pre').textContent, e.target);
      }
    });
  });
  async function copy(text, btn){
    try{
      await navigator.clipboard.writeText(text);
      const old = btn.textContent;
      btn.textContent = '복사됨';
      setTimeout(() => { btn.textContent = old; }, 1500);
    }catch(e){
      btn.textContent = '복사 실패';
    }
  }
  $('#base-url').textContent = BASE;
  paintSamples();

  // ── 데이터 상태 (키 없이) ────────────────────────────────────────────────
  fetch('/api/v1/status').then(r => r.ok ? r.json() : Promise.reject(r.status)).then(({data, meta}) => {
    const r = data.retail, w = data.wholesale;
    $('#f-range').textContent = `${r.earliest_date?.slice(0, 7) ?? '—'} ~ ${r.latest_date ?? '—'}`;
    $('#f-items').textContent = `${r.items} · ${w.items}개`;
    const at = r.last_fetched_at ? new Date(r.last_fetched_at) : null;
    const when = at ? at.toLocaleString('ko-KR', {month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit'}) : '기록 없음';
    $('#live').innerHTML = `<span class="dot ok"></span><span>정상 운영 중 · 최신 조사일 <b>${esc(r.latest_date)}</b> · 마지막 수집 ${esc(when)}</span>`;
    $('#ver').textContent = `서비스 ${meta.service_version}`;
  }).catch(() => {
    $('#live').innerHTML = '<span class="dot bad"></span><span>지금 데이터 상태를 불러오지 못했어요</span>';
  });

  // ── 로그인 상태 ──────────────────────────────────────────────────────────
  document.querySelectorAll('[data-auth]').forEach(b =>
    b.addEventListener('click', () => window.nongsdaqAuth?.open(b.dataset.auth)));

  async function api(path, opts = {}){
    const r = await fetch('/api/keys' + path, {
      headers: {'Content-Type': 'application/json'}, credentials: 'same-origin', ...opts,
    });
    const body = await r.json().catch(() => ({}));
    if(!r.ok) throw new Error(body.detail || `요청이 실패했어요 (${r.status})`);
    return body;
  }

  window.nongsdaqAuth?.onChange(user => {
    const on = !!user;
    $('#keys-gate').hidden = on;
    $('#keys-panel').hidden = !on;
    $('#usage-gate').hidden = on;
    $('#usage-panel').hidden = !on;
    if(!on){
      issuedKey = null;
      $('#issued').hidden = true;
      paintSamples();
      return;
    }
    loadKeys();
    loadUsage();
  });

  // ── 키 ──────────────────────────────────────────────────────────────────
  const day = iso => iso ? new Date(iso).toLocaleDateString('ko-KR') : '—';
  const ago = iso => {
    if(!iso) return '아직 없음';
    const m = Math.round((Date.now() - new Date(iso)) / 60000);
    if(m < 1) return '방금';
    if(m < 60) return `${m}분 전`;
    if(m < 60 * 24) return `${Math.round(m / 60)}시간 전`;
    return day(iso);
  };

  function paintKeys(d){
    const body = $('#keys-body');
    if(!d.keys.length){
      body.innerHTML = '<tr class="none"><td colspan="5">아직 키가 없어요. 위에서 이름을 적고 발급해 보세요.</td></tr>';
    }else{
      body.innerHTML = d.keys.map(k => `
        <tr>
          <td><b>${esc(k.name)}</b></td>
          <td data-l="키"><code>${esc(k.prefix)}…</code></td>
          <td data-l="만든 날">${day(k.created_at)}</td>
          <td data-l="마지막 사용">${ago(k.last_used_at)}</td>
          <td class="act"><button class="btn small danger" type="button" data-revoke="${k.key_no}">폐기</button></td>
        </tr>`).join('');
    }
    const full = d.keys.length >= d.max_keys;
    $('#newkey-btn').disabled = full;
    $('#keyname').disabled = full;
    $('#keyname').placeholder = full ? `키는 ${d.max_keys}개까지예요 — 안 쓰는 키를 폐기해 주세요`
                                     : '키 이름 (예: 내 노트북, 가계부 앱)';
  }

  async function loadKeys(){
    try{ paintKeys(await api('')); }
    catch(e){ showMsg(e.message, true); }
  }

  function showMsg(text, err){
    const m = $('#keys-msg');
    m.textContent = text;
    m.className = 'msg' + (err ? ' err' : '');
  }

  $('#newkey').addEventListener('submit', async e => {
    e.preventDefault();
    const name = $('#keyname').value.trim();
    if(!name) return;
    $('#newkey-btn').disabled = true;
    try{
      const k = await api('', {method: 'POST', body: JSON.stringify({name})});
      issuedKey = k.key;
      $('#issued-key').textContent = k.key;
      $('#issued').hidden = false;
      $('#keyname').value = '';
      showMsg('');
      paintSamples();
      $('#keyhint').textContent = '방금 발급한 키를 예시에 넣어 두었어요. 그대로 복사해 실행해 보세요.';
      await loadKeys();
    }catch(err){
      showMsg(err.message, true);
      $('#newkey-btn').disabled = false;
    }
  });
  $('#issued-copy').addEventListener('click', e => copy($('#issued-key').textContent, e.target));

  // 폐기는 두 번 눌러야 한다 (되돌릴 수 없으므로). 브라우저 확인 창은 쓰지 않는다.
  $('#keys-body').addEventListener('click', async e => {
    const btn = e.target.closest('[data-revoke]');
    if(!btn) return;
    if(btn.dataset.armed !== '1'){
      btn.dataset.armed = '1';
      btn.textContent = '정말 폐기';
      setTimeout(() => { if(btn.isConnected){ btn.dataset.armed = ''; btn.textContent = '폐기'; } }, 4000);
      return;
    }
    btn.disabled = true;
    try{
      paintKeys(await api('/' + btn.dataset.revoke, {method: 'DELETE'}));
      showMsg('키를 폐기했어요. 그 키로는 이제 호출할 수 없어요.');
    }catch(err){
      showMsg(err.message, true);
      btn.disabled = false;
    }
  });

  // ── 사용량 ──────────────────────────────────────────────────────────────
  async function loadUsage(){
    let u;
    try{ u = await api('/usage?days=30'); }
    catch(e){ return; }
    const total = u.daily.reduce((s, d) => s + d.calls, 0);
    const errs = u.daily.reduce((s, d) => s + d.errors, 0);
    const msSum = u.daily.reduce((s, d) => s + (d.avg_ms ? d.avg_ms * d.calls : 0), 0);
    const lim = u.limits.per_day;
    $('#u-remain').innerHTML = `${fmt(u.today.remaining)}<small>/ ${fmt(lim)}</small>`;
    $('#u-meter').style.width = `${Math.min(100, u.today.calls / lim * 100)}%`;
    $('#u-total').textContent = fmt(total);
    $('#u-err').innerHTML = total ? `${(errs / total * 100).toFixed(1)}<small>%</small>` : '—';
    $('#u-ms').innerHTML = total ? `${fmt(Math.round(msSum / total))}<small>ms</small>` : '—';
    drawChart(u.daily);
    drawEndpoints(u.by_endpoint);
    $('#u-table').innerHTML = '<table><thead><tr><th>날짜</th><th>호출</th><th>오류</th><th>평균 ms</th></tr></thead><tbody>' +
      u.daily.slice().reverse().map(d =>
        `<tr><td>${d.date}</td><td>${fmt(d.calls)}</td><td>${fmt(d.errors)}</td><td>${d.avg_ms ?? '—'}</td></tr>`).join('') +
      '</tbody></table>';
  }

  function niceMax(v){
    if(v <= 5) return 5;
    const p = 10 ** Math.floor(Math.log10(v));
    for(const m of [1, 2, 2.5, 5, 10]) if(v <= m * p) return m * p;
    return 10 * p;
  }

  // 하루 호출 수 막대 — 계열이 하나라 범례 없이 제목이 이름을 대신한다. 값은 막대에 올리면 나온다.
  let lastDaily = null;
  // 폭이 바뀌면 다시 그린다 (viewBox 를 실제 폭으로 잡아 글자가 줄어들지 않게)
  new ResizeObserver(() => { if(lastDaily) drawChart(lastDaily); }).observe($('#u-chart'));

  function drawChart(daily){
    lastDaily = daily;
    const box = $('#u-chart');
    const W = Math.max(280, Math.round(box.clientWidth || 640));
    const H = W < 480 ? 180 : 220, L = 40, R = 8, T = 10, B = 26;
    const pw = W - L - R, ph = H - T - B;
    const max = niceMax(Math.max(1, ...daily.map(d => d.calls)));
    const band = pw / daily.length;
    const bw = Math.min(16, band - 2);           // 막대 사이 2px 이상 비운다
    const y = v => T + ph - v / max * ph;
    let s = `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="최근 30일 하루 호출 수 막대 그래프">`;
    for(let i = 0; i <= 4; i++){
      const v = max / 4 * i, yy = y(v);
      s += `<line class="${i ? 'gl' : 'base'}" x1="${L}" x2="${W - R}" y1="${yy}" y2="${yy}"/>`;
      s += `<text class="ax" x="${L - 6}" y="${yy + 4}" text-anchor="end">${fmt(Math.round(v))}</text>`;
    }
    daily.forEach((d, i) => {
      const cx = L + band * i + band / 2, x = cx - bw / 2;
      const top = y(d.calls), h = T + ph - top;
      // 위 끝만 4px 둥글게, 바닥은 반듯하게
      const r = Math.min(4, h, bw / 2);
      const bar = h > 0
        ? `<path class="bar" d="M${x},${T + ph} V${top + r} Q${x},${top} ${x + r},${top} H${x + bw - r} Q${x + bw},${top} ${x + bw},${top + r} V${T + ph} Z"/>`
        : '';
      s += `<rect class="hit" data-i="${i}" x="${L + band * i}" y="${T}" width="${band}" height="${ph}"/>${bar}`;
      const every = W < 480 ? 10 : 7;
      if((daily.length - 1 - i) % every === 0){
        s += `<text class="ax" x="${cx}" y="${H - 6}" text-anchor="middle">${d.date.slice(5).replace('-', '/')}</text>`;
      }
    });
    s += '</svg><div class="tip" hidden></div>';
    box.innerHTML = s;

    const svg = box.querySelector('svg'), tip = box.querySelector('.tip');
    svg.addEventListener('mousemove', e => {
      const hit = e.target.closest('.hit');
      box.querySelectorAll('.bar.on').forEach(b => b.classList.remove('on'));
      if(!hit){ tip.hidden = true; return; }
      const d = daily[+hit.dataset.i];
      hit.nextElementSibling?.classList?.add('on');
      const sr = svg.getBoundingClientRect(), br = box.getBoundingClientRect();
      const k = sr.width / W;
      tip.style.left = `${(L + band * (+hit.dataset.i + .5)) * k + sr.left - br.left}px`;
      tip.style.top = `${y(d.calls) * k + sr.top - br.top}px`;
      tip.innerHTML = `${d.date} · <b>${fmt(d.calls)}</b>회` +
        (d.errors ? ` · 오류 ${fmt(d.errors)}` : '') + (d.avg_ms != null ? ` · 평균 ${d.avg_ms}ms` : '');
      tip.hidden = false;
    });
    svg.addEventListener('mouseleave', () => {
      tip.hidden = true;
      box.querySelectorAll('.bar.on').forEach(b => b.classList.remove('on'));
    });
  }

  function drawEndpoints(rows){
    const box = $('#u-eps');
    if(!rows.length){
      box.innerHTML = '<p class="muted" style="margin:0;font-size:14px">아직 호출 기록이 없어요.</p>';
      return;
    }
    const max = Math.max(...rows.map(r => r.calls));
    box.innerHTML = rows.map(r => `
      <div class="ep"><code>${esc(r.endpoint)}</code><span class="n">${fmt(r.calls)}</span>
        <div class="track"><i style="width:${Math.max(2, r.calls / max * 100)}%"></i></div></div>`).join('');
  }

  // ── 엔드포인트 문서 ─────────────────────────────────────────────────────
  const MARKET = ['market', 'retail | wholesale', '소매 · 도매 (기본 retail)'];
  const ENDPOINTS = [
    {path: '/status', key: false, desc: '시장별 데이터 기간 · 품목 수 · 마지막 수집 시각. 키 없이 부를 수 있어요 — 서비스 상태 확인용.',
     params: [],
     example: {data: {retail: {earliest_date: '2025-09-01', latest_date: '2026-11-18', items: 100, rows: 67218,
       last_fetched_at: '2026-11-18T17:34:08'}, wholesale: {'…': '…'}}, meta: {api_version: 'v1', service_version: '2.2.0'}}},
    {path: '/items', key: true, desc: '다른 엔드포인트에 넣을 품목 · 품종 · 등급 코드. 등급마다 처음 · 마지막 조사일을 함께 줘요.',
     params: [MARKET, ['category', '100~600', '부류코드 (100 식량작물 · 200 채소류 · 300 특용작물 · 400 과실류 · 500 축산물 · 600 수산물)']],
     example: {data: [{item_code: '211', item_name: '배추', category_code: '200', category_name: '채소류',
       kinds: [{kind_code: '03', kind_name: '가을(1포기)', unit: '1포기',
         ranks: [{rank: '상품', first_date: '2025-11-06', last_date: '2026-11-18'}, {rank: '중품', '…': '…'}]}]}],
       meta: {market: 'retail', count: 100}}},
    {path: '/prices/latest', key: true, desc: '품종 · 등급마다 가장 최근 조사일의 가격. 최근 30일 안에 조사된 것만 줘요 (철 지난 품종이 오늘 가격처럼 보이지 않게).',
     params: [MARKET, ['item', '품목코드', '생략하면 전체'], ['kind', '품종코드', 'item 과 함께'], ['rank', '예: 상품', '등급'], ['category', '부류코드', '']],
     example: {data: [{survey_date: '2026-11-18', item_code: '211', item_name: '배추', kind_code: '03',
       kind_name: '가을(1포기)', rank: '상품', unit: '1포기', category_code: '200',
       price: 2390.0, price_1y_ago: 3380.0, price_normal: 3407.0}], meta: {market: 'retail', count: 1, latest_survey_date: '2026-11-18'}}},
    {path: '/prices/history', key: true, desc: '한 품종의 일별 가격. 조사가 없는 날(주말 · 공휴일 등)은 빠져요. 한 번에 최대 366일.',
     params: [['item', '필수', '품목코드'], ['kind', '필수', '품종코드'], ['rank', '예: 상품', '생략하면 모든 등급'],
       ['start', 'YYYY-MM-DD', '생략하면 end 90일 전'], ['end', 'YYYY-MM-DD', '생략하면 최신 조사일'], MARKET],
     example: {data: [{survey_date: '2026-10-28', item_code: '211', kind_code: '03', rank: '상품', price: 4648.0, '…': '…'}],
       meta: {market: 'retail', count: 16, start: '2026-10-01', end: '2026-11-18'}}},
    {path: '/changes', key: true, desc: '품목마다 대표 등급 하나의 등락률. 많이 오른 순이에요. 비교 날짜는 품목마다 다를 수 있어 prev_date 로 확인하세요.',
     params: [['period', '1d | 1w | 2w | 1m', '비교 기준 (기본 1d = 직전 조사일)'], MARKET],
     example: {data: [{item_code: '422', item_name: '방울토마토', kind_code: '01', rank: '상품', unit: '1kg',
       survey_date: '2026-11-18', price: 9136.0, prev_date: '2026-11-11', prev_price: 7115.0, change_pct: 28.4}],
       meta: {market: 'retail', count: 94, period: '1w'}}},
  ];
  $('#endpoints').innerHTML = ENDPOINTS.map(ep => `
    <div class="endpoint">
      <div class="sig"><span class="method">GET</span><code class="path">/api/v1${esc(ep.path)}</code>
        <span class="badge">${ep.key ? '키 필요' : '키 없이'}</span></div>
      <p>${esc(ep.desc)}</p>
      ${ep.params.length ? `<table class="params"><tbody>${ep.params.map(([n, t, d]) =>
        `<tr><td><code>${esc(n)}</code></td><td>${esc(t)}</td><td>${esc(d)}</td></tr>`).join('')}</tbody></table>` : ''}
      <details><summary>응답 예시</summary>
        <div class="code"><pre>${esc(JSON.stringify(ep.example, null, 2))}</pre></div></details>
    </div>`).join('');
})();
