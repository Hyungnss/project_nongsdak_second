r"""LightGBM 튜닝 — 설정 여러 개를 '검증 기간' 에서 비교하고, 고른 설정만 '시험 기간' 에서 한 번 채점한다.

  uv run --group ml python -m ml.tune --round 1                       (도매 · 소매, 1차 후보 전부)
  uv run --group ml python -m ml.tune --round 1 --market 도매 --configs base,leaves31
  uv run --group ml python -m ml.tune --period test --configs base,<고른 설정>     (마지막 채점 — 한 번만)

기간 (ml.run 의 기본 평가 기간 = '시험' 과 겹치지 않게)
  시험  : 최신 조사일 - 35일 에서 2년      ← 지금까지 결과를 낸 기간. 설정을 고르는 데 쓰지 않는다
  검증  : 시험 시작 전 2년                  ← 여기서만 비교하고 고른다
시험 기간 성적을 보며 고르면 '그 기간에만 잘 맞는' 설정이 뽑혀 실력이 부풀려진다.

고르는 기준: 1 · 2 · 4주 MASE 중앙값의 평균 (score). MAPE · DIR 이 나빠지지 않는지도 같이 본다.
결과: MLflow 실험 price-tuning-<market> (run 하나 = 설정 하나) · ml_runs/tune/<period>_r<round>_<market>.csv
"""

import argparse
import os
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from ml import backtest, dataset  # noqa: E402

RUNS = ROOT / "ml_runs"
# 이 PC(메모리 7.7GB)에서 다른 일과 같이 돌아도 버티게 CPU 를 절반만 쓴다 — 결과는 같고 조금 느릴 뿐.
BASE = {**backtest.LGBM_PARAMS, "n_jobs": 6}
CACHE = RUNS / "cache"


def load_series(market, refresh=False):
    """시계열을 파일(ml_runs/cache)에서 읽는다. 없거나 refresh 면 DB 에서 읽어 저장한다.

    튜닝은 같은 자료로 여러 번 돌리므로, 한 번 저장해 두면 DB(Docker)를 꺼 둔 채 돌릴 수 있다 — 메모리가 빠듯한 PC 용.
    """
    import pickle  # noqa: PLC0415

    path = CACHE / f"series_{'retail' if market == '소매' else 'wholesale'}.pkl"
    if path.exists() and not refresh:
        with path.open("rb") as f:
            return pickle.load(f)  # noqa: S301 — 이 스크립트가 직접 만든 파일만 읽는다
    series = dataset.load_series(market)
    CACHE.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as f:
        pickle.dump(series, f)
    return series


def external_query(refresh=False):
    """외부 특성(날씨 · 물가)용 DB 조회를 파일(ml_runs/cache/external.pkl)로 — B · D 를 DB 없이 돌리려고.

    처음(또는 refresh)엔 DB 에서 읽으며 SQL 마다 결과를 저장하고, 그 뒤엔 같은 SQL 에 저장한 결과를 돌려준다.
    """
    import pickle  # noqa: PLC0415

    from ml import external  # noqa: PLC0415

    path = CACHE / "external.pkl"
    if path.exists() and not refresh:
        with path.open("rb") as f:
            saved = pickle.load(f)  # noqa: S301 — 이 스크립트가 직접 만든 파일만 읽는다
        return lambda sql: saved[sql]
    db, saved = external.db_query(), {}

    def record(sql):
        saved[sql] = db(sql)
        return saved[sql]

    external.load_weather(record)
    external.load_weather_by_sido(record)
    external.load_cpi(record)
    CACHE.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as f:
        pickle.dump(saved, f)
    return record


# 입력 조합 — A(가격만)이 기본. B · D 는 '튜닝하면 날씨도 효과가 있나' 확인용 (ml/external.py)
MODELS = {"lgbm": "A", "lgbm_ext": "B", "lgbm_region": "D"}


# 1차: 지금 값(base)에서 한 번에 하나씩만 바꾼다 — 무엇이 효과 있는지 따로 보인다.
ROUND1 = {
    "base":      {},
    "leaves15":  {"num_leaves": 15},
    "leaves31":  {"num_leaves": 31},
    "leaves127": {"num_leaves": 127},
    "mcs50":     {"min_child_samples": 50},
    "mcs300":    {"min_child_samples": 300},
    "mcs1000":   {"min_child_samples": 1000},
    "slow":      {"learning_rate": 0.02, "n_estimators": 1000},
    # 목표가 log(목표가/기준가) 라 값이 작다 (주로 ±0.1 안). alpha 는 '이보다 크면 l1 처럼' 의 경계.
    "huber":     {"objective": "huber", "alpha": 0.1},
}
# 2차: 1차에서 두 시장 모두 좋아진 설정이 없어 '조합' 대신 1차에서 안 건드린 설정을 본다 (역시 하나씩).
ROUND2 = {
    # 나무마다 특성(16개) 중 몇 %만 무작위로 골라 쓰나 (기본 80%). 적으면 특성 하나에 덜 기댄다
    "ff60":   {"feature_fraction": 0.6},
    "ff100":  {"feature_fraction": 1.0},
    # 나무마다 표본 80%만 무작위로 골라 학습 (기본). 끄면 모든 표본으로
    "nobag":  {"bagging_fraction": 1.0, "bagging_freq": 0},
    # 잎의 답(변화율)이 너무 커지지 않게 누르는 규제 (기본 0). 클수록 보수적
    "l2_1":   {"lambda_l2": 1.0},
    "l2_10":  {"lambda_l2": 10.0},
    # slow(0.02 × 1000) 를 한 번 더 — 도매에서만 효과가 있었다
    "slower": {"learning_rate": 0.01, "n_estimators": 2000},
}
ROUNDS = {1: ROUND1, 2: ROUND2}


def periods(series):
    latest = max(s.dates[-1] for s in series)
    test_end = np.datetime64(latest - np.timedelta64(35, "D"), "D")
    test_start = test_end - np.timedelta64(730, "D")
    valid_end = test_start - np.timedelta64(1, "D")
    return {"valid": (valid_end - np.timedelta64(730, "D"), valid_end), "test": (test_start, test_end)}


def score(table, model):
    """1 · 2 · 4주 MASE 중앙값의 평균 — 낮을수록 좋다."""
    return float(table[table.model == model].MASE_median.mean())


def summarize(table, name, model="lgbm"):
    t = table[table.model == model].set_index("h")
    row = {"config": name, "score": score(table, model)}
    for h in t.index:
        row[f"MASE_h{h}"] = t.loc[h, "MASE_median"]
        row[f"MAPE_h{h}"] = t.loc[h, "MAPE"] * 100
        row[f"DIR_h{h}"] = t.loc[h, "DIR"] * 100
    return row


def mlflow_setup(market):
    os.environ.setdefault("MLFLOW_DISABLE_AGENT_HINT", "1")
    import mlflow  # noqa: PLC0415

    RUNS.mkdir(exist_ok=True)
    mlflow.set_tracking_uri(f"sqlite:///{(RUNS / 'mlflow.db').as_posix()}")
    name = f"price-tuning-{'retail' if market == '소매' else 'wholesale'}"
    if mlflow.get_experiment_by_name(name) is None:
        mlflow.create_experiment(name, artifact_location=(RUNS / "artifacts" / name).resolve().as_uri())
    mlflow.set_experiment(name)
    return mlflow


def run_market(market, configs, period, rnd, note, use_mlflow, model="lgbm", log=print):
    series = load_series(market)
    start, end = periods(series)[period]
    if model != "lgbm":
        from ml import external  # noqa: PLC0415

        q = external_query()
        external.db_query = lambda: q          # backtest 가 부르는 DB 조회를 파일로 바꿔 끼운다
    log(f"\n===== {market} · {period} {start} ~ {end} · {MODELS[model]}({model}) · 설정 {len(configs)}개 =====")
    scale = backtest.scales(series, start)

    # 비교 기준: blend (학습 없음 — 한 번만)
    ref = backtest.metrics(backtest.run(series, start, end, ["blend"], log=lambda *_: None), scale, ["blend"])
    rows = [{"config": "(blend)", "score": score(ref, "blend"),
             **{f"MASE_h{r.h}": r.MASE_median for r in ref.itertuples()},
             **{f"MAPE_h{r.h}": r.MAPE * 100 for r in ref.itertuples()},
             **{f"DIR_h{r.h}": r.DIR * 100 for r in ref.itertuples()}}]
    log(f"  (blend)    score {rows[0]['score']:.3f}")

    mlflow = mlflow_setup(market) if use_mlflow else None
    for name, change in configs.items():
        params = {**BASE, **change}
        t = time.time()
        samples = backtest.run(series, start, end, [model], lgbm_params=params, log=lambda *_: None)
        table = backtest.metrics(samples, scale, [model])
        row = summarize(table, name, model)
        row["seconds"] = round(time.time() - t)
        rows.append(row)
        log(f"  {name:<10} score {row['score']:.3f} · "
            + " · ".join(f"{h // 7}주 {row[f'MASE_h{h}']:.3f}" for h in dataset.HORIZONS)
            + f" · {row['seconds']}s")
        if mlflow:
            tag = "" if model == "lgbm" else f"{MODELS[model]}:"
            with mlflow.start_run(run_name=f"{tag}r{rnd}:{name}" if period == "valid" else f"{tag}test:{name}"):
                mlflow.set_tags({"market": market, "period": period, "round": rnd, "config": name,
                                 "model": model, "inputs": MODELS[model],
                                 "change": str(change) or "-", "note": note})
                mlflow.log_params({"market": market, "period": period, "eval_start": str(start),
                                   "eval_end": str(end), **{f"lgbm_{k}": v for k, v in params.items()}})
                mlflow.log_metric("score", row["score"])
                mlflow.log_metric("blend_score", rows[0]["score"])
                for k, v in row.items():
                    if k.startswith(("MASE_", "MAPE_", "DIR_")) and np.isfinite(v):
                        mlflow.log_metric(k, float(v))

    out = pd.DataFrame(rows)
    out["vs_base"] = out.score - out.loc[out.config == "base", "score"].squeeze() if "base" in configs else np.nan
    suffix = "" if model == "lgbm" else f"_{MODELS[model]}"
    path = RUNS / "tune" / f"{period}_r{rnd}_{'retail' if market == '소매' else 'wholesale'}{suffix}.csv"
    path.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(path, index=False)
    log(f"\n── {market} {period} 결과 (score = 1·2·4주 MASE 중앙값 평균, 낮을수록 좋음) ──")
    log(out.round(3).sort_values("score").to_string(index=False))
    log(f"→ {path}")
    return out


def parse_args(argv):
    p = argparse.ArgumentParser(prog="python -m ml.tune")
    p.add_argument("--round", type=int, default=1, choices=list(ROUNDS))
    p.add_argument("--market", default="all", choices=["all", "소매", "도매"])
    p.add_argument("--period", default="valid", choices=["valid", "test"])
    p.add_argument("--configs", default="", help="쉼표 목록 (기본: 그 차수의 전부)")
    p.add_argument("--model", default="lgbm", choices=list(MODELS),
                   help="입력 조합 — lgbm=A(가격만) · lgbm_ext=B · lgbm_region=D")
    p.add_argument("--note", default="")
    p.add_argument("--n-jobs", type=int, default=None, help="LightGBM CPU 수 (기본 6)")
    p.add_argument("--no-mlflow", action="store_true")
    p.add_argument("--cache-only", action="store_true", help="DB 에서 시계열만 읽어 ml_runs/cache 에 저장하고 끝")
    return p.parse_args(argv)


def main(argv=None):
    a = parse_args(sys.argv[1:] if argv is None else argv)
    if a.n_jobs:
        BASE["n_jobs"] = a.n_jobs
    pool = {k: v for r in ROUNDS.values() for k, v in r.items()}
    configs = ({k: pool[k] for k in a.configs.split(",") if k} if a.configs else ROUNDS[a.round])
    markets = ["도매", "소매"] if a.market == "all" else [a.market]
    if a.cache_only:
        for m in markets:
            print(f"{m}: 품종 {len(load_series(m, refresh=True))}개 → {CACHE}")
        external_query(refresh=True)
        print(f"외부 특성(날씨 · 물가) → {CACHE / 'external.pkl'}")
        return
    t0 = time.time()
    for m in markets:
        run_market(m, configs, a.period, a.round, a.note, not a.no_mlflow, a.model)
    print(f"\n전체 걸린 시간 {(time.time() - t0) / 60:.1f}분")


if __name__ == "__main__":
    main()
