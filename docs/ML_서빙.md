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

---

## LightGBM 운영 — 매주 재학습 · 게이트 · 배포 · 롤백 (v2.6.0)

튜닝 결과 기본 설정(base)의 **LightGBM A(가격만)** 로 바꾼다. 서버가 매주 스스로 학습하고, 게이트를 넘은 모델만 쓴다.

**소매 모델은 v2.7.0 부터 같은 품종의 도매 가격 특성 3개를 더한다** ([도매 특성](ML_도매특성.md)) — 학습 · 매일 예측 때 도매 대표 등급 시계열도 읽는다. 도매 모델은 가격만.

```
매일 17:30   가격 수집 → 점검 → 예측 ─── 배포된 LightGBM (current.json) · 없거나 실패하면 blend
매주 일 03:00  .github/workflows/train.yml (서버 runner)
              └ collector 컨테이너에서 python -m collector.train
                 시장마다 (소매 → 도매, 하나씩)
                   1. 도전자 — 최근 8주를 떼어 두고 그 전까지로 학습 → 그 8주 채점
                      챔피언 — 지금 배포된 모델의 방법(설정 · 입력)으로 같은 자료를 다시 학습 → 같은 8주 채점
                   2. 게이트 — 성능(blend 보다 나은가 · 챔피언보다 나쁘지 않은가) · parity(저장 → 다시 읽어도 같은 예측) · 정상(NaN 없음)
                   3. 최종 모델 — 정답이 나온 전체 자료(2016~)로 학습 → 저장
                   4. 통과하면 current.json 이 새 버전을 가리킨다 (= 배포)
                 → TBL_MODEL_RUN (이력) · 버킷 models/ (사본) → 새 모델로 예측 다시
```

| 무엇 | 어디 |
|---|---|
| 학습 · 게이트 · 저장 · 롤백 | `ml/model.py` · `collector/train.py` |
| 매일 예측 (LightGBM · blend 대신하기) | `ml/predict.py` · `collector/predict.py` |
| 모델 파일 | Docker 볼륨 `models` → `/app/models/<retail\|wholesale>/<버전>/model.txt · meta.json`, `current.json` |
| 사본 | 버킷 `s3://<BACKUP_BUCKET>/models/` (볼륨이 지워져도 되살린다) |
| 이력 | `TBL_MODEL_RUN` — 학습마다 한 줄 (게이트 점수 · blend 점수 · 챔피언 버전 · 점수 · parity · 통과 · 이유) |
| 예측의 출처 | `TBL_PRICE_FORECAST.MODEL` · `MODEL_VERSION` (예: `lgbm` · `lgbm-retail-20261122-0300`). 화면 · API · Grafana 에는 버전에서 만든 이름을 같이 보여 준다 — `AI 예측 (LightGBM · 매주 학습) · 11/23 학습` (`backend/model_names.py`) |

### 게이트 — 챔피언 / 도전자

이번 학습이 **도전자**, 지금 배포된 모델이 **챔피언**이다. 둘 다 '떼어 두기 전' 자료로 학습해 같은 8주에서 채점한다.

| 검사 | 기준 | 왜 |
|---|---|---|
| 성능 · blend | 떼어 둔 최근 8주에서 도전자 점수(1 · 2 · 4주 MASE 중앙값 평균)가 **blend 보다 낮다** | 기준선도 못 이기는 모델은 쓸 이유가 없다. 데이터가 망가졌거나 학습이 잘못되면 여기서 걸린다 |
| 성능 · 챔피언 | 도전자 점수 **≤ 챔피언 점수** (배포된 모델이 없으면 건너뜀) | 방법(설정 · 입력)을 바꿨을 때 지금보다 나쁜 모델이 blend 만 이기고 배포되는 것을 막는다 |
| parity | 파일로 저장했다 다시 읽은 모델의 예측 = 메모리 모델의 예측 (차이 1e-6 이하) | 학습한 모델과 서비스가 쓰는 모델이 같다는 보장 |
| 정상 | 떼어 둔 기간 예측이 모두 유한한 값 | NaN · 무한대가 화면에 나가지 않게 |

못 넘으면 모델은 저장만 하고 **지금 모델을 그대로** 쓴다. 이유(예: `챔피언보다 나쁨 (1.090 ≥ 1.080)`)는 `TBL_MODEL_RUN.REASON` · Actions 로그에 남는다.
떼어 둔 8주는 '4주 뒤 정답까지 나온 가장 최근 8주' 다 (학습에는 그 기간의 정답을 쓰지 않는다 — 누수 없음).

**챔피언을 어떻게 채점하나**
- 지금 모델 파일을 그대로 쓰지 않는다 — 그 모델은 지난 학습 때 전체 자료로 만들어져 **이 8주의 정답을 대부분 이미 봤다**. 그대로 채점하면 챔피언이 늘 유리하다.
- 대신 챔피언의 **방법**을 `meta.json` 에서 읽어(`params` · `inputs`) 도전자와 **같은 자료 · 같은 기준일**로 다시 학습한다. `inputs` 가 `price+wholesale` 이면 도매 특성도 같이 넣는다. `inputs` 가 없는 예전 모델(v2.6.0)은 가격만.
- 같은 방법이면 같은 자료 · 같은 설정이라 **점수가 똑같다** → 챔피언 조건은 늘 통과하고, 실제로 걸리는 건 방법이 바뀐 주뿐이다.
- 챔피언 방법을 되살릴 수 없으면(meta.json 에 `params` 없음 · 챔피언은 도매 특성을 쓰는데 도매 자료가 없음) 챔피언 비교만 건너뛰고 로그에 남긴다 (`CHAMPION_SCORE` NULL).
- 기록: `TBL_MODEL_RUN.CHAMPION_VERSION` · `CHAMPION_SCORE` (마이그레이션 007) · `/metrics` 의 `nongsdak_model_gate_score{model="champion"}`.
- 비용: 학습이 시장마다 한 번 더 (도전자 · 챔피언 · 최종 3번). 셋 다 따로 자식 프로세스라 최대 메모리는 그대로 (한 번에 하나).

실제 자료로 처음 돌려 본 결과 (2026-11-20, 게이트 기간 2026-08-25 ~ 10-19):

| 시장 | LightGBM | blend | 1주 · 2주 · 4주 | 통과 |
|---|---|---|---|---|
| 도매 | **0.951** | 0.994 | 1.035 · 0.926 · 0.892 | ✓ |
| 소매 | **1.072** | 1.102 | 1.110 · 1.057 · 1.050 | ✓ |

### 서빙 parity — 학습과 서비스가 같은 입력을 쓰는가

- 서비스의 특성 행(`ml/predict.serving_samples` → `features.build`)은 같은 기준일 · 기간의 학습 표 행과 **똑같다** — `tests/test_ml_model.py`
- 백테스트(`LGBMRegressor`)와 서버(`lgb.train`)는 같은 설정이면 같은 모델을 낸다 (예측 차이 0 확인)
- 저장(`model.txt`) → 불러오기 → 예측이 메모리 모델과 같다 — 매 학습의 게이트가 확인한다

### 서버 메모리 (1.9GB, 여유 약 840MB)

학습 데이터를 최근 4년으로 줄이면 메모리는 줄지만 정확도가 크게 떨어져(도매 1.069 → 1.121) **전체 기간을 쓴다**. 대신

| 한 일 | 효과 |
|---|---|
| 특성 만들기에서 전체 표 복사 · 행마다 문자열 쪼개기를 없앴다 (결과는 같다) | 소매 특성 864 → 414MB |
| 도전자 · 챔피언 · 최종 학습을 각각 잠깐 띄운 자식 프로세스에서 (`model._isolated`) | 한 프로세스에서 960MB 까지 쌓이던 최대치 → 약 700MB |
| 시장을 하나씩, 트래픽이 거의 없는 일요일 03:00 | 웹 · DB 와 겹치지 않게. 스왑 2GB 가 안전판 |

### 롤백

```
Actions > train > Run workflow > action = rollback, market = 소매 (to 비우면 바로 이전 버전)
또는 서버에서
docker compose exec collector python -m collector.train rollback --market 소매 [--to <버전>]
docker compose exec collector python -m collector.predict          # 바로 반영 (워크플로는 알아서 한다)
```

`current.json` 이 이전 버전을 가리키게 할 뿐 파일은 지우지 않는다. 앱 자체를 되돌리는 것(이미지 버전)은 [RUNBOOK](RUNBOOK.md) '되돌리기'.
LightGBM 을 아예 끄려면 `current.json` 을 지우면 된다 — 다음 예측부터 blend 로 돌아간다.
