r"""매일 예측 — 가격 수집 뒤 품종 · 등급마다 1 · 2 · 4주 뒤 가격을 예측해 TBL_PRICE_FORECAST 에 넣는다.

  uv run python -m collector.predict                (소매 · 도매)
  uv run python -m collector.predict --market 소매

스케줄러가 매일 17:30 가격 수집 → 점검 뒤에 부른다 (collector/scheduler.py 의 price 작업).
같은 기준일 · 품종 · 기간 · 모델은 한 줄이다 — 다시 돌리면 덮어쓴다 (같은 날 정정된 가격으로 다시 예측).
모델은 ml/predict.py 의 MODEL (지금은 blend).
"""

import argparse
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "backend"))
import config  # noqa: E402
import db  # noqa: E402  (backend/db.py — 조회 함수)
from collector import ingest, loader  # noqa: E402
from ml import predict  # noqa: E402

SOURCE = "predict"
MARKETS = {"소매": "소매", "도매": "도매", "all": None}

UPSERT = """
    INSERT INTO TBL_PRICE_FORECAST (BASE_DATE, MARKET_TYPE, ITEM_CODE, KIND_CODE, RANK_NAME, H, TARGET_DATE,
                                    BASE_PRICE, PRICE, MODEL, MODEL_VERSION, FALLBACK)
    VALUES (%(base_date)s, %(market)s, %(item_code)s, %(kind_code)s, %(rank_name)s, %(h)s, %(target_date)s,
            %(base_price)s, %(price)s, %(model)s, %(model_version)s, %(fallback)s)
    ON CONFLICT (BASE_DATE, MARKET_TYPE, ITEM_CODE, KIND_CODE, RANK_NAME, H, MODEL) DO UPDATE SET
        TARGET_DATE = EXCLUDED.TARGET_DATE, BASE_PRICE = EXCLUDED.BASE_PRICE, PRICE = EXCLUDED.PRICE,
        MODEL_VERSION = EXCLUDED.MODEL_VERSION, FALLBACK = EXCLUDED.FALLBACK, CREATED_AT = now()
"""


def save(conn, forecasts):
    with conn.transaction(), conn.cursor() as cur:
        for f in forecasts:
            cur.execute(UPSERT, {
                "base_date": str(f.base_date), "market": f.market, "item_code": f.item_code,
                "kind_code": f.kind_code, "rank_name": f.rank_name, "h": f.h, "target_date": str(f.target_date),
                "base_price": f.base_price, "price": f.price, "model": predict.MODEL,
                "model_version": predict.MODEL_VERSION, "fallback": f.fallback,
            })
    return len(forecasts)


def main(argv=None):
    p = argparse.ArgumentParser(prog="python -m collector.predict", description="매일 가격 예측")
    p.add_argument("--market", choices=list(MARKETS), default="all")
    a = p.parse_args(sys.argv[1:] if argv is None else argv)
    markets = [MARKETS[a.market]] if MARKETS[a.market] else ["소매", "도매"]

    print(f"\n===== {config.now_kst():%Y-%m-%d %H:%M} 가격 예측 · 모델 {predict.MODEL_VERSION} =====")
    conn = loader.connect()
    conn.autocommit = True
    errors = 0
    try:
        for m in markets:
            t = time.time()
            try:
                fc = predict.forecast_market(db._query, m)
                n = save(conn, fc)
                series = len({(f.item_code, f.kind_code, f.rank_name) for f in fc})
                fb = sum(f.fallback for f in fc)
                base = max((str(f.base_date) for f in fc), default="-")
                ingest.log(conn, SOURCE, f"{m} {predict.MODEL_VERSION} {base}", "OK" if fc else "NO_DATA", n, n,
                           f"품종 {series} · naive 로 메움 {fb}")
                print(f"  {m}: 품종 {series}개 · 예측 {n}행 · naive 로 메움 {fb}행 · 최신 기준일 {base} · {time.time() - t:.1f}s")
            except Exception as ex:
                errors += 1
                ingest.log(conn, SOURCE, f"{m} {predict.MODEL_VERSION}", "ERROR", message=f"{type(ex).__name__}: {ex}")
                print(f"  {m}: 오류 — {type(ex).__name__}: {ex}")
    finally:
        conn.close()
    if errors:
        sys.exit(1)


if __name__ == "__main__":
    main()
