# 농스닥 — 내 PC에서 돌려보기

CSV 한 개를 각자 로컬 Oracle 에 올리고 웹서비스를 띄우는 순서다.
처음부터 끝까지 **15분쯤** 걸린다.

---

## 0. 준비물

| | 확인 방법 |
|---|---|
| **Oracle Database XE** 가 돌고 있을 것 | 서비스 목록에서 `OracleServiceXE` 실행 중 |
| **Oracle Instant Client** | 압축 푼 폴더 경로를 기억해 둘 것 (아래 2단계에서 씀) |
| **uv** | `uv --version` — 파이썬 3.11 은 uv 가 알아서 받는다 (1단계) |
| **Git** | `git --version` · 저장소를 받는다: `git clone <저장소주소>` |

원본 CSV(`data/raws/kamis_price_data_20250901_20260818.csv`)는 저장소에 함께 들어 있다.
`.env` 와 `.venv/`, `logs/` 는 들어 있지 않다 — 각자 만든다(1·2단계).

> **Instant Client 가 왜 필요한가** — 이 프로젝트의 Oracle 은 11g 라서 `oracledb` 의
> 기본(thin) 모드로는 접속이 안 된다(`DPY-3010`). Instant Client 를 써서 thick 모드로
> 붙어야 한다. 스크립트가 알아서 전환하지만, **경로는 각자 고쳐야 한다.**

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

## 2. 접속 정보 맞추기 (⚠ 각자 환경에 맞게)

접속 정보는 **`.env` 한 곳**에만 적는다. 코드(`config.py`)가 여기서 읽어 가므로
스크립트를 열어 고칠 필요가 없다. `.env` 는 커밋되지 않는다 (`.gitignore`).

```
Copy-Item .env.example .env
```

만든 `.env` 에서 고칠 값:

| 값 | 설명 |
|---|---|
| `ORACLE_CLIENT_DIR` | **사람마다 다르다.** Instant Client 압축을 푼 폴더로 바꿀 것. `oci.dll` 이 **바로 들어 있는 안쪽 폴더**(`...\instantclient_23_26`)여야 한다 |
| `ORACLE_USER` · `ORACLE_PASSWORD` | 실습 환경(`kdt_admin` / `1234`)과 같다면 지워도 된다 |
| `KAMIS_CERT_KEY` · `KAMIS_CERT_ID` | 6단계에서 채운다. 지금은 비워 둬도 웹서비스는 뜬다 |

값을 찾는 순서는 **환경변수 → `.env` → `config.py` 의 기본값**이다.
Oracle 쪽만 기본값이 있고, KAMIS 인증키는 기본값을 두지 않는다 —
없는 채로 수집기를 돌리면 안 되기 때문이다.

---

## 3. 테이블 만들기

SQL Developer 등에서 `kdt_admin` 으로 접속해 `database/01_create_kamis_table.sql` 을 실행한다.
테이블 1개 · 시퀀스 1개 · 인덱스 3개가 만들어진다.

파일 끝의 확인용 SELECT 로 잘 만들어졌는지 볼 수 있다.

로그인 · 회원가입을 쓰려면 `database/11_create_user.sql` 도 실행한다 (회원 · 세션 테이블).
다른 SQL 과 순서는 상관없다. 안 만들어도 시세 화면은 그대로 뜨고, 로그인만 안 된다.

> **`ORA-01950: no privileges on tablespace` 가 나면** — 계정에 테이블스페이스 권한이 없다.
> DBA 계정으로 아래를 실행한 뒤 다시 시도한다.
> ```sql
> ALTER USER kdt_admin DEFAULT TABLESPACE USERS;
> ALTER USER kdt_admin QUOTA UNLIMITED ON USERS;
> ```

---

## 4. CSV 적재

```
uv run python -m collector.loader
```

이렇게 나오면 성공이다.

```
CSV 읽음: kamis_price_data_20250901_20260818.csv · 43,480행
Oracle 연결 성공 (thick 모드)
적재 완료: 43,480행
기간 2025-09-01 ~ 2026-08-18 · 품목 93개 · 당일가격 있는 행 40,xxx
```

> **`ORA-00001: unique constraint` 가 나면** — 이미 들어 있는 자료가 있다.
> 처음부터 다시 넣으려면 `TRUNCATE TABLE TBL_DAILY_PRICE;` 를 실행하고 다시 돌린다.

---

## 5. 웹서비스 실행

프로젝트 최상위 폴더에서:

```
uv run python -m uvicorn backend.app:app --reload
```

브라우저에서 **http://127.0.0.1:8000** 을 연다.

---

## 6. 최신 날짜 채우기 — KAMIS OpenAPI

여기까지는 CSV 한 개(2026-08-18 까지)를 넣은 상태다. **그 뒤 날짜는 API 로 받는다.**

1. KAMIS 에서 OpenAPI 인증키를 발급받는다 (`p_cert_key` · `p_cert_id`).
2. 최상위에 `.env` 를 만들고 채운다 — `.env.example` 을 복사해 쓰면 된다.

   ```
   KAMIS_CERT_KEY=발급받은키
   KAMIS_CERT_ID=마이페이지의ID
   ```

   `KAMIS_CERT_ID` 는 **로그인 아이디가 아니다.** KAMIS 마이페이지에 따로 나오는 ID 를 넣는다.

3. 수집 이력 테이블을 만들고, 도매·원본 보관 구조를 얹는다 (**순서대로**):
   `database/07_create_fetch_log.sql` → `database/10_add_wholesale_and_raw.sql`
4. 빠진 날짜를 채운다. `--days N` 은 그날부터 거슬러 N일치를 함께 받는다.

   ```
   uv run python -m collector.upsert --days 14
   ```

   소매·도매를 둘 다 받는다. **도매는 CSV 가 없어 과거분도 API 로 받아야 한다** — 1년치면:

   ```
   uv run python -m collector.upsert --days 410 --market wholesale
   ```

   410일 × 6부류 ≈ 2,500번 호출이라 40분쯤 걸린다. 끊겨도 다시 돌리면 이어서 메워진다(MERGE).

`MERGE` 라 여러 번 돌려도 중복되지 않고 값만 최신이 된다.

**매일 자동으로 받으려면** 작업 스케줄러에 등록한다 (매일 17:30). PowerShell 에서 `$dir` 만 자기 폴더로 바꿔 실행한다.
`run_fetch.bat` 은 자기 위치로 이동하므로 bat 안의 경로는 고칠 필요가 없다.

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

## 7. 수집 알림 — Slack (선택)

매일 수집 결과(완료 · 실패 · 빠진 날 경고)를 Slack 채널로 받으려면 **Incoming Webhook** 주소가 하나 필요하다.
`.env` 에 `SLACK_WEBHOOK_URL` 이 비어 있으면 알림만 조용히 건너뛰고 수집은 그대로 돈다.

1. 알림 받을 채널을 만든다.
2. [api.slack.com/apps](https://api.slack.com/apps) → **Create New App → From scratch** → 앱 이름 · 워크스페이스 선택 → **Create App**.
3. 왼쪽 **Incoming Webhooks** → 스위치 **On** → **Add New Webhook to Workspace** → 채널 선택 → **Allow**.
4. 생긴 Webhook URL 을 `.env` 에 넣는다.

   ```
   SLACK_WEBHOOK_URL=https://hooks.slack.com/services/...
   ```

5. PowerShell 에서 테스트한다. `ok` 가 나오고 채널에 글이 뜨면 된 것이다.

   ```powershell
   $url  = "여기에_복사한_웹훅_URL"
   $body = [Text.Encoding]::UTF8.GetBytes('{"text":"농스닥 알림 테스트입니다"}')
   Invoke-RestMethod -Method Post -Uri $url -ContentType "application/json; charset=utf-8" -Body $body
   ```

> **웹훅 URL 은 비밀번호처럼 다룬다** — 이 주소만 알면 누구나 채널에 글을 쓸 수 있다.
> `.env` 에만 두고 커밋하지 않는다. 새어 나갔다면 앱 설정에서 그 웹훅을 지우고(**Remove**) 새로 만든다.

---

## 화면에서 볼 수 있는 것

| 영역 | 내용 |
|---|---|
| 맨 위 띠 | 오늘 조사된 87개 품목이 흘러간다. 마우스를 올리면 멈춘다 |
| 등락 요약 | `▲47 ▼21 ―19` — 오른/내린/보합 품목 수 |
| 품목별 시세 | 검색(초성 가능) → 오늘 가격 + 어제~평년 비교 + 90일 추이 차트(평년선 포함) |
| 하한가 · 상한가 | 많이 내린/오른 품목 5개씩. 어제·일주일·한 달 탭 |
| 오늘의 포춘쿠키 | 쿠키를 깨면 품목 하나를 무작위로 추천 |
| 오른쪽 위 버튼 | 다크 모드 전환 |

---

## 자주 걸리는 것

| 증상 | 원인과 해결 |
|---|---|
| `DPY-3010` | Instant Client 경로(`CLIENT_LIB_DIR`)가 틀렸다. 2단계 확인 — 압축 폴더 바깥쪽을 적은 경우가 많다 |
| `DPI-1047` | Visual C++ 런타임이 없다. `winget install --id Microsoft.VCRedist.2015+.x64 -e` |
| 화면이 "불러오는 중…" 에서 멈춤 | 서버는 떴는데 DB 접속 실패. 터미널에 찍힌 오류 확인 |
| 품목이 93개가 아님 | CSV 를 다 못 넣었다. 4단계 출력의 행 수 확인 |
| 값이 8월 14일까지만 나옴 | 합치기 전 옛 CSV 를 넣었다. 파일명이 `..._20260818.csv` 인지 확인 |

---

## 알아두면 좋은 것 (데이터 성질)

- **조사는 평일만 있다.** 그래서 '어제'가 실제로는 며칠 전일 수 있고, 화면에 실제 날짜를 함께 적는다.
- **연휴 다음 날은 거의 비어 있다.** 2026-08-17(광복절 뒤 월요일)은 167행 중 29행만 값이 있다.
  축산물만 조사됐고, 원본 CSV 에서부터 `-` 였다.
- **철 지난 품목은 조사가 끊긴다.** 8월 기준 전어·갓·단감·굴·가리비·딸기 6개가 그렇다.
  이 품목을 열면 "지금은 조사가 없는 철입니다" 경고가 뜬다.
- **평년가격은 KAMIS 가 계산해 준 값이다.** 최근 5년 중 최고·최저 해를 뺀 3개년 평균이라,
  적재는 1년치여도 차트의 청록 점선은 5년치 기준선이다. 다만 명목가격이라 물가 보정은 없다.

더 자세한 내용은 [README.md](README.md) 의 '알려진 함정' 을 볼 것.
