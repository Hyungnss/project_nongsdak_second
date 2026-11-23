"""예측 모델의 사람이 읽는 이름 (backend/model_names.py)."""

from backend import model_names


def test_lgbm_name_and_trained_date_from_version():
    d = model_names.describe("lgbm", "lgbm-retail-20261123-1500")
    assert d == {"model_name": "AI 예측 (LightGBM · 매주 학습)", "trained_on": "2026-11-23",
                 "label": "LightGBM · 11월 23일 학습"}
    assert model_names.describe("lgbm", "lgbm-wholesale-20260105-0300")["label"] == "LightGBM · 1월 5일 학습"


def test_blend_and_unknown():
    assert model_names.describe("blend", "blend-1") == {
        "model_name": "기준선 예측 (예년 계절 흐름)", "trained_on": None, "label": "기준선 blend (학습 없음)"}
    assert model_names.describe("xgb", "xgb-7")["model_name"] == "xgb"         # 모르는 모델은 이름 그대로
    assert model_names.describe(None, None)["label"] == "—"
