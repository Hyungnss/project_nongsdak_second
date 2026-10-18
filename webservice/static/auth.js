// 로그인 · 회원가입 화면.
//
// 시세 화면은 로그인 없이 그대로 쓴다. 이 스크립트는 오른쪽 위 #authbox 에
// 로그인 버튼(또는 'OO님 · 로그아웃')을 그리고, 누르면 팝업을 띄운다.
//
// 장바구니 · 레시피 같은 기능은 window.nongsdaqAuth 로 로그인 상태를 본다.
//   nongsdaqAuth.user            현재 사용자 {user_no, login_id, nickname} 또는 null
//   nongsdaqAuth.onChange(fn)    로그인·로그아웃 때마다 fn(user) 호출 (등록 즉시 한 번 호출)
//   nongsdaqAuth.open('login')   로그인 팝업 열기 ('signup' 이면 회원가입)
//   await nongsdaqAuth.require() 로그인 안 했으면 팝업을 띄우고, 로그인하면 user 를 돌려준다
//                                (닫아 버리면 null)
(() => {
  const box = document.getElementById('authbox');
  if(!box) return;
  const esc = s => String(s).replace(/[&<>"]/g, c =>
    ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));

  let user = null;
  const listeners = [];
  let waiting = [];            // require() 로 로그인을 기다리는 쪽

  function setUser(u){
    user = u;
    paint();
    listeners.forEach(fn => { try{ fn(user); }catch(e){ console.error(e); } });
    if(u){ waiting.forEach(r => r(u)); waiting = []; }
  }

  async function post(path, body){
    const r = await fetch('/api/auth/' + path, {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(body || {}),
    });
    const data = await r.json().catch(() => ({}));
    if(!r.ok){
      // FastAPI 의 형식 오류(422)는 detail 이 배열이다
      const d = data.detail;
      throw new Error(typeof d === 'string' ? d : '입력값을 확인해 주세요');
    }
    return data;
  }

  // ── 오른쪽 위 버튼 ──────────────────────────────────────────────────
  function paint(){
    if(user){
      box.innerHTML =
        `<span class="who"><b>${esc(user.nickname)}</b>님</span>` +
        `<button class="authbtn" type="button" data-act="logout">로그아웃</button>`;
    }else{
      box.innerHTML =
        `<button class="authbtn" type="button" data-act="login">로그인</button>` +
        `<button class="authbtn primary" type="button" data-act="signup">회원가입</button>`;
    }
  }
  box.addEventListener('click', async e => {
    const act = e.target.closest('[data-act]')?.dataset.act;
    if(act === 'login' || act === 'signup') open(act);
    if(act === 'logout'){
      try{ await post('logout'); }catch(err){}
      setUser(null);
    }
  });

  // ── 팝업 ────────────────────────────────────────────────────────────
  const dlg = document.createElement('dialog');
  dlg.className = 'authdlg';
  dlg.innerHTML = `
    <form method="dialog" novalidate>
      <div class="hd">
        <h2 id="authTitle">로그인</h2>
        <button class="x" type="button" data-close aria-label="닫기">×</button>
      </div>
      <div class="switch" role="tablist">
        <button type="button" role="tab" data-mode="login">로그인</button>
        <button type="button" role="tab" data-mode="signup">회원가입</button>
      </div>
      <label>아이디
        <input name="login_id" autocomplete="username" maxlength="20" required>
        <span class="hint" data-signup>영문 소문자 · 숫자 · _ 4~20자</span>
      </label>
      <label>비밀번호
        <input name="password" type="password" maxlength="64" required>
        <span class="hint" data-signup>8~64자</span>
      </label>
      <label data-signup>비밀번호 확인
        <input name="password2" type="password" maxlength="64" autocomplete="new-password">
      </label>
      <label data-signup>닉네임
        <input name="nickname" maxlength="20" autocomplete="nickname">
        <span class="hint">화면에 보일 이름 · 2~20자</span>
      </label>
      <p class="err" role="alert"></p>
      <button class="submit" type="submit">로그인</button>
      <p class="note">시세는 로그인 없이 볼 수 있어요.<br>장바구니 · 레시피 저장에만 로그인이 필요해요.</p>
    </form>`;
  document.body.appendChild(dlg);

  const form = dlg.querySelector('form');
  const errEl = dlg.querySelector('.err');
  const submitBtn = dlg.querySelector('.submit');
  let mode = 'login';

  function setMode(m){
    mode = m;
    const signup = m === 'signup';
    dlg.querySelector('#authTitle').textContent = signup ? '회원가입' : '로그인';
    submitBtn.textContent = signup ? '가입하기' : '로그인';
    dlg.querySelectorAll('[data-signup]').forEach(el => el.hidden = !signup);
    dlg.querySelectorAll('.switch button').forEach(b => {
      const on = b.dataset.mode === m;
      b.classList.toggle('on', on);
      b.setAttribute('aria-selected', on);
    });
    form.password.autocomplete = signup ? 'new-password' : 'current-password';
    errEl.textContent = '';
  }

  function open(m){
    form.reset();
    setMode(m || 'login');
    if(!dlg.open) dlg.showModal();
    form.login_id.focus();
  }

  dlg.querySelector('.switch').addEventListener('click', e => {
    const m = e.target.closest('[data-mode]')?.dataset.mode;
    if(m){ setMode(m); form.login_id.focus(); }
  });
  dlg.querySelector('[data-close]').addEventListener('click', () => dlg.close());
  // 바깥(어두운 영역)을 누르면 닫는다
  dlg.addEventListener('click', e => { if(e.target === dlg) dlg.close(); });
  // 로그인하지 않고 닫으면 require() 로 기다리던 쪽에 null 을 돌려준다
  dlg.addEventListener('close', () => {
    if(!user){ waiting.forEach(r => r(null)); waiting = []; }
  });

  form.addEventListener('submit', async e => {
    e.preventDefault();
    const f = form.elements;
    const body = {login_id: f.login_id.value.trim(), password: f.password.value};
    if(!body.login_id || !body.password){
      errEl.textContent = '아이디와 비밀번호를 입력해 주세요';
      return;
    }
    if(mode === 'signup'){
      if(f.password.value !== f.password2.value){
        errEl.textContent = '비밀번호 확인이 일치하지 않아요';
        return;
      }
      body.nickname = f.nickname.value.trim();
    }
    submitBtn.disabled = true;
    errEl.textContent = '';
    try{
      const u = await post(mode, body);
      setUser(u);
      dlg.close();
    }catch(err){
      errEl.textContent = err.message;
    }finally{
      submitBtn.disabled = false;
    }
  });

  // ── 다른 기능이 쓰는 창구 ───────────────────────────────────────────
  window.nongsdaqAuth = {
    get user(){ return user; },
    onChange(fn){ listeners.push(fn); fn(user); },
    open,
    require(){
      if(user) return Promise.resolve(user);
      return new Promise(resolve => { waiting.push(resolve); open('login'); });
    },
  };

  paint();
  fetch('/api/auth/me').then(r => r.ok ? r.json() : {user: null})
    .then(d => setUser(d.user)).catch(() => {});
})();
