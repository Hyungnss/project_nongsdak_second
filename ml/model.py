"""운영 모델 (LightGBM A — 가격만) — 학습 · 게이트 · 저장 · 불러오기 · 롤백.

서버에서 매주 돈다 (.github/workflows/train.yml → python -m collector.train). 시장(소매 · 도매)마다 모델 하나.

  1. 게이트 모델: 최근 8주(HOLDOUT_DAYS)를 떼어 두고 그 전까지만으로 학습 → 떼어 둔 8주를 예측해 채점
  2. 게이트 (챔피언 / 도전자):
       · 성능 — 같은 8주에서 기준선 blend 보다 나아야 한다 (점수 = 1 · 2 · 4주 MASE 중앙값 평균, 튜닝과 같다)
       · 챔피언 — 지금 배포된 모델의 '방법'(meta.json 의 params · inputs)으로도 같은 떼어 두기 전 자료로 다시 학습해
                  같은 8주를 채점한다. 도전자(이번 방법)가 그보다 나쁘면 안 된다 (같은 방법이면 같은 점수라 통과).
                  지금 모델 파일을 그대로 쓰지 않는 이유: 그 모델은 이 8주의 정답을 이미 보고 학습했다 (불공평).
                  배포된 모델이 없으면(처음) 건너뛴다.
       · parity — 파일로 저장했다 다시 읽은 모델이 메모리의 모델과 똑같이 예측해야 한다
       · 정상 — 예측이 모두 유한한 값이어야 한다
  3. 최종 모델: 정답이 나온 전체 자료(2016~)로 다시 학습해 저장한다
  4. 게이트를 통과하면 current.json 이 새 버전을 가리킨다 (= 배포). 못 넘으면 저장만 하고 지금 모델을 그대로 쓴다

파일 (MODEL_DIR, 서버는 Docker 볼륨 models — train.yml 이 버킷 models/ 에도 올린다)
  models/current.json                              {"retail": {"current": 버전, "history": [버전 ...]}, ...}
  models/<retail|wholesale>/<버전>/model.txt        LightGBM 텍스트 형식 (범주 목록까지 들어 있다)
  models/<retail|wholesale>/<버전>/meta.json        학습 시각 · 자료 끝 · 행 수 · 설정 · 게이트 점수

롤백 = current.json 을 이전 버전으로 되돌리기 (rollback). 파일은 지우지 않는다.
설정은 튜닝으로 확정한 기본값 (backtest.LGBM_PARAMS — docs/ML_LightGBM_2차튜닝.md).
"""

import gc
import json
import os
from datetime import datetime
from pathlib import Path

import numpy as np

from ml import backtest, features
from ml.dataset import ROOT, make_samples

MODEL_NAME = "lgbm"
MARKET_EN = {"소매": "retail", "도매": "wholesale"}
HOLDOUT_DAYS = 56          # 게이트용으로 떼어 두는 최근 기준일 (8주)
ANSWER_DAYS = 28 + 3       # 4주 뒤 정답이 나오려면 기준일이 이만큼 지나야 한다 (목표일 + 허용 3일)


def model_dir():
    return Path(os.environ.get("MODEL_DIR") or ROOT / "models")


def lgb_params(n_jobs=2, **override):
    """백테스트(LGBMRegressor)와 같은 모델을 lgb.train 으로 — n_estimators → num_iterations 만 바꾼다."""
    p = {**backtest.LGBM_PARAMS, **override}
    p["num_iterations"] = p.pop("n_estimators")
    p["n_jobs"] = n_jobs
    return p


def fit(series, samples, params, wholesale=None):
    """series: {sid: Series}. 학습 표본으로 Booster 하나. 특성 표는 학습 뒤 버린다 (메모리).

    wholesale: 도매 시계열 목록 (소매 모델만 — 도매 특성 3개를 더한다, features.WHOLESALE).
    """
    import lightgbm as lgb  # noqa: PLC0415

    x = features.build(series, samples, wholesale)
    y = features.target(samples)
    ds = lgb.Dataset(x, y, categorical_feature=features.CATEGORICAL, free_raw_data=True)
    booster = lgb.train(params, ds)
    del x, y, ds
    gc.collect()
    return booster


def uses_wholesale(booster):
    """이 모델이 도매 특성으로 학습됐나 (예전 소매 모델 · 도매 모델은 아니다)."""
    return features.WHOLESALE[0] in booster.feature_name()


def predict_prices(booster, series, samples, wholesale=None):
    """표본마다 예측 가격 = 기준일 가격 × exp(예측한 로그 변화율)."""
    x = features.build(series, samples, wholesale if uses_wholesale(booster) else None)
    return samples.p0.to_numpy(dtype=float) * np.exp(booster.predict(x))


def load_booster(text):
    import lightgbm as lgb  # noqa: PLC0415

    return lgb.Booster(model_str=text)


# ── 게이트 ────────────────────────────────────────────────────────────────
def holdout_range(series):
    """게이트 기간 — 4주 뒤 정답까지 다 나온 가장 최근 8주 (기준일)."""
    latest = max(s.dates[-1] for s in series)
    end = latest - np.timedelta64(ANSWER_DAYS, "D")
    return end - np.timedelta64(HOLDOUT_DAYS - 1, "D"), end


def _holdout(series_list):
    """게이트 기간 · 그 기간의 채점 표본 (blend 예측까지) · MASE 분모."""
    start, end = holdout_range(series_list)
    # 떼어 둔 기간: 기준선 blend 예측까지 같이 (튜닝 · 백테스트와 같은 함수)
    hold = backtest.run(series_list, start, end, ["blend"], log=lambda *_: None)
    return start, end, hold, backtest.scales(series_list, start)


def _fit_before(series_list, params, start, wholesale=None):
    """떼어 둔 기간의 정답을 못 보게 — 목표일이 start 전인 표본으로만 학습. 돌려주는 것: (booster, 학습 행 수)."""
    by = {s.sid: s for s in series_list}
    train = make_samples(series_list)
    train = train[train.target_date.to_numpy() < start].reset_index(drop=True)
    booster = fit(by, train, params, wholesale)
    rows = len(train)
    del train
    gc.collect()
    return booster, rows


def _score(hold, scale, name):
    table = backtest.metrics(hold, scale, ["blend", name])
    return table, {m: float(table[table.model == m].MASE_median.mean()) for m in ("blend", name)}


def challenger_check(series_list, params, wholesale=None):
    """도전자(이번 방법) — 떼어 두기 전 자료로 학습 → 8주 채점 · blend 점수 · parity · 유한. 결과는 작은 dict."""
    by = {s.sid: s for s in series_list}
    start, end, hold, scale = _holdout(series_list)
    booster, rows = _fit_before(series_list, params, start, wholesale)
    pred = predict_prices(booster, by, hold, wholesale)
    hold["pred_lgbm"], hold["fb_lgbm"] = pred, ~np.isfinite(pred)
    table, score = _score(hold, scale, "lgbm")
    # parity — 파일로 저장했다 다시 읽은 모델이 똑같이 예측하는가
    again = predict_prices(load_booster(booster.model_to_string()), by, hold, wholesale)
    return {
        "holdout_start": str(start), "holdout_end": str(end), "holdout_samples": len(hold), "gate_train_rows": rows,
        "score": score["lgbm"], "blend_score": score["blend"],
        "by_h": {int(r.h): float(r.MASE_median) for r in table[table.model == "lgbm"].itertuples()},
        "parity_max_diff": float(np.nanmax(np.abs(again - pred))) if len(pred) else 0.0,
        "finite": bool(np.isfinite(pred).all()),
    }


def champion_check(series_list, params, wholesale=None):
    """챔피언(지금 배포된 모델의 방법) — 도전자와 같은 떼어 두기 전 자료로 다시 학습해 같은 8주를 채점한다."""
    by = {s.sid: s for s in series_list}
    start, _, hold, scale = _holdout(series_list)
    booster, _ = _fit_before(series_list, params, start, wholesale)
    pred = predict_prices(booster, by, hold, wholesale)
    hold["pred_champion"], hold["fb_champion"] = pred, ~np.isfinite(pred)
    table, score = _score(hold, scale, "champion")
    return {"score": score["champion"],
            "by_h": {int(r.h): float(r.MASE_median) for r in table[table.model == "champion"].itertuples()}}


def champion_method(market, root=None):
    """지금 배포된 모델의 방법 {version, params, inputs, note}. 배포된 모델이 없으면 None.

    meta.json 이 없거나 params 가 없으면 방법을 되살릴 수 없다 → note 만 채워 돌려준다 (비교는 건너뛴다).
    inputs 가 없는 예전 모델(v2.6.0)은 가격만이다.
    """
    root = root or model_dir()
    version = (read_current(root).get(MARKET_EN[market]) or {}).get("current")
    if not version:
        return None
    p = root / MARKET_EN[market] / version / "meta.json"
    meta = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
    if not meta.get("params"):
        return {"version": version, "params": None, "inputs": None, "note": "meta.json 에 학습 설정이 없음"}
    return {"version": version, "params": meta["params"], "inputs": meta.get("inputs") or "price", "note": None}


def gate(series_list, params, log=print, wholesale=None, champion=None, isolate=False):
    """도전자를 떼어 둔 8주에서 blend · 챔피언과 겨룬다. 돌려주는 것: 점수 · 통과 여부 · 이유 dict.

    champion: champion_method() 의 결과 (None 이면 챔피언 비교를 건너뛴다 — 배포된 모델이 없을 때).
    isolate=True 면 도전자 · 챔피언 학습을 각각 잠깐 띄운 자식 프로세스에서 (서버 — 두 학습이 한 프로세스에 쌓이지 않게).
    """
    run = _isolated if isolate else (lambda fn, *a: fn(*a))
    c = run(challenger_check, series_list, params, wholesale)
    gc.collect()

    ch_score, ch_by_h, ch_note = None, {}, None
    if champion is not None:
        if champion.get("params") is None:
            ch_note = champion.get("note") or "챔피언 방법을 알 수 없음"
        elif champion["inputs"] == "price+wholesale" and wholesale is None:
            ch_note = "챔피언은 도매 특성을 쓰는데 도매 자료가 없음"
        else:
            # CPU 수만 이번 학습과 같게 (설정 자체는 챔피언 것 그대로)
            ch_params = {**champion["params"], "n_jobs": params.get("n_jobs", 2)}
            ch_ws = wholesale if champion["inputs"] == "price+wholesale" else None
            ch = run(champion_check, series_list, ch_params, ch_ws)
            gc.collect()
            ch_score, ch_by_h = ch["score"], ch["by_h"]
        if ch_note:
            log(f"  챔피언 {champion['version']} 비교 건너뜀 — {ch_note}")

    reasons = []
    if not c["finite"]:
        reasons.append("예측에 NaN · 무한대")
    if c["parity_max_diff"] > 1e-6:
        reasons.append(f"parity 불일치 {c['parity_max_diff']:.2e}")
    if not c["score"] < c["blend_score"]:
        reasons.append(f"blend 보다 나쁨 ({c['score']:.3f} ≥ {c['blend_score']:.3f})")
    # 같은 방법이면 같은 점수 — 소수 끝자리 차이로 떨어지지 않게 아주 작은 여유만 둔다
    if ch_score is not None and not c["score"] <= ch_score + 1e-9:
        reasons.append(f"챔피언보다 나쁨 ({c['score']:.3f} ≥ {ch_score:.3f})")
    out = {k: v for k, v in c.items() if k != "finite"}
    out.update({
        "champion_version": champion["version"] if champion else None,
        "champion_score": ch_score, "champion_by_h": ch_by_h, "champion_note": ch_note,
        "passed": not reasons, "reason": " · ".join(reasons) or "통과",
    })
    vs = f" vs 챔피언 {ch_score:.3f} ({champion['version']})" if ch_score is not None else ""
    log(f"  게이트 {out['holdout_start']} ~ {out['holdout_end']} · 표본 {out['holdout_samples']:,}"
        f" · LightGBM {c['score']:.3f} vs blend {c['blend_score']:.3f}{vs}"
        f" · parity {c['parity_max_diff']:.1e} → {out['reason']}")
    return out


# ── 저장 · 현재 모델 · 롤백 ─────────────────────────────────────────────────
def _current_path(root):
    return root / "current.json"


def read_current(root=None):
    p = _current_path(root or model_dir())
    if not p.exists():
        return {}
    return json.loads(p.read_text(encoding="utf-8"))


def _write_current(data, root):
    root.mkdir(parents=True, exist_ok=True)
    tmp = _current_path(root).with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(_current_path(root))          # 한 번에 바꾼다 (예측이 반쯤 쓴 파일을 읽지 않게)


def save(booster, meta, root=None):
    root = root or model_dir()
    d = root / MARKET_EN[meta["market"]] / meta["version"]
    d.mkdir(parents=True, exist_ok=True)
    (d / "model.txt").write_text(booster.model_to_string(), encoding="utf-8")
    (d / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    return d


def promote(market, version, root=None):
    """current.json 이 이 버전을 가리키게 (배포). history 에 차례로 쌓는다."""
    root = root or model_dir()
    data = read_current(root)
    m = data.setdefault(MARKET_EN[market], {"current": None, "history": []})
    m["current"] = version
    m["history"] = [v for v in m["history"] if v != version] + [version]
    _write_current(data, root)


def rollback(market, to=None, root=None):
    """현재 모델을 이전 버전(또는 to)으로. 돌려주는 것: (이전 current, 새 current)."""
    root = root or model_dir()
    data = read_current(root)
    m = data.get(MARKET_EN[market])
    if not m or not m.get("current"):
        raise ValueError(f"{market}: 배포된 모델이 없습니다")
    hist, cur = m["history"], m["current"]
    if to is None:
        i = hist.index(cur)
        if i == 0:
            raise ValueError(f"{market}: 되돌릴 이전 버전이 없습니다 (history {hist})")
        to = hist[i - 1]
    if not (root / MARKET_EN[market] / to / "model.txt").exists():
        raise ValueError(f"{market}: {to} 모델 파일이 없습니다")
    m["current"] = to
    _write_current(data, root)
    return cur, to


def load_current(market, root=None):
    """현재 모델 (booster, meta). 없으면 None."""
    root = root or model_dir()
    version = (read_current(root).get(MARKET_EN[market]) or {}).get("current")
    if not version:
        return None
    d = root / MARKET_EN[market] / version
    return load_booster((d / "model.txt").read_text(encoding="utf-8")), json.loads(
        (d / "meta.json").read_text(encoding="utf-8"))


# ── 한 번에: 게이트 → 최종 학습 → 저장 → (통과하면) 배포 ─────────────────────
def _final(series_list, params, meta, root, wholesale=None):
    """전체 자료로 최종 학습 → 저장. 돌려주는 것: 채운 meta."""
    import lightgbm as lgb  # noqa: PLC0415

    by = {s.sid: s for s in series_list}
    train = make_samples(series_list)          # 목표일이 있는 표본 = 정답이 나온 전부
    meta = {**meta, "train_rows": len(train), "lightgbm": lgb.__version__}
    booster = fit(by, train, params, wholesale)
    del train
    meta["features"] = booster.feature_name()
    save(booster, meta, root)
    return meta


def _isolated(fn, *args):
    """fn(*args) 를 잠깐 띄운 자식 프로세스에서 돌리고 결과만 받는다.

    학습 한 번에 최대 약 700MB 를 쓰는데, 파이썬은 쓴 메모리를 운영체제에 잘 돌려주지 않는다. 도전자 · 챔피언 · 최종
    학습을 한 프로세스에서 차례로 하면 최대치가 쌓여 960MB 까지 오른다(서버 여유 약 840MB). 자식이 끝나면 메모리가 전부 돌아온다.
    리눅스(서버)는 fork — 부모가 읽어 둔 시계열을 복사 없이 같이 본다. 단 fork 는 부모가 lightgbm(OpenMP)을 한 번도
    돌리지 않았을 때만 안전하다 (GNU OpenMP 는 쓴 뒤 fork 하면 자식이 멈춘다). collector.train 의 부모는 자료만 읽으므로
    괜찮다. 같은 프로세스에서 lightgbm 을 이미 돌린 곳(pytest 등)은 MODEL_MP_CONTEXT=spawn 으로 깨끗한 프로세스를 띄운다.
    """
    import multiprocessing as mp  # noqa: PLC0415
    import sys  # noqa: PLC0415
    from concurrent.futures import ProcessPoolExecutor  # noqa: PLC0415

    method = os.environ.get("MODEL_MP_CONTEXT") or ("fork" if sys.platform.startswith("linux") else "spawn")
    ctx = mp.get_context(method)
    with ProcessPoolExecutor(max_workers=1, mp_context=ctx) as ex:
        return ex.submit(fn, *args).result()


def train_market(market, series_list, n_jobs=2, root=None, now=None, params_override=None, isolate=False,
                 log=print, wholesale=None):
    """isolate=True 면 도전자 · 챔피언 · 최종 학습을 각각 자식 프로세스에서 (서버 — collector.train).

    wholesale: 도매 시계열 목록 — 소매 모델에 도매 특성을 더한다 (collector.train 이 소매일 때 넘긴다).
    """
    params = lgb_params(n_jobs, **(params_override or {}))
    now = now or datetime.now()
    root = root or model_dir()
    version = f"{MODEL_NAME}-{MARKET_EN[market]}-{now:%Y%m%d-%H%M}"
    latest = max(s.dates[-1] for s in series_list)
    log(f"\n[{market}] {version} · 품종 {len(series_list)}개 · 자료 끝 {latest}"
        + (f" · 도매 특성 (도매 {len(wholesale)}품종)" if wholesale is not None else ""))

    # 챔피언 = 지금 배포된 모델의 방법 (이번 학습이 배포되기 전 상태)
    g = gate(series_list, params, log, wholesale, champion=champion_method(market, root), isolate=isolate)
    gc.collect()

    meta = {
        "version": version, "market": market, "model": MODEL_NAME, "trained_at": now.isoformat(timespec="seconds"),
        "data_end": str(latest), "series": len(series_list),
        "inputs": "price+wholesale" if wholesale is not None else "price",
        "params": {k: v for k, v in params.items() if k != "n_jobs"}, "gate": g,
    }
    meta = (_isolated(_final, series_list, params, meta, root, wholesale) if isolate
            else _final(series_list, params, meta, root, wholesale))
    gc.collect()
    if g["passed"]:
        promote(market, version, root)
    log(f"  최종 학습 {meta['train_rows']:,}행 → {root / MARKET_EN[market] / version}"
        f" · {'배포' if g['passed'] else '배포 안 함 (지금 모델 유지)'}")
    return meta
