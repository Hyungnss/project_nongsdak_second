"""특성 데이터 수집기(weather · cpi · forecast) 공용 — HTTP 다시 시도 · 수집 기록 · 숫자 해석 · 비밀 가리기."""

import time

import requests

import config

RETRIES = 3


def get_json(url, params=None, timeout=60, retries=RETRIES):
    """GET → JSON. 네트워크 오류 · JSON 아님은 몇 번 다시 시도한다 (5초, 10초 ... 쉬고)."""
    last = None
    for attempt in range(retries):
        try:
            r = requests.get(url, params=params, timeout=timeout)
            r.raise_for_status()
            return r.json()
        except (requests.RequestException, ValueError) as e:
            last = e
            if attempt < retries - 1:
                time.sleep(5 * (attempt + 1))
    raise RuntimeError(f"{retries}번 시도했지만 실패: {type(last).__name__}: {hide(str(last))}")


def hide(text):
    """오류 문구에 들어간 인증키를 가린다 (ECOS 는 키가 주소 안에 있다)."""
    for name in ("DATA_GO_KR_KEY", "ECOS_KEY"):
        v = config.get(name)
        if v:
            text = text.replace(v, "***")
    return text


def num(v, empty=None):
    """'12.3' → 12.3. 빈 값 · 공백 · '-' 는 empty (기본 None)."""
    s = str(v if v is not None else "").strip()
    if s in ("", "-", "null", "None"):
        return empty
    try:
        return float(s)
    except ValueError:
        return empty


def log(conn, source, target, status, fetched=0, upserted=0, message=None):
    with conn.transaction():
        conn.execute("""INSERT INTO TBL_INGEST_LOG (SOURCE, TARGET, STATUS, ROWS_FETCHED, ROWS_UPSERTED, MESSAGE)
                        VALUES (%s, %s, %s, %s, %s, %s)""",
                     (source, target[:100], status, fetched, upserted, hide(message or "")[:500] or None))


def require(name):
    v = config.get(name)
    if not v:
        raise SystemExit(f"{name} 가 없습니다. .env 에 넣어 주세요 (SETUP.md 참고).")
    return v
