"""운영 모델 (ml/model.py · ml/predict.py 의 LightGBM 경로) — 게이트 · 배포 · 롤백 · parity · blend 로 대신하기.

DB 없이 가짜 시계열로 돈다. 학습은 나무 수를 줄여 몇 초 안에 끝낸다.
"""

import json
from datetime import datetime

import numpy as np
import pytest

from ml import features, model, predict
from ml.dataset import Series, make_samples
from tests.test_ml import _series

FAST = {"n_estimators": 30, "min_child_samples": 20}
NOW = datetime(2026, 11, 22, 3, 0)


def _market():
    """품목 · 부류가 다른 가짜 시계열 4개 (3년)."""
    return [_series(sid=f"{item}/01/상품", item=item, seed=n) for n, item in enumerate(["211", "212", "213", "214"])]


def _cut(s, k):
    """앞에서 k 개 조사일까지만 남긴 시계열 — '그날이 마지막 조사일' 인 상황."""
    return Series(**{**s.__dict__, "dates": s.dates[:k], "prices": s.prices[:k], "normals": s.normals[:k]})


@pytest.fixture
def root(tmp_path, monkeypatch):
    monkeypatch.setenv("MODEL_DIR", str(tmp_path))
    return tmp_path


# ── 학습 · 게이트 · 배포 ─────────────────────────────────────────────────────
def test_train_saves_model_and_gate_record(root):
    meta = model.train_market("도매", _market(), n_jobs=1, now=NOW, params_override=FAST, log=lambda *_: None)
    d = root / "wholesale" / meta["version"]
    assert meta["version"] == "lgbm-wholesale-20261122-0300"
    assert (d / "model.txt").exists() and json.loads((d / "meta.json").read_text(encoding="utf-8"))["series"] == 4
    g = meta["gate"]
    assert g["parity_max_diff"] < 1e-9                         # 저장했다 다시 읽어도 똑같이 예측
    assert g["holdout_end"] < meta["data_end"]                 # 게이트 기간은 4주 뒤 정답이 나온 과거
    assert set(g["by_h"]) == {7, 14, 28} and np.isfinite(g["score"]) and np.isfinite(g["blend_score"])
    # 배포 여부 = 게이트 통과 여부
    assert (model.read_current().get("wholesale", {}).get("current") == meta["version"]) == g["passed"]


def test_gate_failure_keeps_current_model(root, monkeypatch):
    model.train_market("도매", _market(), n_jobs=1, now=NOW, params_override=FAST, log=lambda *_: None)
    model.promote("도매", "lgbm-wholesale-20261122-0300")
    monkeypatch.setattr(model, "gate", lambda *a, **k: {
        "holdout_start": "x", "holdout_end": "y", "score": 9.0, "blend_score": 1.0, "passed": False,
        "reason": "blend 보다 나쁨", "parity_max_diff": 0.0, "by_h": {}})
    later = model.train_market("도매", _market(), n_jobs=1, now=datetime(2026, 11, 29, 3, 0),
                               params_override=FAST, log=lambda *_: None)
    assert (root / "wholesale" / later["version"] / "model.txt").exists()       # 저장은 한다
    assert model.read_current()["wholesale"]["current"] == "lgbm-wholesale-20261122-0300"   # 배포는 안 한다


def test_gate_blocks_model_worse_than_blend(root):
    """일부러 망친 모델(나무 1개 · 학습률 0)은 blend 를 못 이겨 배포되지 않는다."""
    meta = model.train_market("소매", _market(), n_jobs=1, now=NOW, log=lambda *_: None,
                              params_override={"n_estimators": 1, "learning_rate": 1e-9})
    assert not meta["gate"]["passed"] and "blend" in meta["gate"]["reason"]
    assert "retail" not in model.read_current()


# ── 롤백 ──────────────────────────────────────────────────────────────────
def test_rollback_moves_current_back(root):
    for v in ("lgbm-retail-a", "lgbm-retail-b"):
        (root / "retail" / v).mkdir(parents=True)
        (root / "retail" / v / "model.txt").write_text("x", encoding="utf-8")
        model.promote("소매", v)
    assert model.rollback("소매") == ("lgbm-retail-b", "lgbm-retail-a")
    assert model.read_current()["retail"]["current"] == "lgbm-retail-a"
    with pytest.raises(ValueError, match="이전 버전"):
        model.rollback("소매")                                  # 더 이전이 없다
    assert model.rollback("소매", to="lgbm-retail-b") == ("lgbm-retail-a", "lgbm-retail-b")
    with pytest.raises(ValueError, match="파일이 없습니다"):
        model.rollback("소매", to="lgbm-retail-zzz")
    with pytest.raises(ValueError, match="배포된 모델이 없습니다"):
        model.rollback("도매")


# ── parity: 서빙 특성 = 학습 특성 ────────────────────────────────────────────
def test_serving_features_equal_training_features():
    """같은 기준일 · 기간이면 서빙(serving_samples)과 학습(make_samples)의 특성 행이 똑같다."""
    full = _series()
    k = 400
    while ((full.dates[k - 1].astype(int) + 3) % 7) != 0:          # 월요일 기준 → 7 · 14 · 28일 뒤도 월요일(조사일)
        k += 1
    cut = _cut(full, k)
    serve = predict.serving_samples([cut])
    train = make_samples([full])
    train = train[train.origin == cut.dates[-1]].sort_values("h").reset_index(drop=True)
    assert list(train.target_date) == list(serve.target_date)       # 목표일이 조사일이라 같다
    fs = features.build({cut.sid: cut}, serve)
    ft = features.build({full.sid: full}, train)
    np.testing.assert_array_equal(fs.drop(columns=features.CATEGORICAL).to_numpy(),
                                  ft.drop(columns=features.CATEGORICAL).to_numpy())


# ── 매일 예측: 배포된 모델 · 없거나 망가지면 blend ─────────────────────────────
def test_forecast_market_uses_current_model_then_falls_back(root, monkeypatch):
    series = _market()
    monkeypatch.setattr(predict, "load_all_series", lambda q, m: series)
    # 모델이 없으면 blend
    fc = predict.forecast_market(None, "도매", log=lambda *_: None)
    assert {f.model for f in fc} == {"blend"} and len(fc) == 12

    meta = model.train_market("도매", series, n_jobs=1, now=NOW, params_override=FAST, log=lambda *_: None)
    model.promote("도매", meta["version"])
    fc = predict.forecast_market(None, "도매", log=lambda *_: None)
    assert {f.model for f in fc} == {"lgbm"} and {f.model_version for f in fc} == {meta["version"]}
    assert [f.h for f in fc[:3]] == [7, 14, 28] and all(f.price > 0 and not f.fallback for f in fc)

    # 메모리 모델로 직접 예측한 값과 같다 (저장 → 불러오기 → 서빙 경로)
    booster, _ = model.load_current("도매")
    direct = model.predict_prices(booster, {s.sid: s for s in series}, predict.serving_samples(series))
    np.testing.assert_allclose([f.price for f in fc], np.round(direct, 2))

    # 모델 파일이 망가지면 blend 로 대신한다 (예측이 비지 않게)
    (root / "wholesale" / meta["version"] / "model.txt").write_text("broken", encoding="utf-8")
    seen = []
    fc = predict.forecast_market(None, "도매", log=seen.append)
    assert {f.model for f in fc} == {"blend"} and "blend 로 대신" in seen[0]
