# 농스닥 — 내 PC에서 돌려보기

PostgreSQL 을 Docker 로 띄우고, 원본 CSV 를 넣고, 웹서비스를 띄우는 순서다.
처음부터 끝까지 **10분쯤** 걸린다.

> v1.0.0 까지는 Oracle XE 11g 를 썼다. v2 부터 PostgreSQL 이다.
> Oracle 에 쌓인 데이터를 옮겨 오는 방법은 맨 아래 [Oracle 에서 옮겨 오기](#oracle-에서-옮겨-오기-v1--v2) 에 있다.

---

## 0. 준비물

| | 확인 방법 |
|---|---|
| **Docker Desktop** | `docker --version` · `docker compose version` — PostgreSQL 을 컨테이너로 띄운다 |
| **uv** | `uv --version` — 파이썬 3.11 은 uv 가 알아서 받는다 (1단계) |
| **Git** | `git --version` · 저장소를 받는다: `git clone <저장소주소>` |

원본 CSV(`data/raws/kamis_price_data_20250901_20260818.csv`)는 저장소에 함께 들어 있다.
`.env` 와 `.venv/`, `logs/` 는 들어 있지 않다 — 각자 만든다(1·2단계).

예전처럼 Oracle Instant Client 를 깔 필요는 없다.

---

## 1. 파이썬 환경 만들기 — uv

파이썬 버전(`.python-version` = 3.11)과 패키지 버전(`uv.lock`)은 [uv](https://docs.astral.sh/uv/) 로 관리한다.
uv 가 없으면 먼저 설치한다.

```powershell
winget install --id=astral-sh.uv -e
```

저장소 폴더에서 한 줄이면 된다. 파이썬 3.11 이 없으면 uv 가 받아 오고, `.venv/` 를 만들어
`uv.lock` 에 적힌 버전 그대로 설치한다.

```
uv sync
```

- 실행은 `uv run ...` 으로 한다 (예: `uv run python -m collector.upsert --dry-run`).
  `.venv\Scripts\python.exe -m ...` 로 직접 불러도 같다 — 작업 스케줄러용 `run_fetch.bat` 은 이쪽을 쓴다
  (스케줄러 환경에 uv 가 PATH 에 없어도 돌게 하려고).
- 패키지를 더하거나 빼려면 `uv add 이름` / `uv remove 이름`. `pyproject.toml` 과 `uv.lock` 이 같이 바뀌니 둘 다 커밋한다.
- 서버에는 개발 도구(pytest · ruff)가 필요 없으므로 `uv sync --no-dev` 로 설치한다.

---

## 2. 접속 정보 맞추기 — `.env`

접속 정보는 **`.env` 한 곳**에만 적는다. 코드(`config.py`)와 `docker compose` 가 둘 다 여기서 읽는다.
`.env` 는 커밋되지 않는다 (`.gitignore`).

```
Copy-Item .env.example .env
```

만든 `.env` 에서 고칠 값:

| 값 | 설명 |
|---|---|
| `DB_PASSWORD` | **꼭 정한다.** 3단계에서 DB 를 처음 띄울 때 이 비밀번호로 만들어진다 (나중에 바꾸려면 볼륨을 새로 만들어야 한다) |
| `DB_HOST` · `DB_PORT` · `DB_NAME` · `DB_USER` | 기본값(`127.0.0.1` · `5432` · `nongsdak` · `nongsdak`) 그대로 두면 된다 |
| `KAMIS_CERT_KEY` · `KAMIS_CERT_ID` | 6단계에서 채운다. 지금은 비워 둬도 웹서비스는 뜬다 |

값을 찾는 순서는 **환경변수 → `.env` → `config.py` 의 기본값**이다.
KAMIS 인증키는 기본값을 두지 않는다 — 없는 채로 수집기를 돌리면 안 되기 때문이다.

> **`DB_HOST` 를 `localhost` 로 적지 말 것** — Windows 는 `localhost` 를 IPv6(`::1`)로 먼저 시도하는데,
> Docker 는 IPv4(`127.0.0.1`)에만 열어 두어서 접속할 때마다 몇 초씩 멈춘다.

---

## 3. DB 띄우기 — docker compose

```
docker compose up -d db
```

처음 뜰 때 `database/schema.sql` 이 자동으로 실행돼 **테이블 6개**(시세 · 수집 이력 · API 원문 ·
회원 · 로그인 세션 · 장바구니)가 만들어진다. 데이터는 `pgdata` 볼륨에 남아서 껐다 켜도 그대로다.

그다음 **마이그레이션**을 적용한다 (공개 API 키 · 사용량 테이블 등 나중에 더한 것). Git Bash 에서:

```
bash database/migrate.sh
```

아직 적용하지 않은 `database/migrations/NNN_*.sql` 만 순서대로 적용하고 `TBL_SCHEMA_MIGRATION` 에 남긴다.
몇 번을 돌려도 괜찮다. `git pull` 로 새 마이그레이션 파일이 생기면 다시 돌린다.
서버에서는 배포 작업(`deploy.yml`)이 새 버전을 띄우기 전에 알아서 돌린다.

> 새 마이그레이션을 만들 때: 다음 번호로 **새 파일**을 만든다 (`003_무엇.sql`). 머지된 파일은 고치지 않는다.
> 기존 코드가 새 DB 에서도 돌도록 **더하기**(테이블 · 컬럼 추가)로 쓴다 — 배포는 DB 를 먼저 바꾸고 앱을 나중에 바꾼다.

```
docker compose ps                                       # STATUS 가 healthy 면 준비 완료
docker compose exec db psql -U nongsdak -d nongsdak     # 직접 들어가 보기 (\dt 로 테이블 목록)
```

| 할 일 | 명령 |
|---|---|
| 끄기 (데이터 유지) | `docker compose down` |
| 처음부터 다시 (⚠ 데이터 삭제) | `docker compose down -v` 후 `docker compose up -d db` |

DB 는 이 PC 안에서만 접속할 수 있다 (`127.0.0.1:5432`). 버전은 `postgres:18.7` 로 고정돼 있다.

---

## 4. CSV 적재

```
uv run python -m collector.loader
```

이렇게 나오면 성공이다.

```
CSV 읽음: kamis_price_data_20250901_20260818.csv · 43,480행
PostgreSQL 연결 성공 (127.0.0.1:5432/nongsdak)
적재 완료: 43,480행
기간 2025-09-01 ~ 2026-08-18 · 품목 93개 · 당일가격 있는 행 40,xxx
```

> **`duplicate key value violates unique constraint` 가 나면** — 이미 들어 있는 자료가 있다.
> 처음부터 다시 넣으려면 psql 에서 `TRUNCATE TBL_DAILY_PRICE;` 를 실행하고 다시 돌린다.

---

## 5. 웹서비스 실행

둘 중 하나로 띄운다.

| 방법 | 명령 | 주소 | 언제 |
|---|---|---|---|
| 개발 (코드 고치면 바로 반영) | `uv run uvicorn backend.app:app --reload` | http://127.0.0.1:8000 | 코드를 고칠 때 |
| 컨테이너 (서버와 같은 모양) | `docker compose up -d --build` | http://127.0.0.1:8080 | 배포 전에 확인할 때 |

컨테이너는 `Dockerfile` 로 만든 이미지 하나를 웹과 수집기가 같이 쓴다. `docker compose up -d` 는
`db` + `web` 만 띄운다 — 이 PC 에서는 수집을 작업 스케줄러가 하므로 `collector` 는 띄우지 않는다
(두 번 수집하지 않게). 서버에서는 `.env` 에 `COMPOSE_PROFILES=collector` 를 넣어 같이 띄운다.

```
docker compose ps               # web 이 healthy 면 DB 까지 정상 (/api/health)
docker compose logs -f web      # 로그
docker compose up -d --build    # 코드를 고친 뒤 이미지 다시 만들기
```

---

## 6. 최신 날짜 채우기 — KAMIS OpenAPI

여기까지는 CSV 한 개(2026-08-18 까지)를 넣은 상태다. **그 뒤 날짜는 API 로 받는다.**

1. KAMIS 에서 OpenAPI 인증키를 발급받는다 (`p_cert_key` · `p_cert_id`).
2. `.env` 에 채운다.

   ```
   KAMIS_CERT_KEY=발급받은키
   KAMIS_CERT_ID=마이페이지의ID
   ```

   `KAMIS_CERT_ID` 는 **로그인 아이디가 아니다.** KAMIS 마이페이지에 따로 나오는 ID 를 넣는다.

3. 빠진 날짜를 채운다. `--days N` 은 그날부터 거슬러 N일치를 함께 받는다.

   ```
   uv run python -m collector.upsert --days 14
   ```

   소매·도매를 둘 다 받는다. **도매는 CSV 가 없어 과거분도 API 로 받아야 한다** — 1년치면:

   ```
   uv run python -m collector.upsert --days 410 --market wholesale
   ```

   410일 × 6부류 ≈ 2,500번 호출이라 40분쯤 걸린다. 끊겨도 다시 돌리면 이어서 메워진다.

'있으면 갱신 · 없으면 추가'(`INSERT ... ON CONFLICT`)라 여러 번 돌려도 중복되지 않고 값만 최신이 된다.

**매일 자동으로 받으려면** — 서버(컨테이너)에서는 `collector` 서비스가 매일 17:30(한국 시각)에
수집 → 점검을 돈다(`collector/scheduler.py`). 이 PC(Windows)에서는 작업 스케줄러에 등록한다 (매일 17:30). PowerShell 에서 `$dir` 만 자기 폴더로 바꿔 실행한다.
`run_fetch.bat` 은 자기 위치로 이동하므로 bat 안의 경로는 고칠 필요가 없다.
수집할 때 DB 가 떠 있어야 한다 — Docker Desktop 을 로그인할 때 자동 시작으로 두고, db 서비스는
`restart: unless-stopped` 라 Docker 가 뜨면 같이 뜬다.

```powershell
$dir = "C:\Users\본인계정\Desktop\Hyun\project_nongsdak"
$action  = New-ScheduledTaskAction -Execute "cmd.exe" -Argument ('/c "' + $dir + '\run_fetch.bat"') -WorkingDirectory $dir
$trigger = New-ScheduledTaskTrigger -Daily -At (Get-Date -Hour 17 -Minute 30 -Second 0)
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries `
              -DontStopIfGoingOnBatteries -ExecutionTimeLimit (New-TimeSpan -Hours 1) `
              -MultipleInstances IgnoreNew
Register-ScheduledTask -TaskName "KAMIS_fetch_1730" -Action $action -Trigger $trigger -Settings $settings
```

| 옵션 | 왜 |
|---|---|
| `-StartWhenAvailable` | 17:30 에 PC 가 꺼져 있었으면 켜질 때 바로 따라잡는다 |
| `-AllowStartIfOnBatteries` · `-DontStopIfGoingOnBatteries` | 기본값은 배터리면 시작 안 함 / 배터리로 바뀌면 중단이라 노트북에서 결번이 된다 |
| `-MultipleInstances IgnoreNew` | 앞 실행이 안 끝났는데 또 뜨는 걸 막는다 |

KAMIS 공표가 17:00 이라 17:30 에 돈다. `--days 7` 로 지난 7일을 다시 받으므로 며칠 꺼져 있던 구멍도 메워진다.

> `run_fetch.bat` 은 **주석까지 ASCII 로만** 쓴다. 한글을 넣으면 `cmd` 가 코드페이지 때문에
> 파일을 잘못 읽어 통째로 깨진다. 자세한 건 [WORKLOG.md](docs/WORKLOG.md).

---

## 서버 DB 백업 — Lightsail 버킷

`.github/workflows/backup.yml` 이 **매일 04:00 (KST)** 서버 runner 에서 `database/backup.sh` 를 돌린다.

| | |
|---|---|
| 덤프 | `pg_dump -Fc` (압축 형식) → `s3://<BACKUP_BUCKET>/backup/YYYY/MM/nongsdak_YYYYMMDD_HHMM.dump` |
| 보관 | 30일. 지난 것은 같은 작업이 지운다 |
| 복원 시험 | 한국 시각 일요일마다 가장 최근 백업을 임시 DB 에 실제로 복원해 운영 DB 와 행 수를 맞춰 보고 지운다 |
| 확인 | 실패하면 Actions 에 빨간불 · GitHub 알림 |

버킷 준비 (Lightsail 콘솔)
1. 스토리지 → 버킷 생성 — 서버와 같은 리전(시드니), 가장 작은 요금제. **모든 객체 비공개**.
2. 버킷 → 권한 → **리소스 액세스 → 인스턴스 연결**. 서버가 키 없이 버킷에 쓴다 (인스턴스 하나에 버킷 연결 하나 — 다른 버킷과 연결돼 있으면 먼저 끊는다).
   연결 뒤 서버에 반영되기까지 몇 분 걸린다.
3. GitHub Variable `BACKUP_BUCKET` 에 버킷 이름.

손으로 되살리기
```
aws s3 cp s3://<버킷>/backup/2026/11/nongsdak_20261120_0400.dump /tmp/x.dump        # 서버에서
docker compose exec -T db sh -c 'pg_restore --clean --if-exists --no-owner -U "$POSTGRES_USER" -d "$POSTGRES_DB"' < /tmp/x.dump
```
`--clean` 은 지금 표를 지우고 백업으로 바꾼다. 표 하나만 되살리려면 `-t tbl_user` 처럼 고른다.

---

## 7. 검사 돌리기

push 하기 전에 로컬에서 CI 와 같은 검사를 돌릴 수 있다.

```
uv run ruff check .     # 린트
uv run pytest           # 시험 — DB 시험은 3단계의 Postgres 를 쓴다
```

DB 시험은 개발 DB(`nongsdak`)를 건드리지 않고 **`nongsdak_test` 를 새로 만들어** 쓴다 (매번 지우고 다시 만든다).
Postgres 가 꺼져 있으면 DB 시험만 건너뛴다. GitHub CI 에서는 Postgres 를 따로 띄워 전부 돌린다.

---

## 화면에서 볼 수 있는 것

| 영역 | 내용 |
|---|---|
| 소매 · 도매 탭 | 누르면 화면 전체가 그 시장으로 바뀐다 |
| 맨 위 띠 | 오늘 조사된 품목이 흘러간다. 마우스를 올리면 멈춘다 |
| 오늘의 상한가 · 하한가 | 오른쪽 위 카드. 직전 조사일 대비 많이 오른/내린 품목 3개씩 |
| 지금 사기 좋아요 | 평년 같은 때보다 많이 싼 품목 |
| 모든 품목 (시세판) | 어제 · 1주 · 평년 대비로 정렬. 누르면 오늘 가격 + 비교 + 90일 추이 차트(평년선 포함) |
| 오늘의 포춘쿠키 | 쿠키를 깨면 품목 하나를 무작위로 추천 |
| 오른쪽 위 버튼 | 로그인 · 회원가입 · 장바구니 · 다크 모드 |

---

## 자주 걸리는 것

| 증상 | 원인과 해결 |
|---|---|
| `connection refused` · `could not connect to server` | DB 가 안 떠 있다. Docker Desktop 실행 → `docker compose up -d db` → `docker compose ps` 가 healthy 인지 |
| `password authentication failed` | `.env` 의 `DB_PASSWORD` 가 DB 를 처음 만들 때와 다르다. 맞추거나, 데이터가 없으면 `docker compose down -v` 후 다시 띄운다 |
| 접속이 몇 초씩 걸림 | `DB_HOST=localhost` 로 돼 있다. `127.0.0.1` 로 바꾼다 (2단계) |
| `port is already allocated` (5432) | 이 PC 에 다른 PostgreSQL 이 돌고 있다. `.env` 의 `DB_PORT` 를 5433 등으로 바꾸고 다시 띄운다 |
| 화면이 "불러오는 중…" 에서 멈춤 | 서버는 떴는데 DB 접속 실패. 터미널에 찍힌 오류 확인 |
| 품목이 93개가 아님 | CSV 를 다 못 넣었다. 4단계 출력의 행 수 확인 |

---

## 알아두면 좋은 것 (데이터 성질)

- **조사는 평일만 있다.** 그래서 '어제'가 실제로는 며칠 전일 수 있고, 화면에 실제 날짜를 함께 적는다.
- **연휴 다음 날은 거의 비어 있다.** 2026-08-17(광복절 뒤 월요일)은 167행 중 29행만 값이 있다.
  축산물만 조사됐고, 원본 CSV 에서부터 `-` 였다.
- **철 지난 품목은 조사가 끊긴다.** 8월 기준 전어·갓·단감·굴·가리비·딸기 6개가 그렇다.
  이 품목을 열면 "지금은 조사가 없는 철입니다" 경고가 뜬다.
- **평년가격은 KAMIS 가 계산해 준 값이다.** 최근 5년 중 최고·최저 해를 뺀 3개년 평균이라,
  적재는 1년치여도 차트의 청록 점선은 5년치 기준선이다. 다만 명목가격이라 물가 보정은 없다.
- **KAMIS 는 코드는 두고 이름만 바꿀 때가 있다.** 계란은 2026-10-27 부터 `특란10구` 가 `XL10구` 가 됐다.
  화면은 코드로 묶고 이름은 가장 최근 것을 쓴다.

더 자세한 내용은 [README.md](README.md) 의 '알려진 함정' 을 볼 것.

---

## Oracle 에서 옮겨 오기 (v1 → v2)

v1.0.0 의 Oracle XE 에 쌓인 데이터(시세 · 수집 이력 · API 원문 · 회원 · 장바구니)를 그대로 옮긴다.
CSV 적재(4단계)와 API 백필(6단계) 대신 쓴다. 한 번만 하면 된다.

1. 3단계까지 해서 빈 Postgres 를 띄운다.
2. Oracle 드라이버는 평소에는 설치하지 않는다(`migrate` 그룹). 이때만 함께 설치해 실행한다 — 아래 명령의 `--group migrate`.
3. `.env` 에 Oracle 접속 정보(`ORACLE_USER` · `ORACLE_PASSWORD` · `ORACLE_HOST` · `ORACLE_PORT` ·
   `ORACLE_SERVICE` · `ORACLE_CLIENT_DIR`)도 남아 있어야 한다. Oracle 11g 라 Instant Client 가 필요하다.
4. 옮긴다.

   ```
   uv run --group migrate python -m database.migrate_from_oracle            # Postgres 가 비어 있어야 한다
   uv run --group migrate python -m database.migrate_from_oracle --replace  # Postgres 를 비우고 다시 옮긴다
   uv run --group migrate python -m database.migrate_from_oracle --verify   # 옮기지 않고 비교만
   ```

   Oracle 은 읽기만 한다. 일련번호는 원래 번호 그대로 넣고, 끝나면 **모든 행을 하나씩 비교**한다.
   14만 행 남짓에 10초쯤 걸린다. 하나라도 다르면 실패로 끝나고, 넣던 도중 실패하면 Postgres 쪽은 통째로 되돌린다.
