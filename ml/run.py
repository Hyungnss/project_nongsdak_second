r"""백테스트 실행 → 결과표 출력 · MLflow 기록.

  uv run --group ml python -m ml.run                                    (기준선 5종 + LightGBM)
  uv run --group ml python -m ml.run --models naive,seasonal_naive      (일부만)
  uv run --group ml python -m ml.run --eval-start 2024-12-01 --eval-end 2026-10-20
  uv run --group ml mlflow ui --backend-store-uri sqlite:///ml_runs/mlflow.db   (결과 보기)

평가 구간 끝은 '오늘 - 28일 - 여유' 쯤이어야 4주 뒤 정답까지 있다 (기본: 최신 조사일 - 35일).
"""

import argparse
import os
import sys
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from ml import backtest, dataset  # noqa: E402

RUNS = ROOT / "ml_runs"
ALL = ["naive", "seasonal_naive", "seasonal_adjusted", "moving_average", "seasonal_profile", "blend", "lgbm"]
BASELINE_SET = ALL[:-1]   # --models baselines


def parse_args(argv):
    p = argparse.ArgumentParser(prog="python -m ml.run")
    p.add_argument("--market", default="소매")
    p.add_argument("--models", default=",".join(ALL), help="쉼표 목록, 또는 baselines (기준선 6종)")
    p.add_argument("--eval-start", default=None, help="기본: 평가 끝 - 2년")
    p.add_argument("--eval-end", default=None, help="기본: 최신 조사일 - 35일")
    p.add_argument("--refit-days", type=int, default=28)
    p.add_argument("--no-mlflow", action="store_true")
    return p.parse_args(argv)


def main(argv=None):
    a = parse_args(sys.argv[1:] if argv is None else argv)
    models = BASELINE_SET if a.models == "baselines" else [m for m in a.models.split(",") if m]
    t0 = time.time()
    series = dataset.load_series(a.market)
    latest = max(s.dates[-1] for s in series)
    end = np.datetime64(a.eval_end or (latest - np.timedelta64(35, "D")), "D")
    start = np.datetime64(a.eval_start or (end - np.timedelta64(730, "D")), "D")
    first = min(s.dates[0] for s in series)
    print(f"{a.market} 품종 {len(series)}개 · 자료 {first} ~ {latest} · 평가 {start} ~ {end}")

    samples = backtest.run(series, start, end, models, refit_days=a.refit_days)
    scale = backtest.scales(series, start)
    table = backtest.metrics(samples, scale, models)
    by_cat = backtest.metrics(samples, scale, models, by=("h", "category_code"))
    best = (table[table.model != "naive"].groupby("model").MASE_mean.mean().idxmin()
            if len(models) > 1 else models[0])
    worst = backtest.worst_series(samples, scale, best)

    show = table.copy()
    for c in ("MAPE", "DIR", "fallback"):
        show[c] = (show[c] * 100).round(1)
    print("\n── 기간별 (MAPE · DIR · fallback 은 %) ──")
    print(show.round(3).to_string(index=False))
    print(f"\n── 가장 많이 틀린 품종 ({best}) ──")
    print(worst.round(3).to_string())
    print(f"\n걸린 시간 {time.time() - t0:.0f}s")

    if a.no_mlflow:
        return table
    os.environ.setdefault("MLFLOW_DISABLE_AGENT_HINT", "1")
    import mlflow  # noqa: PLC0415

    RUNS.mkdir(exist_ok=True)
    mlflow.set_tracking_uri(f"sqlite:///{(RUNS / 'mlflow.db').as_posix()}")
    # 결과 파일(artifact)도 ml_runs/ 안에 둔다. 지정하지 않으면 지금 폴더의 ./mlruns 에 생긴다.
    exp_name = f"price-baseline-{'retail' if a.market == '소매' else 'wholesale'}"
    if mlflow.get_experiment_by_name(exp_name) is None:
        mlflow.create_experiment(exp_name, artifact_location=(RUNS / "artifacts" / exp_name).resolve().as_uri())
    mlflow.set_experiment(exp_name)
    with mlflow.start_run(run_name=",".join(models)):
        mlflow.log_params({"market": a.market, "models": ",".join(models), "eval_start": str(start),
                           "eval_end": str(end), "refit_days": a.refit_days, "series": len(series),
                           "data_first": str(first), "data_latest": str(latest), "target": "daily",
                           "horizons": "7,14,28", "tolerance": dataset.TOLERANCE,
                           **{f"lgbm_{k}": v for k, v in backtest.LGBM_PARAMS.items()}})
        for r in table.itertuples():
            for m in ("MASE_mean", "MASE_median", "MAPE", "DIR"):
                v = getattr(r, m)
                if np.isfinite(v):
                    mlflow.log_metric(f"{r.model}.h{r.h}.{m}", float(v))
        out = RUNS / "last"
        out.mkdir(exist_ok=True)
        table.to_csv(out / "metrics.csv", index=False)
        by_cat.to_csv(out / "metrics_by_category.csv", index=False)
        worst.to_csv(out / f"worst_{best}.csv")
        samples.to_csv(out / "predictions.csv.gz", index=False)
        mlflow.log_artifacts(str(out))
    print(f"MLflow 기록 완료 → {RUNS / 'mlflow.db'}")
    return table


if __name__ == "__main__":
    main()
