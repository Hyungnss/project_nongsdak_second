# 농스닥

"지금 이 가격이 평년 대비 어느 수준인가"를 한눈에 보여주는 웹서비스.
KAMIS 일별 소매 시세를 Oracle 에 적재해 두고, 오늘 가격과 시점별 변동을 화면에 띄운다.

팀 **다채롭조**에서 월별/주별/일별로 나눠 맡았고, 이 저장소는 **일별(daily)** 파트다.

---

## 실행

```
.venv\Scripts\python.exe -m uvicorn webservice.app:app --reload
```
→ http://127.0.0.1:8000

**처음 세팅하는 사람은 [SETUP.md](SETUP.md) 를 볼 것** — CSV 를 각자 로컬 Oracle 에 올리고
서비스를 띄우기까지의 순서와, 자주 걸리는 문제를 정리해 두었다.

---

## 화면 기능

| 영역 | 내용 |
|---|---|
| 맨 위 띠 | 오늘 조사된 품목이 흘러간다. 마우스를 올리면 멈춘다 |
| 등락 요약 | `▲47 ▼21 ―19` — 오른/내린/보합 품목 수 |
| **검색** | 품목명·품종명·등급명 부분일치 + **초성 검색**(`ㅂㅊ` → 배추) |
| **품목별 시세** | 오늘 가격 + 어제/1주일/2주일/1개월/1년전/평년 대비 + 최근 90일 추이 차트 |
| **하한가 · 상한가** | 많이 내린/오른 품목 5개씩. 어제·일주일·한 달 탭 |
| 오늘의 포춘쿠키 | 쿠키를 깨면 품목 하나를 무작위로 추천 |
| 오른쪽 위 버튼 | 다크 모드 전환 |

검색은 `/api/products`로 이미 받아 둔 품종 162개를 클라이언트에서 거르므로 서버 왕복이 없다.
조사가 끊긴 품종에는 `N일째 조사 없음`을 붙여 오늘 시세가 아님을 알린다.
차트는 주식처럼 상승 빨강 / 하락 파랑이고, **평년가를 청록 점선**으로 겹쳐 그린다.

---

## 파일

| 파일 | 하는 일 |
|---|---|
| `webservice/app.py` | FastAPI 라우트 (`/api/meta`, `/api/products`, `/api/detail`, `/api/movers`, `/api/fortune`) |
| `webservice/db.py` | Oracle 조회·집계. 대표 등급 우선순위 `RANK_PRIORITY`도 여기 있다 |
| `webservice/static/index.html` | 화면 전체 (외부 리소스 0건, 단독 파일) |

---

## 데이터베이스

`TBL_DAILY_PRICE` — **45,909행** · `2025-09-01 ~ 2026-09-02` · 조사일 267일 · 품목 100개 · 품종 163개

| 스크립트 | 하는 일 |
|---|---|
| `database/01_create_kamis_table.sql` | 테이블·시퀀스·인덱스 생성 (컬럼 주석 포함) |
| `database/02_insert_daily_price.py` | **전체 적재** — `TRUNCATE` 후 CSV 전량을 다시 넣는다 |
| `database/04_insert_new_days.py` | **증분 적재** — DB에 없는 조사 건만 골라 이어붙인다 (CSV용) |
| `database/05_fetch_kamis.py` | KAMIS OpenAPI 로 하루치를 받아 CSV 모양으로 만든다 (DB는 안 건드림) |
| **`database/06_upsert_daily_price.py`** | **자동 수집의 본체** — 받아서 `MERGE` 로 덮어쓴다 |
| `database/07_create_fetch_log.sql` | 수집 이력 테이블 `TBL_FETCH_LOG` |
| `database/09_verify_against_csv.py` | API 값과 원본 CSV 값 대조 |

**평소에는 아무것도 안 해도 된다.** 작업 스케줄러가 매일 17:30 에 `06` 을 돌린다.
손으로 돌릴 일이 있으면:

```
.venv\Scripts\python.exe database\06_upsert_daily_price.py [YYYY-MM-DD] [--days N] [--dry-run]
```

여러 번 돌려도 중복되지 않고 값만 최신이 된다 (`MERGE` + `NVL` 이라 늦게 온 `-` 가
기존 값을 지우지도 않는다). `--days N` 은 그날부터 거슬러 N일치를 함께 요청한다.

변환 규칙(등급 `-`→`없음`, 가격 `-`→`NULL`)은 `02`의 함수를 importlib로 불러 쓴다.
같은 규칙을 두 곳에 적어두면 나중에 한쪽만 고쳐져 데이터가 어긋나기 때문이다.

## 자동 수집

| | |
|---|---|
| 진입점 | `run_fetch.bat` (**ASCII 전용** — 이유는 [WORKLOG.md](WORKLOG.md)) |
| 작업 이름 | `KAMIS_fetch_1730` · 매일 **17:30** · 놓친 실행은 PC 가 켜지면 따라잡음 |
| 받는 범위 | `--days 7` — 오늘부터 거슬러 7일치 (실행 누락 + KAMIS 사후 개정 대응) |
| 점검 | 수집 직후 `check_fetch.bat` 이 최근 7일 기록을 확인하고, 빈 날이 있으면 슬랙으로 알림 |
| 로그 | `logs\fetch.log` · DB 쪽은 `TBL_FETCH_LOG` |

17:30 인 이유는 **KAMIS 공표가 17:00** 이라서다. 그 전에 받으면 축산물밖에 값이 없다.
30분 여유를 두고, 그래도 늦게 올라온 값은 다음 날 `--days 7` 이 다시 받아 메운다.
실행해도 화면에는 아무것도 안 뜬다 — 출력이 전부 로그 파일로 간다.

```powershell
Get-ScheduledTaskInfo -TaskName KAMIS_fetch_1730 | Select LastRunTime, LastTaskResult
Get-Content logs\fetch.log -Tail 20 -Encoding UTF8
```

> **실행 중(17:30 직후 1분쯤)에는 작업 상태를 들여다보지 말 것** — 그 실행이 `^C` 로 죽는다.
> 끝난 뒤 로그로 확인한다. 이유는 [WORKLOG.md](WORKLOG.md).

새 PC 에서 작업을 다시 등록하는 명령은 [REALTIME_MIGRATION.md](REALTIME_MIGRATION.md) 7단계에 있다.
`.bat` 은 자기 위치(`%~dp0`)로 이동하므로 경로를 고칠 필요가 없다.

화면 위쪽 최신성 표시는 `TBL_FETCH_LOG` 를 읽는다. 수집이 조용히 죽으면
어제 값이 오늘 값처럼 보이므로, 그걸 막으려고 `/api/meta` 가 `status`·`age_minutes`·`stale` 을 같이 준다.

---

## 알려진 함정

- **Oracle 11g라 `thin` 모드로 못 붙는다.** `oracledb`가 `DPY-3010`을 내므로 Instant Client로
  thick 모드 전환이 필요하다. 커넥션 풀은 지연 접속이라 **풀 생성 전에 단일 연결로 모드를
  판별**해야 폴백이 걸린다.
- **`FETCH FIRST ... ROWS ONLY`를 못 쓴다** (12c 문법). `ROWNUM`을 쓸 것.
- **비교 시점을 저장 컬럼(`PRICE_1D` 등)으로 계산하면 안 된다.** 연휴 뒤에는 비어 있다.
  그 품종의 **조사 이력에서 직전 조사일**을 찾아 쓰고, 목표 간격과 다르면 실제 날짜를 화면에 적는다.
- **조사는 평일만 있다.** '어제'가 실제로는 며칠 전일 수 있다.
- **연휴 다음 조사일은 당일가격이 거의 비어 있다.** 2026-08-17(광복절 연휴 뒤 월요일)은
  167행 중 29행만 값이 있다(결측 **82.6%**, 평소는 2~6%). 값이 있는 건 축산물뿐이고,
  원본 CSV에서부터 `-`이므로 적재 실수가 아니다.
- **비교 시점은 품목마다 다르다.** 연휴와 무관한 '한 달 전' 탭도 07-20~07-22로 갈린다.
  그래서 급등락 요약은 한 날짜가 아니라 **범위**(`prev_from`/`prev_to`)로 표시한다.
- **기본 품종은 `최근 조사일 → 최근 자료량 → 이름순`으로 고른다.** 이름순으로만 고르면
  배추가 '가을'(2025-12 이후 조사 없음)로 잡혀 8개월 전 가격을 오늘 시세처럼 보여준다.
- **급등락은 최근 3일 내 조사된 품종만 집계한다.** 철 지나 조사가 끊긴 품종이 53개인데,
  그냥 두면 몇 주 떨어진 마지막 두 관측의 변동률이 '오늘의 변동'처럼 1위로 올라온다.
- **등급 필드에 등급이 아닌 값이 20.5% 섞여 있다** (부위·원산지·제품형태).
- **평년가격은 KAMIS가 계산해 준 값이다.** 최근 5년 중 최고·최저 연도를 뺀 3개년 평균이라,
  적재는 1년치여도 화면에는 5년치 기준선이 뜬다. 다만 **명목가격이라 물가 보정이 없다.**
- **원본 CSV는 절대 덮어쓰지 않는다.** 합칠 때도 새 파일로 만들고 건수를 로그에 남긴다.

---

## 폴더 구조

```
project_grocery_price_insights_service/
├── webservice/                  FastAPI 서비스
│   ├── app.py  db.py
│   └── static/index.html
├── database/                    Oracle DDL·적재·수집 스크립트
├── raws/                        원본 CSV (수정 금지)
├── logs/                        fetch.log — 자동 수집 로그 (커밋 안 함)
├── config.py                    Oracle 접속정보·KAMIS 인증키를 한 곳에서 읽는다
├── .env                         인증키·비밀번호 (커밋 안 함 / .env.example 참고)
├── run_fetch.bat                작업 스케줄러 진입점 (ASCII 전용)
├── README.md
├── SETUP.md                     처음 세팅하는 사람용
├── REALTIME_MIGRATION.md        KAMIS OpenAPI 자동 수집 — 전환 과정과 결정 근거
├── WORKLOG.md                   날짜별 작업 기록
└── requirements.txt
```

## 실행 환경

Python 3.11 · fastapi · uvicorn · oracledb · pandas(적재 스크립트에서만 사용)
Oracle Database XE 11g + Instant Client (thick 모드 필수)

## 앞으로

**KAMIS OpenAPI 자동 수집 전환은 2026-09-02 에 끝났다** — 사람이 CSV 를 받아 옮기는 과정은
없어졌고, 매일 17:30 에 저절로 갱신된다. 과정과 결정 근거는
[REALTIME_MIGRATION.md](REALTIME_MIGRATION.md), 날짜별 기록은 [WORKLOG.md](WORKLOG.md) 에 있다.

남은 것은 **배포**다. 지금은 이 PC 가 켜져 있을 때만 돌고 Oracle XE 도 로컬이라,
남이 접속하려면 서버와 DB 이전이 따로 필요하다.
