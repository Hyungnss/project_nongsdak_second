"""예측 모델의 사람이 읽는 이름 — 화면 · 공개 API · Grafana 에서 같이 쓴다.

모델 버전(예: lgbm-retail-20261123-1500)은 추적 · 롤백용 ID 라 그대로 두고, 보여 줄 이름만 여기서 만든다.
따로 관리하는 표 없이 버전 ID 에서 뽑는다 (모델 종류 · 학습 날짜).

  describe("lgbm", "lgbm-retail-20261123-1500")
    → {"model_name": "AI 예측 (LightGBM · 매주 학습)", "trained_on": "2026-11-23", "label": "LightGBM · 11월 23일 학습"}
  describe("blend", "blend-1")
    → {"model_name": "기준선 예측 (예년 계절 흐름)", "trained_on": None, "label": "기준선 blend (학습 없음)"}
"""

import re

NAMES = {
    "lgbm": "AI 예측 (LightGBM · 매주 학습)",
    "blend": "기준선 예측 (예년 계절 흐름)",
}
_TRAINED = re.compile(r"-(\d{4})(\d{2})(\d{2})-\d{4}$")


def describe(model, version=None):
    """model_name(소비자 · API 용) · trained_on(학습 날짜, 'YYYY-MM-DD' 또는 None) · label(운영자 · Grafana 용)."""
    m = _TRAINED.search(version or "")
    trained = f"{m[1]}-{m[2]}-{m[3]}" if m else None
    if model == "lgbm":
        label = f"LightGBM · {int(m[2])}월 {int(m[3])}일 학습" if m else "LightGBM"
    elif model == "blend":
        label = "기준선 blend (학습 없음)"
    else:
        label = model or "—"
    return {"model_name": NAMES.get(model, model), "trained_on": trained, "label": label}
