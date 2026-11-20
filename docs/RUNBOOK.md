# 운영 런북

서버(AWS Lightsail, 시드니) 배포 · 되돌리기 · 장애 대응 절차. 명령은 그대로 따라 칠 수 있게 적는다.

| | |
|---|---|
| 서비스 | https://hyungnss.eta.pyhub.kr (caddy → web) · 공개 API `/api/v1` · 개발자 `/developers` |
| 서버 폴더 | `/srv/nongsdak` — compose 파일 · Caddyfile · `database/` · `.env`(배포가 Secrets 로 매번 새로 씀) |
| 접속 | `ssh AWS_HG` (PC 의 `~/.ssh/config`) · 비상시 Lightsail 콘솔의 브라우저 SSH (22번) |
| 컨테이너 | `caddy` · `web` · `collector` · `db` (`docker compose ps`) |
| 배포 | `v*` 태그 → `ci.yml`(시험 · 이미지 · Release) → `deploy.yml`(서버 runner) |
| 백업 | 매일 04:00 KST `backup.yml` → `s3://hyungnss-nongsdak/backup/` (30일) · 일요일 복원 시험 |

서버에서 `cd /srv/nongsdak` 뒤에는 `docker compose` 만 치면 된다 — `.env` 의 `COMPOSE_FILE` 이 운영용 두 파일을 함께 쓴다.

---

## 1. 평소 배포

1. 기능 브랜치 → PR → CI 통과 → 머지 (머지만으로는 배포되지 않는다)
2. main 에서 버전 올리기
   ```
   # pyproject.toml 의 version 을 바꾼 뒤
   uv lock
   git commit -am "vX.Y.Z — 요약" && git push
   ```
3. main CI 통과를 본 뒤 태그
   ```
   git tag vX.Y.Z && git push origin vX.Y.Z
   ```
4. Actions 에서 `ci` 의 **서버 배포** 까지 초록인지 본다. 배포 작업이 스스로 확인하는 것:
   - DB 마이그레이션 (`database/migrate.sh`) — 새 버전을 띄우기 **전에**
   - `https://<도메인>/api/health` 200 · 응답의 `version` 이 태그와 같은지
   - http → https 이동
5. 바깥에서 한 번 더
   ```
   curl -s https://hyungnss.eta.pyhub.kr/api/health
   ```

배포 중 실패하면 옛 버전이 계속 돈다 (마이그레이션에서 멈추면 새 버전은 뜨지 않는다).

---

## 2. 되돌리기

### 앱만 이전 버전으로
Actions → **deploy** → Run workflow → 버전에 `2.2.0` 처럼 이전 버전.
GHCR 에 남아 있는 이미지를 다시 띄운다. 2.1.0 이하는 `/api/health` 에 버전이 없어 확인을 건너뛴다(경고만).

마이그레이션은 **더하기만** 하므로(테이블 · 열 추가) 옛 코드가 새 DB 에서 그대로 돈다. DB 를 되돌릴 필요는 보통 없다.

### DB 를 백업 시점으로
데이터가 망가졌을 때만. 서버에서:
```
cd /srv/nongsdak
aws s3 ls s3://hyungnss-nongsdak/backup/ --recursive | tail -5          # 백업 고르기
aws s3 cp s3://hyungnss-nongsdak/backup/2026/11/nongsdak_YYYYMMDD_0400.dump /tmp/x.dump
docker compose stop web collector                                        # 쓰는 쪽을 멈추고
docker compose exec -T db sh -c 'pg_restore --clean --if-exists --no-owner -U "$POSTGRES_USER" -d "$POSTGRES_DB"' < /tmp/x.dump
docker compose start web collector
rm /tmp/x.dump
```
표 하나만: `pg_restore` 에 `-t tbl_user` 를 더한다. 백업 뒤에 수집된 날은 `collector` 가 다음 실행 때 최근 7일을 다시 받아 메운다.

---

## 3. 자주 쓰는 확인

```
cd /srv/nongsdak
docker compose ps                                           # 상태 · healthy
docker compose logs --tail 50 collector                     # 수집기 (다음 작업 시각이 찍힌다)
docker compose logs --tail 50 web
docker compose exec db psql -U nongsdak -d nongsdak         # DB (비밀번호 없이)
docker compose exec collector python -m collector.check     # 최근 7일 가격 수집 점검
docker compose exec collector python -m collector.quality   # 품질 점검 (가격 · 날씨 · 물가)
free -h ; df -h /                                           # 메모리 · 디스크
```

수집 작업을 지금 한 번 돌리기 (예약 시각을 기다리지 않고):
```
docker compose exec collector python -m collector.scheduler --once            # 가격 → 점검 → 예측
docker compose exec collector python -m collector.predict                     # 예측만 다시 (가격을 손으로 고친 뒤 등)
docker compose exec collector python -m collector.scheduler --once weather    # weather · cpi · forecast_am · forecast_pm
```

---

## 4. 장애 대응

| 증상 | 먼저 볼 것 | 조치 |
|---|---|---|
| 사이트가 안 열림 | `docker compose ps` · `logs caddy` · `logs web` | 멈춘 컨테이너 `docker compose up -d`. 인증서 오류면 caddy 로그 (`caddy_data` 볼륨은 지우지 않는다 — 발급 횟수 제한) |
| `/api/health` 503 | `logs db` · `df -h` | DB 가 죽었거나 디스크가 찼다 |
| 예측이 안 바뀜 · 빈 목록 | `SELECT MAX(base_date), model_version, COUNT(*) FROM tbl_price_forecast GROUP BY 2` · `logs collector` | 예측은 17:30 가격 작업의 마지막 단계다. 철 지난 품종(7일 넘게 조사 없음)은 일부러 예측하지 않는다 (빈 목록). 급하면 `collector.predict` |
| 가격이 안 바뀜 | `logs collector` · `collector.check` | KAMIS 장애면 다음 날 7일치를 다시 받아 메운다. 급하면 `--once` |
| 날씨 · 물가 수집 실패 | `TBL_INGEST_LOG` 의 ERROR 행 | 키 만료(공공데이터포털 활용기간 · ECOS) → Secrets 갱신 후 재배포 |
| **예보가 빠짐** | `SELECT TM_FC, COUNT(*) FROM TBL_FCST_RAW GROUP BY 1 ORDER BY 1 DESC LIMIT 5` | 기상청은 **최근 24시간분만** 준다 — 24시간 안이면 `--once forecast_am` 으로 메운다. 지나면 되살릴 수 없다 |
| 백업 실패 (Actions 빨간불) | backup 작업 로그 | 버킷 연결(Lightsail 리소스 액세스) · 디스크 · `aws s3 ls s3://hyungnss-nongsdak` |
| 메모리 부족 | `free -h` · `docker stats --no-stream` | 스왑 2GB 가 있다. 계속 모자라면 인스턴스 요금제를 올린다 |

---

## 5. v2.3.0 배포 (2026-11-19 · 한 번만)

v2.3.0 은 평소보다 손이 더 간다: 마이그레이션 003 · 004, 로컬에서 받은 백필 약 110만 행 이전, 수집 작업이 1개에서 5개로.
**순서가 중요하다** — 테이블(마이그레이션)이 생긴 뒤에 데이터를 옮긴다.

### 준비 (PC)
- [ ] 로컬 가격 백필 완료 (`uv run python -m collector.backfill --status` — 오류 구간 0)
- [ ] 소매 품질 점검 (`uv run python -m collector.quality --only price --market 소매`)
- [ ] 브랜치 3개가 main 위에 있다 (`feat/backfill` → `feat/ingest-weather-cpi`, `feat/ml-baseline`)
- [ ] GitHub Secrets 에 `DATA_GO_KR_KEY` · `ECOS_KEY` (deploy 가 없으면 멈춘다)

### 순서
| # | 할 일 | 확인 |
|---|---|---|
| 1 | PR `feat/backfill` → 머지 | CI 초록 |
| 2 | PR `feat/ingest-weather-cpi` (base 를 main 으로) → 머지 | CI 초록 (compose 작업이 마이그레이션 003 · 004 를 두 번 적용해 본다) |
| 3 | PR `feat/ml-baseline` → 머지 | CI 초록 (ml 그룹은 서버 이미지에 안 들어간다) |
| 4 | `pyproject.toml` 2.3.0 · `uv lock` · 커밋 · push → main CI | |
| 5 | `git tag v2.3.0 && git push origin v2.3.0` | 서버 배포 로그에 `적용: 003_price_backfill` · `적용: 004_weather_cpi_forecast` · `버전: 2.3.0` |
| 6 | 서버 수집기가 작업 5개로 떴는지 `docker compose logs --tail 5 collector` | `forecast_am 06:40 · weather 11:30 · cpi 11:40 · price 17:30 · forecast_pm 18:40` |
| 7 | PC 에서 데이터 이전 | 아래 |
| 8 | 화면 · API 확인 | 아래 |
| 9 | (17:30 서버 가격 수집을 본 뒤) PC 작업 스케줄러 끄기 | 아래 |

### 7. 데이터 이전 (PC, Git Bash)
```
uv run python database/transfer.py export                  # 로컬 → logs/transfer/*.csv.gz (최신으로 다시)
uv run python database/transfer.py push --ssh AWS_HG        # 표마다 '새로 들어간 행'
uv run python database/transfer.py verify --ssh AWS_HG      # 표마다 로컬 · 서버 행 수 + 내용 해시
```
- 서버에 이미 있는 행은 건너뛴다 — 몇 번 다시 돌려도 결과가 같다. 표마다 한 트랜잭션.
- `verify` 에서 날씨 · 예보가 **서버가 더 많음** 이면 정상이다 (배포 뒤 서버가 직접 받은 날).
- 예보는 로컬에서 받아 둔 발표분까지 옮겨진다 — 배포 전 18시 발표분을 로컬에 받아 뒀다면 그것도.

### 8. 확인
```
curl -s https://hyungnss.eta.pyhub.kr/api/v1/status         # retail.earliest_date 가 2016-…
curl -s -o /dev/null -w "%{time_total}s\n" https://hyungnss.eta.pyhub.kr/api/briefing   # 0.5초 안팎
ssh AWS_HG 'cd /srv/nongsdak && docker compose exec -T db psql -U nongsdak -d nongsdak -c "SELECT version, name FROM tbl_schema_migration ORDER BY 1"' 
ssh AWS_HG 'free -h; df -h /'
```

### 9. PC 작업 스케줄러 끄기
서버 `price` 작업이 17:30 에 돈 것을 본 뒤 (`docker compose logs collector` · `collector.check`).
PC 의 관리자 PowerShell 에서:
```
schtasks /Change /TN KAMIS_fetch_1730 /DISABLE
schtasks /Query /TN KAMIS_fetch_1730 /FO LIST | findstr 상태
```
다시 켤 때는 `/ENABLE`. 이 뒤로 최신 데이터는 서버에만 있다 — 백업은 버킷이 맡는다.

### 실패하면
| 어디서 | 조치 |
|---|---|
| 1~4 (머지 · CI) | 서버는 그대로 — 고쳐서 다시 |
| 5 마이그레이션 | 옛 버전(2.2.0)이 계속 돈다. 로그의 SQL 오류를 고쳐 v2.3.1 |
| 5 새 버전 기동 · 확인 | Actions → deploy → 2.2.0 (2절). 마이그레이션은 더하기라 그대로 둬도 된다 |
| 7 이전 | 실패한 표만 다시 `push` (덮어쓰지 않는다) |
| 8 화면이 느림 | `collector.quality` 와 별개로 `docker stats` · 인덱스 확인 |
