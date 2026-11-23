r"""운영 모델 학습 · 롤백 — 서버에서 매주 (.github/workflows/train.yml 이 collector 컨테이너 안에서 부른다).

  python -m collector.train                        소매 · 도매 학습 → 게이트 → 통과하면 배포 (current.json)
  python -m collector.train --market 도매
  python -m collector.train status                 시장마다 지금 쓰는 모델 · 이력
  python -m collector.train rollback --market 도매          이전 버전으로 되돌리기
  python -m collector.train rollback --market 도매 --to lgbm-wholesale-20261122-0300

학습 · 게이트 규칙은 ml/model.py. 결과는 TBL_MODEL_RUN(이력)과 TBL_INGEST_LOG(source 'train') 에 남는다.
시장을 하나씩 차례로 학습한다 — 서버 메모리(2GB)에서 한 번에 하나만 올라가게 (전체 기간 학습 최대 약 670MB).
새 모델은 다음 예측(매일 17:30, 또는 train.yml 의 '새 모델로 예측')부터 쓰인다.
"""

import argparse
import gc
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "backend"))
import config  # noqa: E402
from collector import ingest, loader  # noqa: E402
from ml import dataset, model  # noqa: E402

SOURCE = "train"
MARKETS = {"소매": ["소매"], "도매": ["도매"], "all": ["소매", "도매"]}

RECORD = """
    INSERT INTO TBL_MODEL_RUN (MODEL_VERSION, MARKET_TYPE, MODEL, TRAINED_AT, DATA_END, TRAIN_ROWS, HOLDOUT_START,
                               HOLDOUT_END, SCORE, BLEND_SCORE, CHAMPION_VERSION, CHAMPION_SCORE, PARITY_DIFF,
                               PASSED, REASON, DEPLOYED, META)
    VALUES (%(version)s, %(market)s, %(model)s, %(trained_at)s, %(data_end)s, %(train_rows)s, %(hs)s, %(he)s,
            %(score)s, %(blend)s, %(ch_version)s, %(ch_score)s, %(parity)s, %(passed)s, %(reason)s, %(passed)s,
            %(meta)s)
    ON CONFLICT (MODEL_VERSION) DO NOTHING
"""


def record(conn, meta):
    g = meta["gate"]
    with conn.transaction():
        conn.execute(RECORD, {
            "version": meta["version"], "market": meta["market"], "model": meta["model"],
            "trained_at": meta["trained_at"], "data_end": meta["data_end"], "train_rows": meta["train_rows"],
            "hs": g["holdout_start"], "he": g["holdout_end"], "score": round(g["score"], 4),
            "blend": round(g["blend_score"], 4),
            # 챔피언 — 배포된 모델이 없었거나 비교를 건너뛰었으면 NULL
            "ch_version": g.get("champion_version"),
            "ch_score": None if g.get("champion_score") is None else round(g["champion_score"], 4),
            "parity": g["parity_max_diff"], "passed": g["passed"],
            "reason": g["reason"][:200], "meta": json.dumps(meta, ensure_ascii=False),
        })


def train(markets, n_jobs):
    print(f"\n===== {config.now_kst():%Y-%m-%d %H:%M} 모델 학습 · {model.MODEL_NAME} · {model.model_dir()} =====")
    conn = loader.connect()
    conn.autocommit = True
    failed = 0
    try:
        for m in markets:
            try:
                series = dataset.load_series(m)
                # 소매 모델은 같은 품종의 도매 가격도 본다 (소매는 도매를 늦게 따라간다 — features.WHOLESALE)
                # (도매 자료가 없으면 None — 예전처럼 가격만)
                wholesale = (dataset.load_series("도매") or None) if m == "소매" else None
                meta = model.train_market(m, series, n_jobs=n_jobs, now=config.now_kst(), isolate=True,
                                          wholesale=wholesale)
                del series, wholesale
                gc.collect()
                record(conn, meta)
                g = meta["gate"]
                vs = (f" vs 챔피언 {g['champion_score']:.3f}" if g.get("champion_score") is not None else "")
                ingest.log(conn, SOURCE, f"{m} {meta['version']}", "OK", meta["train_rows"],
                           1 if g["passed"] else 0,
                           f"LightGBM {g['score']:.3f} vs blend {g['blend_score']:.3f}{vs} · {g['reason']}")
            except Exception as ex:
                failed += 1
                ingest.log(conn, SOURCE, f"{m} {model.MODEL_NAME}", "ERROR", message=f"{type(ex).__name__}: {ex}")
                print(f"  {m}: 오류 — {type(ex).__name__}: {ex}")
    finally:
        conn.close()
    status()
    return failed


def status():
    cur = model.read_current()
    print("\n── 지금 쓰는 모델 (current.json) ──")
    for m, en in model.MARKET_EN.items():
        c = cur.get(en) or {}
        print(f"  {m}: {c.get('current') or '없음 (blend 로 예측)'} · 이력 {len(c.get('history', []))}개")


def rollback(market, to):
    before, after = model.rollback(market, to)
    print(f"{market}: {before} → {after} (다음 예측부터 적용)")
    conn = loader.connect()
    conn.autocommit = True
    try:
        ingest.log(conn, SOURCE, f"{market} rollback", "OK", message=f"{before} → {after}")
    finally:
        conn.close()


def main(argv=None):
    p = argparse.ArgumentParser(prog="python -m collector.train", description="운영 모델 학습 · 게이트 · 롤백")
    p.add_argument("action", nargs="?", default="train", choices=["train", "status", "rollback"])
    p.add_argument("--market", choices=list(MARKETS), default="all")
    p.add_argument("--to", default=None, help="rollback: 되돌릴 버전 (생략하면 바로 이전)")
    p.add_argument("--n-jobs", type=int, default=2, help="LightGBM CPU 수 (서버 2개)")
    a = p.parse_args(sys.argv[1:] if argv is None else argv)

    if a.action == "status":
        status()
    elif a.action == "rollback":
        if a.market == "all":
            p.error("rollback 은 --market 소매 또는 --market 도매 를 정해 주세요")
        rollback(a.market, a.to)
    elif train(MARKETS[a.market], a.n_jobs):
        sys.exit(1)


if __name__ == "__main__":
    main()
