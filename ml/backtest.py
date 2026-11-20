"""시간 순서를 지키는 백테스트 (rolling origin) · 지표.

평가 구간의 모든 조사일이 기준일이다. 학습이 필요한 것(계절 프로파일 · LightGBM)은 refit_days(기본 28)마다
다시 만들고, 그때까지 '목표일까지 이미 지난' 표본으로만 학습한다 — 아직 정답을 모르는 표본은 학습에 쓰지 않는다.

지표
  MASE  : 오차 / (평가 이전 구간에서 naive 의 같은 기간 오차 평균). 1 보다 작으면 naive 보다 낫다. 주 지표.
          품종마다 계산해 평균 · 중앙값을 낸다 (가격 크기와 상관없이 비교).
  MAPE  : 평균 % 오차.
  DIR   : 오를지 내릴지 맞힌 비율 (실제로 그대로였던 표본은 뺀다). naive 는 '안 바뀐다' 라서 계산하지 않는다.
"""

import time

import numpy as np
import pandas as pd

from ml import baselines, external, features
from ml.dataset import HORIZONS, make_samples

LGBM_PARAMS = {
    "objective": "l1", "learning_rate": 0.05, "num_leaves": 63, "min_child_samples": 100,
    "feature_fraction": 0.8, "bagging_fraction": 0.8, "bagging_freq": 1, "n_estimators": 400,
    "verbose": -1,
}


def refit_dates(start, end, every=28):
    return np.arange(np.datetime64(start, "D"), np.datetime64(end, "D") + 1, every)


def run(series, eval_start, eval_end, models, horizons=HORIZONS, refit_days=28, lgbm_params=None, log=print):
    """평가 구간의 예측표를 만든다. 열: 표본 정보 + 모델마다 pred_<이름> · fb_<이름>(naive 로 메운 표본)."""
    by_sid = {s.sid: s for s in series}
    samples = make_samples(series, horizons, start=eval_start, end=eval_end)
    refits = refit_dates(eval_start, eval_end, refit_days)
    log(f"평가 표본 {len(samples):,}개 · 품종 {samples.sid.nunique()}개 · 재학습 {len(refits)}번")
    naive = baselines.naive(by_sid, samples)
    samples.attrs["importance"] = {}
    ext = None
    for name in models:
        t = time.time()
        if name in external.FEATURE_SETS:
            parts = external.FEATURE_SETS[name]
            if parts and ext is None:
                ext = external.External(external.db_query())
            pred, imp = _lgbm(series, by_sid, samples, refits, horizons, lgbm_params or LGBM_PARAMS, log,
                              ext=ext, parts=parts)
            samples.attrs["importance"][name] = imp
        elif name in baselines.NEEDS_REFITS:
            pred = baselines.BASELINES[name](by_sid, samples, refits)
        else:
            pred = baselines.BASELINES[name](by_sid, samples)
        fb = ~np.isfinite(pred)
        samples[f"pred_{name}"] = np.where(fb, naive, pred)
        samples[f"fb_{name}"] = fb
        log(f"  {name:<18} {time.time() - t:6.1f}s · naive 로 메운 표본 {fb.mean():.1%}")
    return samples


def _lgbm(series, by_sid, samples, refits, horizons, params, log, ext=None, parts=()):
    """LightGBM. parts 가 있으면 외부 특성(날씨 · 물가 · 실험용 oracle)을 가격 특성 옆에 붙인다.

    돌려주는 것: (예측, 마지막 모델의 특성 중요도(gain) Series)
    """
    import lightgbm as lgb   # noqa: PLC0415 — ml 그룹에만 있다

    # 학습 표본: 평가 시작 전부터 쌓인 모든 기준일 (목표일이 refit 이전인 것만 그때그때 쓴다)
    train_all = make_samples(series, horizons, end=refits[-1])
    xf_all = features.build(by_sid, train_all)
    y_all = features.target(train_all)
    xf_eval = features.build(by_sid, samples)
    if parts:
        xf_all = pd.concat([xf_all, ext.build(train_all, parts)], axis=1)
        xf_eval = pd.concat([xf_eval, ext.build(samples, parts)], axis=1)
    cats = {c: xf_all[c].cat.categories for c in features.CATEGORICAL}
    for c in features.CATEGORICAL:
        xf_eval[c] = pd.Categorical(xf_eval[c].astype(str), categories=cats[c])

    out = np.full(len(samples), np.nan)
    origin = samples.origin.to_numpy()
    which = np.searchsorted(refits, origin, side="right") - 1
    for r, when in enumerate(refits):
        k = which == r
        if not k.any():
            continue
        tr = train_all.target_date.to_numpy() < when      # 정답이 이미 나온 표본만
        m = lgb.LGBMRegressor(**params)
        m.fit(xf_all[tr], y_all[tr], categorical_feature=features.CATEGORICAL)
        out[k] = samples.p0.to_numpy()[k] * np.exp(m.predict(xf_eval[k]))
        if r % 6 == 0:
            log(f"    재학습 {r + 1}/{len(refits)} · {str(when)} · 학습 {tr.sum():,}행")
    imp = pd.Series(m.booster_.feature_importance("gain"), index=m.booster_.feature_name()).sort_values(ascending=False)
    return out, imp / imp.sum()


# ── 지표 ──────────────────────────────────────────────────────────────────
def scales(series, eval_start, horizons=HORIZONS):
    """품종 · 기간마다 평가 이전 구간 naive 오차 평균 (MASE 분모)."""
    pre = make_samples(series, horizons, end=np.datetime64(eval_start, "D") - 1)
    pre = pre[pre.target_date < np.datetime64(eval_start, "D")]
    return (pre.y - pre.p0).abs().groupby([pre.sid, pre.h]).mean().rename("scale")


def metrics(samples, scale, models, by=("h",)):
    """모델 × by 별 지표 표."""
    df = samples.join(scale, on=["sid", "h"])
    rows = []
    for name in models:
        e = (df[f"pred_{name}"] - df.y).abs()
        tmp = df.assign(ae=e, ape=e / df.y,
                        se=e / df.scale.where(df.scale > 0),
                        dir_ok=np.sign(df[f"pred_{name}"] - df.p0) == np.sign(df.y - df.p0),
                        moved=df.y != df.p0)
        for key, g in tmp.groupby(list(by)):
            per_series = g.groupby("sid").se.mean()
            # naive 로 메운 표본은 '안 바뀐다' 고 예측한 셈이라 방향을 따지면 늘 틀린다 — 방향 계산에서 뺀다
            mv = g[g.moved & ~g[f"fb_{name}"]]
            rows.append({
                "model": name, **dict(zip(by, key if isinstance(key, tuple) else (key,))),
                "MASE_mean": per_series.mean(), "MASE_median": per_series.median(),
                "MAPE": g.ape.mean(), "DIR": np.nan if name == "naive" else mv.dir_ok.mean(),
                "fallback": g[f"fb_{name}"].mean(), "n": len(g), "series": g.sid.nunique(),
            })
    return pd.DataFrame(rows)


def worst_series(samples, scale, model, top=15):
    df = samples.join(scale, on=["sid", "h"])
    se = (df[f"pred_{model}"] - df.y).abs() / df.scale.where(df.scale > 0)
    return (df.assign(se=se).groupby("sid").agg(MASE=("se", "mean"), n=("se", "size"))
            .sort_values("MASE", ascending=False).head(top))
