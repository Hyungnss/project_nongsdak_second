# 가격 예측 — 서빙 (예측을 서비스에 올리기)

> 결과 요약은 [ML.md](ML.md). 이 문서는 매일 예측 · API · 모델 교체 방법을 남긴다.

---

## 서빙 — 예측을 서비스에 올리기 (v2.4.0)

**기준선(blend)을 먼저 운영에 올리고, 더 나은 모델이 증명되면 교체한다.** 표 · API · 화면은 모델과 상관없이 같다.

```
매일 17:30  가격 수집 → 점검 → collector/predict.py  (ml/predict.py — blend)
            품종 · 등급마다 마지막 조사일 기준 7 · 14 · 28일 뒤 → TBL_PRICE_FORECAST
화면        GET /api/forecast?item&kind&rank&market            (backend/forecast.py — 화면과의 약속 모양)
공개 API    GET /api/v1/forecast  (키 필요, {data, meta}, meta.model · model_version)
평가        V_FORECAST_EVAL — 목표일의 실제 가격이 나오면 예측과 비교 (APE · 방향)
```

| 규칙 | 이유 |
|---|---|
| 기준일 = 그 품종의 마지막 조사일 | 주말 · 공휴일에도 가장 최근 가격에서 출발 |
| 시장 최신 조사일보다 7일 넘게 끊긴 품종은 예측하지 않는다 (빈 목록) | 철 지난 등급(예: 올해 조사 안 된 가을 배추 중품)에 1년 전 가격을 '예측' 으로 보여 주지 않게 |
| 계절 모양을 못 만들면 기준일 가격 그대로 + `FALLBACK` 표시 | 예측이 비지 않게 하되 메운 것인지 추적한다 |
| 예측마다 `MODEL` · `MODEL_VERSION` 저장 | 어떤 모델이 이 숫자를 냈는지 끝까지 추적 (교체 전후 비교) |

모델 교체 — `ml/predict.py` 의 `MODEL` · `MODEL_VERSION` 과 예측 함수를 바꾼다. LightGBM 으로 바꾸면 서버 이미지에
lightgbm(+ libgomp)과 모델 파일(버킷 `models/` + `current.json`)이 필요하다 (v2.6.0 계획).
