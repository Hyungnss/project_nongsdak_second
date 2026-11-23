# 운영 모니터링 — Prometheus + Grafana

서버(AWS Lightsail)에서 **웹 요청 수 · 지연 · 오류율**과 **서버 CPU · 메모리 · 디스크**를 모아 보여 준다.
서버용 덧씌움 파일(`docker-compose.prod.yml`)에만 들어 있어서, 배포하면 같이 뜬다. 이 PC 의 `docker compose up -d` 에는 없다.

```
 인터넷 ──https──▶ caddy ─┬─ /metrics   → 404 (막음)
                          ├─ /grafana/* → grafana:3000 ──▶ prometheus:9090
                          └─ 그 밖       → web:8000

 prometheus 가 30초마다 내부망에서 긁는다:  web:8000/metrics · node-exporter:9100 · 자기 자신
```

| 서비스 | 이미지 | 하는 일 | mem_limit |
|---|---|---|---|
| `prometheus` | `prom/prometheus:v3.16.0` | 지표를 모아 저장 (15일 · 많아야 1GB) | 256m |
| `grafana` | `grafana/grafana:13.3.1` | 대시보드 (운영자 전용, 로그인 필요) | 256m |
| `node-exporter` | `prom/node-exporter:v1.13.1` | 서버 CPU · 메모리 · 디스크를 내보냄 | 64m |

셋을 합쳐 많아야 **576MB**. 로컬에서 재 보니 prometheus 약 135MB · node-exporter 약 14MB 였고, grafana 는
`docker stats` 로는 한도(256MB) 가까이 보이지만 실제로 쓰는 힙은 110MB 남짓이다 — 나머지는 Go 가 늦게 돌려주는
메모리(`GOMEMLIMIT=200MiB` 근처에서 GC 가 거둔다)와 내부 DB 파일 캐시라 모자라면 버려진다.
grafana 는 처음 뜰 때 내부 DB 를 만드느라 1~2분 걸린다.
한도를 넘으면 그 컨테이너만 죽고(`restart: unless-stopped`) 다시 뜬다 — 웹 · DB 는 영향이 없다.

세 서비스 모두 **포트를 열지 않는다.** 바깥에서 들어오는 길은 caddy 의 `/grafana/` 하나뿐이다.

---

## 처음 한 번 — 관리자 비밀번호

1. GitHub 저장소 → Settings → Secrets and variables → Actions → **New repository secret**
   - 이름: `GRAFANA_ADMIN_PASSWORD`
   - 값: 긴 무작위 문자열. **영문 · 숫자만** 쓴다 (`$` · `#` · 따옴표는 `.env` 에서 다르게 읽힐 수 있다).
2. 다음 배포 때 `deploy.yml` 이 서버의 `.env` 에 넣는다. **이 Secret 이 없으면 배포가 멈춘다** (`.env 쓰기` 단계).
3. `https://<도메인>/grafana/` → 아이디 `admin` · 위 비밀번호로 로그인.

> ⚠ 이 비밀번호는 grafana 가 **처음** 뜰 때(`grafana_data` 볼륨이 비어 있을 때)만 들어간다.
> 나중에 Secret 만 바꾸면 **반영되지 않는다**. 바꾸려면 서버에서:
>
> ```
> cd /srv/nongsdak
> docker compose exec grafana grafana cli admin reset-admin-password '새비밀번호'
> ```
>
> 그리고 GitHub Secret 도 같은 값으로 바꿔 둔다 (다음에 볼륨을 새로 만들 때 쓰이도록).

익명 접근 · 회원가입은 꺼져 있다. 다른 운영자가 필요하면 admin 으로 로그인해 Administration → Users 에서 만든다.

---

## 대시보드 — "농스닥 운영"

로그인하면 바로 뜬다 (홈 대시보드). 원본은 저장소의 `monitoring/grafana/dashboards/nongsdak.json`.

| 칸 | 무엇을 | 식 (요약) |
|---|---|---|
| 웹 상태 | prometheus 가 web 을 긁을 수 있는지 (UP/DOWN) | `up{job="web"}` |
| 초당 요청 · 상태 코드별 | 방문자 요청 (헬스체크 · `/metrics` 제외) | `rate(http_requests_total[5m])` |
| p50 · p95 지연 | 응답을 다 보낼 때까지 걸린 시간 | `histogram_quantile(0.95, … http_request_duration_highr_seconds_bucket …)` |
| 오류율 (5xx) | 전체 요청 중 서버 오류 비율. 4xx 는 넣지 않는다 | `5xx / 전체` |
| 경로별 요청 상위 10 | 어느 API 가 많이 불리는지. `none` 은 없는 주소(404) 모음 | `topk(10, increase(…[$__range]))` |
| CPU · 메모리 · 스왑 · 디스크 | 서버 전체 | node-exporter |
| **예측 모델** — 지금 모델 · 게이트 · 마지막 학습 | 어떤 모델이 예측을 내고 있나 (lgbm · blend), 마지막 재학습이 게이트를 넘었나, 몇 시간 전인가 | `nongsdak_model_*` |
| **예측 · 가격 신선도** | 가장 최근 예측 기준일 · 가격 조사일이 며칠 전인가 (수집 · 예측이 멈췄는지) | `nongsdak_forecast_base_date_*` · `nongsdak_price_latest_*` |
| **게이트 점수 vs blend** | 매주 학습마다 떼어 둔 8주 점수 (낮을수록 좋음) | `nongsdak_model_gate_score` |
| **예측 vs 실제** | 최근 28일 평균 % 오차 · 방향 맞힘 (정답이 나온 예측만 — 첫 채점 11-26) | `nongsdak_forecast_eval_*` |

색 기준: p95 0.5초 주황 · 1초 빨강, 오류율 1% 주황 · 5% 빨강, CPU · 메모리 70% 주황 · 90% 빨강, 디스크 80% · 90%. 예측 · 가격 경과 3일 주황 · 5일 빨강 (주말 · 공휴일 2~3일은 정상), 마지막 학습 8일 주황 · 15일 빨강.

### 대시보드 고치기

화면에서 고쳐도 **저장되지 않는다** (프로비저닝된 대시보드라서 — 서버에서 고친 것이 저장소와 어긋나지 않게).

1. grafana 에서 고친 뒤 → 오른쪽 위 **Export → Export as JSON** 으로 내려받는다.
2. 저장소의 `monitoring/grafana/dashboards/nongsdak.json` 을 그 내용으로 바꾼다 (`uid` 는 `nongsdak-ops` 그대로).
3. PR → 머지 → 배포. grafana 는 60초 안에 파일을 다시 읽는다.

`tests/test_repo_files.py` 가 JSON 이 깨지지 않았는지, 모든 패널이 데이터 원본 `prometheus` 를 쓰는지 본다.

### 그때그때 조회 — Explore

정해진 대시보드 밖의 것은 grafana 왼쪽 메뉴 **Explore** 에서 PromQL 로 본다. 예:

```
sum by (handler) (rate(http_requests_total{job="web",status="429"}[5m]))   # 호출 제한(429)에 걸린 경로
sum by (handler) (rate(http_requests_total{job="web",status=~"5.."}[1h]))  # 5xx 가 난 경로
process_resident_memory_bytes{job="web"}                                   # web 프로세스 메모리
prometheus_tsdb_storage_blocks_bytes                                       # prometheus 저장 용량
```

prometheus 자체 화면(9090)은 바깥에 열지 않는다. 필요하면 내 PC 에서 SSH 터널로:
`ssh -L 9090:<prometheus 컨테이너 IP>:9090 ubuntu@<서버>` — 보통은 Explore 로 충분하다.

---

## 지표가 나오는 곳 — `/metrics`

`backend/app.py` 의 `prometheus-fastapi-instrumentator` 가 내보낸다.

| 지표 | 라벨 | 뜻 |
|---|---|---|
| `http_requests_total` | `handler` · `method` · `status` | 요청 수 |
| `http_request_duration_highr_seconds` | (없음) | 지연 히스토그램, 버킷이 촘촘하다 — p95 는 이걸로 |
| `http_request_duration_seconds` | `handler` · `method` | 경로별 지연 (버킷 0.1 · 0.5 · 1초로 성기다) |
| `http_request_size_bytes` · `http_response_size_bytes` | `handler` | 요청 · 응답 크기 |
| `process_*` · `python_gc_*` | | web 프로세스 CPU · 메모리 · GC |
| `nongsdak_model_info` · `_gate_score` · `_gate_passed` · `_trained_timestamp_seconds` · `_runs` | `market` (· `model` · `version` · `name` · `result`) — `name` 은 사람이 읽는 이름 (`LightGBM · 11월 23일 학습`, `backend/model_names.py`) | 예측 모델 상태 — `backend/model_metrics.py` |
| `nongsdak_forecast_rows` · `_base_date_timestamp_seconds` · `nongsdak_price_latest_timestamp_seconds` | `market` | 예측 · 가격 신선도 |
| `nongsdak_forecast_eval_ape` · `_direction` · `_count` | `market` · `h` | 예측 vs 실제 (최근 28일, `V_FORECAST_EVAL`) |

- `handler` 는 **경로 틀**이다 (`/api/detail`, `/api/v1/prices/history`, `/static`). 없는 주소는 모두 `none` —
  스캐너가 아무 주소나 두드려도 지표 종류가 늘지 않는다.
- `status` 는 묶지 않은 상태 코드 그대로 (`200` · `401` · `404` · `429` · `503` …).
- `/api/health` 는 세지 않는다 — 컨테이너 healthcheck 가 10초마다 불러 실제 방문이 묻히기 때문이다.
- `nongsdak_*` 는 웹이 **DB 를 읽어** 만든다 (60초에 한 번만 — prometheus 는 30초마다 긁는다). grafana 에 DB 접속을 주지 않으려고
  이렇게 했다 (모니터링 쪽 권한이 늘지 않는다). DB 를 못 읽으면 이 지표만 빠지고 `/metrics` 는 그대로 나온다.
- uvicorn 이 프로세스 하나로 돈다 (`--workers` 없음). 여러 개로 늘리면 프로세스마다 숫자가 따로 놀아
  multiprocess 설정이 필요하다.

### 바깥에서 보이지 않게

`/metrics` 는 web 에 그대로 열려 있지만, 서버에서 web 은 포트를 열지 않고 caddy 만 말을 건다.
caddy 는 `Caddyfile` 에서 `/metrics` · `/metrics/*` 를 **web 으로 넘기기 전에 404** 로 끊는다.
grafana 도 자기 지표를 `/metrics` 에 인증 없이 내놓기 때문에 `GF_METRICS_ENABLED=false` 로 끄고,
caddy 에서 `/grafana/metrics` 도 404 로 한 번 더 막는다.
prometheus 는 caddy 를 거치지 않고 docker 내부망에서 `web:8000/metrics` 를 직접 긁는다.

- 배포 작업(`deploy.yml` 의 확인 단계)이 매번 `https://<도메인>/metrics` · `/grafana/metrics` 가 404 인지, `/grafana/api/health` 가 200 인지 본다.
- 이 PC 의 `docker compose up -d` 에서는 `http://127.0.0.1:8080/metrics` 로 보인다 (이 PC 안에서만 열린 포트).

---

## 서버에서 손으로 볼 때

```
cd /srv/nongsdak
docker compose ps prometheus grafana node-exporter      # 셋 다 Up 인지
docker compose logs --tail 50 grafana                   # 로그인 · 프로비저닝 오류
docker compose logs --tail 50 prometheus                # 설정 오류 · 긁기 실패
docker stats --no-stream                                # 컨테이너별 메모리 (MEM USAGE / LIMIT)
```

| 증상 | 원인과 해결 |
|---|---|
| 배포가 `.env 쓰기` 에서 `GRAFANA_ADMIN_PASSWORD 가 비어 있습니다` | Secret 을 아직 등록하지 않았다 (위 '처음 한 번') |
| `/grafana/` 가 502 | grafana 가 아직 뜨는 중이거나 죽었다. `docker compose logs grafana` |
| 대시보드가 "No data" | grafana → Connections → Data sources → Prometheus → Test. 웹 상태 칸이 DOWN 이면 web 쪽 |
| 서버 칸만 비어 있음 | node-exporter 가 죽었다. `docker compose logs node-exporter` |
| 비밀번호가 안 맞음 | Secret 을 grafana 가 처음 뜬 뒤에 바꿨다. 위의 `reset-admin-password` |
| 디스크가 찬다 | prometheus 는 1GB 를 넘지 않는다. `docker system df -v` 로 다른 것(이미지 · 로그)을 본다 |

## 끄거나 지우기

- 잠깐 끄기: `docker compose stop prometheus grafana node-exporter` (다음 배포 때 다시 뜬다).
- 모아 둔 지표만 버리기: `docker compose rm -sf prometheus` 후 `docker volume rm nongsdak_prometheus_data`, 그리고 다시 배포.
  grafana 의 `grafana_data` 를 지우면 로그인 계정도 사라지고, 다음에 뜰 때 Secret 의 비밀번호로 새로 만들어진다.
- 아예 빼려면 `docker-compose.prod.yml` 에서 세 서비스를, `Caddyfile` 에서 `/grafana/` 를 지운다.
