"""회원가입 · 로그인 · 로그아웃.

시세 API 는 로그인 없이 그대로 열려 있다. 로그인은 장바구니 · 레시피 정리처럼
'내 것'을 저장하는 기능에만 쓴다. 그런 API 는 아래 의존성 하나만 붙이면 된다.

    from fastapi import Depends
    import auth

    @app.get("/api/cart")
    def cart(user: dict = Depends(auth.require_user)):     # 로그인 안 했으면 401
        ... user["user_no"] 로 조회 ...

    @app.get("/api/something")
    def something(user: dict | None = Depends(auth.current_user)):   # 로그인 선택
        ...

설계 메모
  · 비밀번호는 표준 라이브러리 scrypt 로 해시한다. 새 패키지를 깔지 않아도 된다.
    해시 문자열에 파라미터를 같이 적어 두므로 나중에 강도를 올려도 예전 회원은 그대로 로그인된다.
  · 로그인 상태는 서버 세션(TBL_USER_SESSION) + HttpOnly 쿠키로 유지한다.
    서명 쿠키(JWT 등)와 달리 로그아웃하면 서버에서 바로 무효가 된다.
    DB 에는 토큰 원문이 아니라 SHA-256 만 둔다.
  · 쿠키는 SameSite=Lax 라 다른 사이트에서 보낸 POST 에는 실리지 않는다 (CSRF 방어).
"""

import hashlib
import hmac
import re
import secrets
from datetime import datetime, timedelta

import oracledb
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel

import db

router = APIRouter(prefix="/api/auth", tags=["auth"])

COOKIE_NAME = "nongsdaq_session"
SESSION_DAYS = 14

LOGIN_ID_RE = re.compile(r"^[a-z0-9_]{4,20}$")
PASSWORD_MIN, PASSWORD_MAX = 8, 64
NICKNAME_MIN, NICKNAME_MAX = 2, 20

# scrypt 강도. n=2^14, r=8 이면 한 번에 메모리 16MB · 수십 ms 정도라
# 로그인 한 번에는 부담이 없고, 유출된 해시를 대량으로 맞춰 보기는 어렵다.
SCRYPT_N, SCRYPT_R, SCRYPT_P = 2 ** 14, 8, 1


# ── 비밀번호 ──────────────────────────────────────────────────────────────
def hash_password(password):
    salt = secrets.token_bytes(16)
    h = hashlib.scrypt(password.encode(), salt=salt,
                       n=SCRYPT_N, r=SCRYPT_R, p=SCRYPT_P, dklen=32)
    return f"scrypt${SCRYPT_N}${SCRYPT_R}${SCRYPT_P}${salt.hex()}${h.hex()}"


def verify_password(password, stored):
    try:
        algo, n, r, p, salt, h = stored.split("$")
        if algo != "scrypt":
            return False
        calc = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt),
                              n=int(n), r=int(r), p=int(p), dklen=len(h) // 2)
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(calc.hex(), h)


# 없는 아이디로 로그인할 때도 해시를 한 번 계산한다.
# 바로 돌려주면 응답 속도 차이로 '그 아이디가 있는지'가 드러난다.
_DUMMY_HASH = hash_password(secrets.token_hex(8))


# ── DB ────────────────────────────────────────────────────────────────────
def _token_hash(token):
    return hashlib.sha256(token.encode()).hexdigest()


def _find_user_by_token(token):
    rows = db._query("""
        SELECT u.USER_NO, u.LOGIN_ID, u.NICKNAME
        FROM   TBL_USER_SESSION s
        JOIN   TBL_USER u ON u.USER_NO = s.USER_NO
        WHERE  s.TOKEN_HASH = :t AND s.EXPIRES_AT > SYSDATE
    """, {"t": _token_hash(token)})
    return rows[0] if rows else None


def _create_session(conn, user_no):
    """세션을 만들고 쿠키에 넣을 토큰 원문을 돌려준다. 커밋은 부르는 쪽에서 한다."""
    token = secrets.token_urlsafe(32)
    with conn.cursor() as cur:
        # 만료된 세션은 따로 청소 작업을 두지 않고 로그인할 때마다 같이 지운다
        cur.execute("DELETE FROM TBL_USER_SESSION WHERE EXPIRES_AT <= SYSDATE")
        cur.execute("""
            INSERT INTO TBL_USER_SESSION (TOKEN_HASH, USER_NO, EXPIRES_AT)
            VALUES (:t, :u, :exp)
        """, {"t": _token_hash(token), "u": user_no,
              "exp": datetime.now() + timedelta(days=SESSION_DAYS)})
    return token


def _set_cookie(request, response, token):
    response.set_cookie(
        COOKIE_NAME, token,
        max_age=SESSION_DAYS * 24 * 3600,
        httponly=True,                          # 자바스크립트로 못 읽게
        samesite="lax",
        secure=request.url.scheme == "https",   # 로컬(http)에서도 동작하도록
        path="/",
    )


def _public(u):
    return {"user_no": int(u["user_no"]), "login_id": u["login_id"],
            "nickname": u["nickname"]}


# ── 다른 API 가 붙여 쓰는 의존성 ──────────────────────────────────────────
def current_user(request: Request):
    """로그인했으면 {user_no, login_id, nickname}, 아니면 None."""
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        return None
    u = _find_user_by_token(token)
    return _public(u) if u else None


def require_user(user: dict | None = Depends(current_user)):
    """로그인이 꼭 필요한 API 용. 안 했으면 401."""
    if user is None:
        raise HTTPException(401, "로그인이 필요합니다")
    return user


# ── API ───────────────────────────────────────────────────────────────────
class SignupIn(BaseModel):
    login_id: str
    password: str
    nickname: str


class LoginIn(BaseModel):
    login_id: str
    password: str


@router.post("/signup")
def signup(body: SignupIn, request: Request, response: Response):
    """가입하고 바로 로그인 상태로 만든다."""
    login_id = body.login_id.strip().lower()
    nickname = body.nickname.strip()
    if not LOGIN_ID_RE.match(login_id):
        raise HTTPException(400, "아이디는 영문 소문자·숫자·_ 로 4~20자여야 합니다")
    if not PASSWORD_MIN <= len(body.password) <= PASSWORD_MAX:
        raise HTTPException(400, f"비밀번호는 {PASSWORD_MIN}~{PASSWORD_MAX}자여야 합니다")
    if not NICKNAME_MIN <= len(nickname) <= NICKNAME_MAX:
        raise HTTPException(400, f"닉네임은 {NICKNAME_MIN}~{NICKNAME_MAX}자여야 합니다")

    pw_hash = hash_password(body.password)
    with db._init_pool().acquire() as conn:
        try:
            with conn.cursor() as cur:
                user_no = cur.var(oracledb.NUMBER)
                cur.execute("""
                    INSERT INTO TBL_USER (USER_NO, LOGIN_ID, PASSWORD_HASH, NICKNAME, LAST_LOGIN_AT)
                    VALUES (SEQ_USER.NEXTVAL, :id, :pw, :nick, SYSDATE)
                    RETURNING USER_NO INTO :no
                """, {"id": login_id, "pw": pw_hash, "nick": nickname, "no": user_no})
                user_no = int(user_no.getvalue()[0])
        except oracledb.IntegrityError:
            # 중복 확인을 먼저 SELECT 로 하면 동시에 가입할 때 둘 다 통과한다.
            # 유니크 제약에 맡기고 여기서 받는다.
            raise HTTPException(409, "이미 사용 중인 아이디입니다")
        token = _create_session(conn, user_no)
        conn.commit()

    _set_cookie(request, response, token)
    return {"user_no": user_no, "login_id": login_id, "nickname": nickname}


@router.post("/login")
def login(body: LoginIn, request: Request, response: Response):
    login_id = body.login_id.strip().lower()
    rows = db._query("""
        SELECT USER_NO, LOGIN_ID, NICKNAME, PASSWORD_HASH
        FROM   TBL_USER WHERE LOGIN_ID = :id
    """, {"id": login_id})
    u = rows[0] if rows else None
    ok = verify_password(body.password, u["password_hash"] if u else _DUMMY_HASH)
    if not (u and ok):
        # 아이디가 틀렸는지 비밀번호가 틀렸는지는 알려주지 않는다
        raise HTTPException(401, "아이디 또는 비밀번호가 올바르지 않습니다")

    with db._init_pool().acquire() as conn:
        token = _create_session(conn, u["user_no"])
        with conn.cursor() as cur:
            cur.execute("UPDATE TBL_USER SET LAST_LOGIN_AT = SYSDATE WHERE USER_NO = :u",
                        {"u": u["user_no"]})
        conn.commit()

    _set_cookie(request, response, token)
    return _public(u)


@router.post("/logout")
def logout(request: Request, response: Response):
    token = request.cookies.get(COOKIE_NAME)
    if token:
        with db._init_pool().acquire() as conn, conn.cursor() as cur:
            cur.execute("DELETE FROM TBL_USER_SESSION WHERE TOKEN_HASH = :t",
                        {"t": _token_hash(token)})
            conn.commit()
    response.delete_cookie(COOKIE_NAME, path="/")
    return {"ok": True}


@router.get("/me")
def me(user: dict | None = Depends(current_user)):
    """화면이 처음 뜰 때 로그인 상태를 묻는다. 로그인 안 했으면 user 가 null."""
    return {"user": user}
