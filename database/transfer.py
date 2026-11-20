r"""로컬 DB 에서 받아 둔 백필 데이터를 서버 DB 로 옮긴다 (KAMIS · 기상청을 서버에서 다시 부르지 않게).

  uv run python database/transfer.py export                  (로컬 → logs/transfer/*.csv.gz)
  uv run python database/transfer.py push --ssh AWS_HG        (파일을 서버로 보내 넣는다)
  uv run python database/transfer.py verify --ssh AWS_HG      (로컬 · 서버의 행 수와 내용 해시 비교)

  서버에 마이그레이션 003 · 004 가 적용된 뒤에만 쓴다 (v2.3.0 배포가 먼저).
  Git Bash 에서 돌린다 (docker compose · ssh 를 부른다). --ssh 는 ~/.ssh/config 의 호스트 이름이다.

무엇을 옮기나 (TABLES)
  · 가격 백필 행 (TBL_DAILY_PRICE 중 DATA_SOURCE='kamis_period') 과 백필 진행 기록
  · 관측소 · 날씨 · 물가 · 예보(원문 · 정리본) 전부
  매일 수집 기록(TBL_FETCH_LOG · TBL_INGEST_LOG)은 옮기지 않는다 — 서버는 서버 것을 쓴다.

지키는 규칙
  · 서버에 이미 있는 행은 덮어쓰지 않는다 (ON CONFLICT DO NOTHING). 서버가 그사이 직접 수집한 값이 이긴다.
  · 가격의 PRICE_NO(번호)는 옮기지 않는다 — 서버의 번호 규칙(IDENTITY)으로 새로 매긴다.
  · 표마다 한 트랜잭션이다. 중간에 실패하면 그 표는 통째로 되돌아간다. 몇 번을 다시 돌려도 결과는 같다.
"""

import argparse
import gzip
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "logs" / "transfer"

# 한글 출력이 cp949 로 깨지지 않게 (config.py 와 같은 처리 — 이 스크립트는 config 를 부르지 않는다)
for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")
REMOTE_DIR = "/srv/nongsdak"

# (표, 옮길 열, 조건, 충돌 키, 순서 키) — 충돌 키가 서버에 이미 있으면 그 행은 건너뛴다
PRICE_COLS = ("SURVEY_DATE, MARKET_TYPE, CATEGORY_NAME, CATEGORY_CODE, ITEM_CODE, ITEM_NAME, KIND_CODE, "
              "KIND_NAME, RANK_NAME, RANK_CODE, UNIT, PRICE_TODAY, PRICE_1D, PRICE_1W, PRICE_2W, PRICE_1M, "
              "PRICE_1Y, PRICE_NORMAL, PRICE_1D_DATE, PRICE_1W_DATE, PRICE_2W_DATE, DATA_SOURCE")
PRICE_KEY = "MARKET_TYPE, SURVEY_DATE, ITEM_CODE, KIND_CODE, RANK_NAME"
TABLES = [
    ("TBL_DAILY_PRICE", PRICE_COLS, "DATA_SOURCE = 'kamis_period'", PRICE_KEY, PRICE_KEY),
    ("TBL_BACKFILL_JOB", "*", None, "MARKET_TYPE, ITEM_CODE, KIND_CODE, RANK_CODE, CHUNK_START",
     "MARKET_TYPE, ITEM_CODE, KIND_CODE, RANK_CODE, CHUNK_START"),
    ("TBL_WEATHER_STATION", "*", None, "STN_ID", "STN_ID"),
    ("TBL_WEATHER_DAILY", "*", None, "OBS_DATE, STN_ID", "OBS_DATE, STN_ID"),
    ("TBL_CPI_MONTHLY", "*", None, "PERIOD, STAT_CODE, ITEM_CODE", "PERIOD, STAT_CODE, ITEM_CODE"),
    ("TBL_FCST_RAW", "*", None, "TM_FC, KIND, REG_ID", "TM_FC, KIND, REG_ID"),
    ("TBL_FCST_MID_TA", "*", None, "TM_FC, REG_ID, TARGET_DATE", "TM_FC, REG_ID, TARGET_DATE"),
    ("TBL_FCST_MID_LAND", "*", None, "TM_FC, REG_ID, TARGET_DATE", "TM_FC, REG_ID, TARGET_DATE"),
]


def _select(table, cols, where, order):
    return f"SELECT {cols} FROM {table}" + (f" WHERE {where}" if where else "") + f" ORDER BY {order}"


def _psql(args, remote=None, stdin=None, capture=True, gunzip=False):
    """db 컨테이너의 psql 을 부른다. remote 가 있으면 ssh 로 서버에서. 계정 · DB 이름은 컨테이너 안의 값.

    gunzip: stdin 이 gzip 이다. 서버로는 압축한 채로 보내고 서버에서 푼다 (전송량이 약 1/7).
    """
    inner = ['docker', 'compose', 'exec', '-T', 'db', 'sh', '-c',
             'exec psql -X -q -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" "$@"', 'psql', *args]
    if remote:
        quoted = " ".join("'" + a.replace("'", "'\\''") + "'" for a in inner)
        cmd = ["ssh", "-o", "BatchMode=yes", remote,
               f"cd {REMOTE_DIR} && " + ("gunzip -c | " if gunzip else "") + quoted]
    else:
        cmd = inner
        if gunzip:
            stdin = gzip.decompress(stdin)
    r = subprocess.run(cmd, input=stdin, capture_output=capture, cwd=ROOT)
    if r.returncode != 0:
        err = (r.stderr or b"").decode("utf-8", "replace")
        raise SystemExit(f"psql 실패 ({'서버' if remote else '로컬'}): {err.strip()[-800:]}")
    return r.stdout


def export():
    OUT.mkdir(parents=True, exist_ok=True)
    for table, cols, where, _key, order in TABLES:
        data = _psql(["-c", f"\\copy ({_select(table, cols, where, order)}) TO STDOUT WITH (FORMAT csv, HEADER)"])
        path = OUT / f"{table.lower()}.csv.gz"
        with gzip.open(path, "wb") as f:
            f.write(data)
        rows = max(data.count(b"\n") - 1, 0)
        print(f"  {table:<22} {rows:>9,}행 · {path.stat().st_size / 1e6:6.1f}MB")
    print(f"→ {OUT}")


def push(remote):
    for table, cols, _where, key, _order in TABLES:
        path = OUT / f"{table.lower()}.csv.gz"
        if not path.exists():
            raise SystemExit(f"{path} 가 없습니다. 먼저 export 를 돌리세요.")
        gz = path.read_bytes()
        rows = max(gzip.decompress(gz).count(b"\n") - 1, 0)
        col_list = cols if cols != "*" else None
        target = f"{table} ({col_list})" if col_list else table
        sel = col_list or "*"
        # 새로 들어간 행 수는 INSERT ... RETURNING 으로 직접 센다. 앞뒤 COUNT(*) 차이로 재면
        # 그사이 수집기가 넣은 행까지 섞인다.
        script = [
            "-At",
            "-c", "BEGIN",
            "-c", f"CREATE TEMP TABLE _t AS SELECT {sel} FROM {table} WITH NO DATA",
            "-c", "\\copy _t FROM STDIN WITH (FORMAT csv, HEADER)",
            "-c", (f"WITH ins AS (INSERT INTO {target} SELECT * FROM _t ON CONFLICT ({key}) DO NOTHING "
                   "RETURNING 1) SELECT COUNT(*) FROM ins"),
            "-c", "COMMIT",
        ]
        out = _psql(script, remote=remote, stdin=gz, gunzip=True).decode().split()
        inserted = int(out[-1]) if out and out[-1].isdigit() else -1
        print(f"  {table:<22} 보낸 {rows:>9,}행 · 새로 들어간 {inserted:>9,}행")
    print("완료. verify 로 비교하세요.")


def _digest(table, cols, where, order, remote):
    """옮긴 대상(조건에 맞는 행)의 행 수와 내용 해시. 순서를 고정해 같은 내용이면 같은 해시."""
    sql = (f"SELECT COUNT(*), md5(COALESCE(string_agg(t::text, '|' ORDER BY {order}), '')) "
           f"FROM ({_select(table, cols, where, order)}) t")
    out = _psql(["-At", "-F", " ", "-c", sql], remote=remote).decode().strip()
    n, h = out.split(" ")
    return int(n), h


def verify(remote):
    bad = 0
    for table, cols, where, _key, order in TABLES:
        ln, lh = _digest(table, cols, where, order, None)
        rn, rh = _digest(table, cols, where, order, remote)
        same = (ln, lh) == (rn, rh)
        note = "✅ 같음" if same else ("➕ 서버가 더 많음 (서버가 직접 수집한 행)" if rn > ln else "❌ 다름")
        bad += 0 if same or rn > ln else 1
        print(f"  {table:<22} 로컬 {ln:>9,} · 서버 {rn:>9,}  {note}")
    if bad:
        sys.exit(1)


def main(argv=None):
    p = argparse.ArgumentParser(prog="python database/transfer.py")
    p.add_argument("action", choices=["export", "push", "verify"])
    p.add_argument("--ssh", help="서버 ssh 호스트 (push · verify)")
    a = p.parse_args(sys.argv[1:] if argv is None else argv)
    if a.action != "export" and not a.ssh:
        p.error("push · verify 에는 --ssh 가 필요합니다")
    print(f"== {a.action} ==")
    {"export": export, "push": lambda: push(a.ssh), "verify": lambda: verify(a.ssh)}[a.action]()


if __name__ == "__main__":
    main()

