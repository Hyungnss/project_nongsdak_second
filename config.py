"""Oracle 접속 정보와 KAMIS 인증키를 한 곳에서 읽는다.

값을 찾는 순서
  1. 환경변수
  2. 프로젝트 최상위의 `.env` 파일
  3. 코드에 적힌 기본값 (Oracle 접속 정보만)

`.env` 를 함께 보는 이유는, Windows 에서 [Environment]::SetEnvironmentVariable 로 심은
값이 이미 떠 있는 프로세스에는 전달되지 않아 터미널을 다시 열어야 하기 때문이다.
파일로 두면 바로 읽힌다. 대신 이 파일은 절대 커밋하지 않는다 (.gitignore 에 있다).

KAMIS 인증키에는 기본값을 두지 않는다. 없는 채로 수집기를 돌리면 안 되기 때문이다.
다만 import 시점에 터뜨리지는 않는다 — webservice 는 여기서 Oracle 정보만 가져다 쓰는데,
인증키가 없다는 이유로 화면이 안 뜨면 곤란하다. 수집기가 require_kamis() 를 부르는
시점에 확인한다.
"""

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
ENV_FILE = BASE_DIR / ".env"

_file_values = None


def _from_env_file():
    """.env 를 한 번만 읽어 dict 로 들고 있는다. 파일이 없으면 빈 dict."""
    global _file_values
    if _file_values is not None:
        return _file_values

    _file_values = {}
    if not ENV_FILE.exists():
        return _file_values

    for line in ENV_FILE.read_text(encoding="utf-8-sig").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        val = val.strip()
        # 값을 따옴표로 감싼 경우를 벗겨 준다
        if len(val) >= 2 and val[0] == val[-1] and val[0] in "\"'":
            val = val[1:-1]
        _file_values[key.strip()] = val
    return _file_values


def get(name, default=None):
    """환경변수 -> .env -> 기본값 순으로 찾는다."""
    v = os.environ.get(name)
    if v:
        return v
    v = _from_env_file().get(name)
    if v:
        return v
    return default


# ── Oracle ────────────────────────────────────────────────────────────────
DB_USER = get("ORACLE_USER", "kdt_admin")
DB_PASSWORD = get("ORACLE_PASSWORD", "1234")
DB_DSN = {
    "host": get("ORACLE_HOST", "localhost"),
    "port": int(get("ORACLE_PORT", "1521")),
    "service_name": get("ORACLE_SERVICE", "xe"),
}
CLIENT_LIB_DIR = get(
    "ORACLE_CLIENT_DIR",
    r"C:\instantclient-basic-windows.x64-23.26.3.0.0\instantclient_23_26",
)

# ── KAMIS OpenAPI ─────────────────────────────────────────────────────────
KAMIS_CERT_KEY = get("KAMIS_CERT_KEY")
KAMIS_CERT_ID = get("KAMIS_CERT_ID")

# 품종명 끝에 `(단위)` 를 어떻게 붙일지.
#   append_unit_except_livestock : 축산물(500)만 빼고 붙인다. 이미 붙어 있으면 두 번 안 붙인다.
#   verbatim                     : API 가 준 그대로 쓴다.
# 기존 43,480행 조사 결과 100·200·300·400·600 은 100% 붙어 있고 500 은 0% 다 (예외 0건).
# 어느 쪽이 API 에서 온 것인지는 실제 응답을 봐야 알 수 있어 갈아끼울 수 있게 둔다.
KAMIS_KIND_NAME_MODE = get("KAMIS_KIND_NAME_MODE", "append_unit_except_livestock")


def require_kamis():
    """인증키를 돌려준다. 없으면 무엇을 어떻게 채워야 하는지 알려주고 멈춘다."""
    if KAMIS_CERT_KEY and KAMIS_CERT_ID:
        return KAMIS_CERT_KEY, KAMIS_CERT_ID
    raise SystemExit(
        "KAMIS 인증키가 없습니다.\n"
        f"  {ENV_FILE} 를 만들고 아래 두 줄을 채워 주세요.\n\n"
        "    KAMIS_CERT_KEY=발급받은키\n"
        "    KAMIS_CERT_ID=신청할때쓴아이디\n"
    )
