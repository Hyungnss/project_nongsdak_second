// 내 장바구니.
//
// 메인 화면(장보기 브리핑)은 그대로 두고, 오른쪽 위 '장바구니' 버튼을 누르면 오른쪽에서
// 패널이 열린다. 버튼은 로그인한 사람에게만 보인다. 로그인 상태는 auth.js 의
// window.nongsdaqAuth 로 본다 (그래서 이 파일은 auth.js 다음에 불러야 한다).
//
// 다른 화면이 쓰는 창구
//   nongsdaqCart.open()                    장바구니 패널 열기 (로그인 안 했으면 로그인부터)
//   nongsdaqCart.add(item, kind, rank)     한 품목 담기 (상세 화면의 '장바구니에 담기')
//
// 가격은 소매 기준이다. 서버가 열 때마다 최신 소매가를 붙여 준다 (/api/cart).
(() => {
  const btn = document.getElementById('cartbtn');
  const auth = window.nongsdaqAuth;
  if(!btn || !auth) return;

  const esc = s => String(s).replace(/[&<>"]/g, c =>
    ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
  const num = n => Math.round(n).toLocaleString('ko-KR');
  const won = n => num(n) + '원';
  const signed = n => (n > 0 ? '+' : '') + n.toFixed(1) + '%';
  const dir = n => n == null || Math.abs(n) < 0.05 ? 'flat' : (n > 0 ? 'up' : 'down');
  // 조사 붙이기: josa('오이', '을', '를') -> '오이를', josa('배추', '은', '는') -> '배추는'.
  // 끝의 '(국산)' 같은 괄호는 건너뛰고 그 앞 글자의 받침을 본다.
  // 받침을 알 수 없는 글자(영문 등)는 '을(를)'처럼 둘 다 적는다.
  function josa(word, withB, withoutB){
    const w = String(word).replace(/\s*\([^)]*\)\s*$/, '').trim();
    const ch = w.slice(-1), c = ch.charCodeAt(0);
    let b = null;
    if(c >= 0xAC00 && c <= 0xD7A3) b = (c - 0xAC00) % 28 !== 0;
    else if(c >= 0x3131 && c <= 0x314E) b = true;           // ㄱ~ㅎ 자음 (기역 · 니은 … 모두 받침 있음)
    else if(/[0-9]/.test(ch)) b = '013678'.includes(ch);    // 영 일 삼 육 칠 팔
    return word + (b === null ? `${withB}(${withoutB})` : (b ? withB : withoutB));
  }

  // 평년 대비 이만큼 넘게 벌어져야 '사기 좋은 때 / 기다려 보기'라고 말한다 (첫 화면과 같은 기준)
  const VERDICT_PCT = 10;

  // 묶음 담기. 품목 이름 · 수량(조사 단위 개수). 그날 조사되지 않는 품목은 조용히 빠진다.
  const PRESETS = {
    '김장': [['배추', 10], ['무', 5], ['파', 2], ['깐마늘(국산)', 1], ['고춧가루', 1],
             ['새우젓', 1], ['멸치액젓', 1], ['생강', 1]],
    '아침 식탁': [['계란', 2], ['우유', 2], ['사과', 1], ['바나나', 1], ['토마토', 1]],
    '찌개거리': [['호박', 1], ['감자', 1], ['양파', 1], ['파', 1], ['느타리버섯', 1], ['붉은고추', 1]],
  };

  let cart = null;      // 서버가 준 장바구니 {count, items}
  let brief = null;     // 담을 수 있는 품목 (장보기 브리핑 · 소매)
  let busy = false;

  async function call(method, path = '', body){
    const r = await fetch('/api/cart' + path, {
      method,
      headers: body ? {'Content-Type': 'application/json'} : {},
      body: body ? JSON.stringify(body) : undefined,
    });
    const data = await r.json().catch(() => ({}));
    if(r.status === 401){
      // 세션이 만료됐다. 패널을 닫고 다시 로그인하게 한다.
      dlg.close();
      auth.open('login');
      throw new Error('로그인이 끝났어요. 다시 로그인해 주세요.');
    }
    if(!r.ok){
      const d = data.detail;
      throw new Error(typeof d === 'string' ? d : '요청을 처리하지 못했어요. 잠시 뒤 다시 해 주세요.');
    }
    return data;
  }

  // ── 오른쪽 위 버튼 ──────────────────────────────────────────────────
  const badge = btn.querySelector('.n');
  function paintBadge(){
    const n = cart ? cart.count : 0;
    badge.textContent = n;
    badge.hidden = !n;
    btn.setAttribute('aria-label', n ? `장바구니 ${n}가지 담김` : '장바구니');
    // 장바구니가 바뀔 때마다 알린다. 메인 화면 목록의 +/− 와 수량이 이걸 듣고 다시 그린다.
    window.dispatchEvent(new CustomEvent('nongsdaq-cart'));
  }

  // ── 패널 ────────────────────────────────────────────────────────────
  const dlg = document.createElement('dialog');
  dlg.className = 'cartdlg';
  dlg.setAttribute('aria-labelledby', 'cartTitle');
  dlg.innerHTML = `<div class="wrapc">
      <div class="hd">
        <div><h2 id="cartTitle">내 장바구니</h2><p id="cartWho"></p></div>
        <button class="x" type="button" data-close aria-label="장바구니 닫기">×</button>
      </div>
      <div class="bd" id="cartBody"></div>
    </div>`;
  document.body.appendChild(dlg);
  const body = dlg.querySelector('#cartBody');
  dlg.querySelector('[data-close]').addEventListener('click', () => dlg.close());
  // 패널 바깥(어두운 영역)을 누르면 닫는다
  dlg.addEventListener('click', e => { if(e.target === dlg) dlg.close(); });

  // 버튼은 로그인한 사람에게만 보인다. onChange 는 등록하자마자 한 번 불리므로 패널을 만든 뒤에 단다.
  auth.onChange(async user => {
    btn.hidden = !user;
    cart = null;
    paintBadge();
    if(!user){ if(dlg.open) dlg.close(); return; }
    try{ cart = await call('GET'); paintBadge(); }catch(e){}
  });
  btn.addEventListener('click', () => open());

  async function open(){
    const user = await auth.require();
    if(!user) return;
    dlg.querySelector('#cartWho').textContent = `${user.nickname}님 · 소매 가격 기준`;
    if(!dlg.open) dlg.showModal();
    body.innerHTML = '<div class="cempty">불러오는 중…</div>';
    try{
      const [c, b] = await Promise.all([
        call('GET'),
        brief ? Promise.resolve(null) : fetch('/api/briefing?market=retail').then(r => r.json()),
      ]);
      cart = c;
      if(b) brief = b.items;
      paintBadge();
      render();
    }catch(e){
      body.innerHTML = `<div class="cerr">${esc(e.message)}</div>`;
    }
  }

  // ── 계산 ────────────────────────────────────────────────────────────
  const vsNormal = i => i.normal && i.price ? (i.price / i.normal - 1) * 100 : null;
  // 지난주 가격은 KAMIS 가 함께 공표하는 1주일 전 가격에서 거꾸로 구한다
  const weekAgo = i => i.change_7d == null ? i.price : i.price / (1 + i.change_7d / 100);

  function advice(i){
    const v = vsNormal(i);
    if(v == null) return ['na', '평년 자료 없음'];
    if(v <= -VERDICT_PCT) return ['down', '사기 좋은 때'];
    if(v >= VERDICT_PCT) return ['up', '조금 기다려 보기'];
    return ['flat', '평소 가격'];
  }

  function render(){
    const items = cart.items.filter(i => i.price != null);
    const lost = cart.items.filter(i => i.price == null);
    if(!cart.items.length){
      body.innerHTML = `<div class="cbox cempty"><b>장바구니가 비어 있어요</b>
          아래에서 품목을 고르거나 묶음으로 한 번에 담아 보세요.<br>
          메인 화면의 품목 상세에서도 '장바구니에 담기'로 담을 수 있어요.</div>` + addBox();
      return;
    }

    const now = items.reduce((s, i) => s + i.price * i.qty, 0);
    const last = items.reduce((s, i) => s + weekAgo(i) * i.qty, 0);
    const nrm = items.reduce((s, i) => s + (i.normal ?? i.price) * i.qty, 0);
    const d = now - last;
    const top = Math.max(now, last, nrm) * 1.04 || 1;
    const bar = (lab, v, cls) => `<div class="cbar ${cls}"><span class="lab">${lab}</span>
      <span class="trk"><i style="width:${(v / top * 100).toFixed(1)}%"></i></span><span class="v">${won(v)}</span></div>`;

    const judged = items.filter(i => vsNormal(i) != null).sort((a, b) => vsNormal(a) - vsNormal(b));
    const best = judged[0], worst = judged[judged.length - 1];
    let tip = '';
    if(best && vsNormal(best) <= -VERDICT_PCT){
      tip += `<b class="g">${esc(josa(best.item_name, '은', '는'))}</b> 평년보다 ${Math.round(-vsNormal(best))}% 싸서 지금 사 두기 좋아요. `;
    }
    if(worst && worst !== best && vsNormal(worst) >= VERDICT_PCT){
      tip += `<b class="r">${esc(josa(worst.item_name, '은', '는'))}</b> 평년보다 ${Math.round(vsNormal(worst))}% 비싸요.`;
    }

    const date = items.map(i => i.date).filter(Boolean).sort().pop();
    body.innerHTML = `
      <section class="cbox csum" aria-label="합계">
        <div>
          <div class="lb">${date ? `${+date.slice(5, 7)}월 ${+date.slice(8)}일 조사 가격으로 계산` : '오늘 가격'}</div>
          <div class="big">${num(now)}<small>원</small></div>
          <div class="delta ${dir(d)}">${Math.abs(d) < 1 ? '지난주와 같아요'
            : `지난주보다 <b>${won(Math.abs(d))}</b> ${d > 0 ? '더 들어요' : '덜 들어요'}`}</div>
        </div>
        <div class="cbars" role="img" aria-label="지난주 ${won(last)}, 오늘 ${won(now)}, 평년 ${won(nrm)}">
          ${bar('지난주', last, '')}${bar('오늘', now, 'now')}${bar('평년', nrm, 'nrm')}
          <div class="cscale">막대는 0원부터 같은 비율이에요. 평년 자료가 없는 품목은 오늘 가격으로 계산해요.</div>
        </div>
      </section>
      ${tip ? `<div class="ctip">${tip}</div>` : ''}
      <section class="cbox">
        <h3>담은 품목 ${cart.items.length}가지</h3>
        <p class="sub">가격은 품목마다 조사 단위(1포기 · 1kg · 10개) 기준이고, 수량은 그 단위의 개수예요.</p>
        <div class="clist">${items.map(rowHtml).join('')}${lost.map(lostRow).join('')}</div>
      </section>
      ${addBox()}
      <div class="cfoot"><span>지난주 가격은 KAMIS가 함께 공표하는 1주일 전 가격이에요.</span>
        <button type="button" class="cbtn ghost" data-act="clear">장바구니 비우기</button></div>`;
  }

  function rowHtml(i){
    const [ac, at] = advice(i);
    const v = vsNormal(i);
    const md = i.date ? `${+i.date.slice(5, 7)}/${+i.date.slice(8)}` : '';
    const old = i.current ? '' : ` · <span class="old">${md} 마지막 조사 (지금 조사 안 함)</span>`;
    return `<div class="crow">
      <span class="nm">${esc(i.item_name)}<small>${esc(i.kind_name)} · ${esc(i.rank_name)} · ${esc(i.unit)}당 ${won(i.price)}${old}</small></span>
      <span class="tot">${won(i.price * i.qty)}<small class="${dir(i.change_7d)}">1주 ${i.change_7d == null ? '—' : signed(i.change_7d)}</small></span>
      <button type="button" class="rm" data-act="rm" data-no="${i.cart_no}" aria-label="${esc(i.item_name)} 빼기">×</button>
      <div class="line2">
        <span class="qty" role="group" aria-label="${esc(i.item_name)} 수량">
          <button type="button" data-act="qty" data-no="${i.cart_no}" data-q="${i.qty - 1}" ${i.qty <= 1 ? 'disabled' : ''} aria-label="하나 빼기">−</button>
          <output>${i.qty}</output>
          <button type="button" data-act="qty" data-no="${i.cart_no}" data-q="${i.qty + 1}" ${i.qty >= 99 ? 'disabled' : ''} aria-label="하나 더하기">+</button>
        </span>
        <span><span class="pill ${ac}">${at}</span> <span class="why">${v == null ? '' : '평년 대비 ' + signed(v)}</span></span>
      </div>
    </div>`;
  }

  // 품목 코드가 바뀌었거나 자료가 아예 없어진 줄. 지울 수 있게만 둔다.
  function lostRow(i){
    return `<div class="crow"><span class="nm">알 수 없는 품목<small>가격 자료를 찾지 못했어요. 빼고 다시 담아 주세요.</small></span>
      <span class="tot"></span>
      <button type="button" class="rm" data-act="rm" data-no="${i.cart_no}" aria-label="알 수 없는 품목 빼기">×</button></div>`;
  }

  function addBox(){
    if(!brief) return '';
    const inCart = new Set((cart ? cart.items : []).map(i => `${i.item_code}|${i.kind_code}|${i.rank_name}`));
    const opts = brief.filter(c => !inCart.has(`${c.item_code}|${c.kind_code}|${c.rank_name}`))
      .slice().sort((a, b) => a.item_name.localeCompare(b.item_name, 'ko'))
      .map(c => `<option value="${brief.indexOf(c)}">${esc(c.item_name)} · ${esc(c.kind_name)} · ${won(c.price)}</option>`)
      .join('');
    const presets = Object.entries(PRESETS).map(([name, list]) => {
      const n = list.filter(([nm]) => brief.some(c => c.item_name === nm)).length;
      return n ? `<button type="button" class="cbtn ghost" data-act="preset" data-name="${esc(name)}">${esc(name)}<small>${n}가지</small></button>` : '';
    }).join('');
    return `<section class="cbox">
        <h3>더 담기</h3>
        <div class="cadd"><label for="cartPick" style="position:absolute;left:-9999px">담을 품목</label>
          <select id="cartPick">${opts}</select>
          <button type="button" class="cbtn" data-act="add">담기</button></div>
        ${presets ? `<p class="sub" style="margin-top:14px">묶음으로 한 번에 담기</p><div class="cpresets">${presets}</div>` : ''}
        <p class="cerr" id="cartErr" role="alert"></p>
      </section>`;
  }

  // 쓰기는 한 번에 하나씩. 버튼을 연달아 눌러도 요청이 겹치지 않는다.
  async function act(fn){
    if(busy) return;
    busy = true;
    try{
      cart = await fn();
      paintBadge();
      render();
    }catch(e){
      const err = body.querySelector('#cartErr');
      if(err) err.textContent = e.message; else body.insertAdjacentHTML('afterbegin', `<div class="cerr">${esc(e.message)}</div>`);
    }finally{
      busy = false;
    }
  }

  body.addEventListener('click', e => {
    const b = e.target.closest('[data-act]');
    if(!b || b.disabled) return;
    const no = b.dataset.no;
    switch(b.dataset.act){
      case 'qty': return act(() => call('PATCH', '/' + no, {qty: +b.dataset.q}));
      case 'rm': return act(() => call('DELETE', '/' + no));
      case 'add': {
        const c = brief[+body.querySelector('#cartPick').value];
        if(c) act(() => call('POST', '', {item_code: c.item_code, kind_code: c.kind_code, rank_name: c.rank_name}));
        return;
      }
      case 'preset': {
        const items = PRESETS[b.dataset.name].map(([nm, qty]) => {
          const c = brief.find(x => x.item_name === nm);
          return c && {item_code: c.item_code, kind_code: c.kind_code, rank_name: c.rank_name, qty};
        }).filter(Boolean);
        return act(() => call('POST', '/bulk', {items}));
      }
      case 'clear': {
        // 확인 창(confirm) 대신 버튼을 한 번 더 누르게 한다
        if(b.dataset.armed){ return act(() => call('DELETE')); }
        b.dataset.armed = '1';
        b.textContent = '한 번 더 누르면 모두 빠져요';
        setTimeout(() => { if(b.isConnected){ delete b.dataset.armed; b.textContent = '장바구니 비우기'; } }, 4000);
        return;
      }
    }
  });

  // ── 다른 화면에서 담기 ──────────────────────────────────────────────
  const toast = document.createElement('div');
  toast.className = 'ctoast';
  toast.setAttribute('role', 'status');
  toast.hidden = true;
  document.body.appendChild(toast);
  let toastTimer = null;
  function say(msg, withOpen){
    toast.innerHTML = `<span>${esc(msg)}</span>` +
      (withOpen ? '<button type="button" data-open>장바구니 보기</button>' : '');
    toast.hidden = false;
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => { toast.hidden = true; }, 4000);
  }
  toast.addEventListener('click', e => {
    if(e.target.closest('[data-open]')){ toast.hidden = true; open(); }
  });

  // 담긴 줄 찾기. 등급을 주면 등급까지 맞춘다 (같은 품종의 다른 등급은 다른 줄이다).
  function lineOf(item, kind, rank){
    if(!cart) return null;
    return cart.items.find(i => i.item_code === item && i.kind_code === kind &&
                                (!rank || i.rank_name === rank)) || null;
  }

  async function add(item, kind, rank, name){
    const user = await auth.require();
    if(!user) return;
    try{
      cart = await call('POST', '', {item_code: item, kind_code: kind, rank_name: rank || null});
      paintBadge();
      if(dlg.open) render();
      const line = lineOf(item, kind, rank);
      say(`${josa(name || '품목', '을', '를')} 담았어요${line && line.qty > 1 ? ` · 지금 ${line.qty}개` : ''}`, true);
    }catch(e){
      say(e.message, false);
    }
  }

  window.nongsdaqCart = {open, add, lineOf, josa};
})();
