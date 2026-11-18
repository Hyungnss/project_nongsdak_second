# 농스닥

"지금 이 가격이 평년 대비 어느 수준인가"를 한눈에 보여주는 웹서비스.
KAMIS 일별 **소매·도매** 시세를 PostgreSQL 에 적재해 두고, 오늘 가격과 시점별 변동을 화면에 띄운다.

팀 **다채롭조**의 일별(daily) 파트로 시작한 프로젝트다. 팀 결과물은 원래 저장소에 v1 으로 남겨 두었고,
이 저장소는 그 뒤를 이어 개인 프로젝트로 보완 · 배포한다.

---

## 실행

```
uv run uvicorn backend.app:app --reload
```
→ http://127.0.0.1:8000

검사는 push 하기 전에 로컬에서도 같은 것을 돌릴 수 있다. GitHub 에서는 main push · PR 마다
`.github/workflows/ci.yml` 이 자동으로 돌리고, `v*` 태그를 올리면 검사 통과 후 Release 를 만든다.

```
uv run ruff check .     # 린트 — 정의 안 된 이름 · 안 쓰는 import · 문법 오류
uv run pytest           # 시험 — tests/ (DB · 인증키 없이 돈다)
```

**처음 세팅하는 사람은 [SETUP.md](SETUP.md) 를 볼 것** — Docker 로 PostgreSQL 을 띄워 CSV 를 올리고
서비스를 띄우기까지의 순서와, 자주 걸리는 문제를 정리해 두었다.

---

## 화면 기능

| 영역 | 내용 |
|---|---|
| **소매 · 도매 탭** | 제목 아래. 누르면 화면 전체(띠·등락·검색·시세·급등락·포춘쿠키)가 그 시장으로 바뀐다. 기본은 소매 |
| 맨 위 띠 | 오늘 조사된 품목이 흘러간다. 마우스를 올리면 멈춘다 |
| 등락 요약 | `▲47 ▼21 ―19` — 오른/내린/보합 품목 수 |
| **검색** | 품목명·품종명·등급명 부분일치 + **초성 검색**(`ㅂㅊ` → 배추) |
| **품목별 시세** | 오늘 가격 + 어제/1주일/2주일/1개월/1년전/평년 대비 + 최근 90일 추이 차트 |
| **오늘의 상한가 · 하한가** | 오른쪽 위 카드. 직전 조사일 대비 많이 오른/내린 품목 3개씩. 누르면 그 품목 상세가 열린다 |
| 지금 사기 좋아요 | 평년 같은 때보다 많이 싼 품목 카드 |
| **모든 품목 (시세판)** | 어제 · 1주 · 평년 대비 열 머리를 눌러 정렬. 한 페이지 30개 |
| 오늘의 포춘쿠키 | 쿠키를 깨면 품목 하나를 무작위로 추천 |
| 오른쪽 위 버튼 | **로그인 · 회원가입** (선택) · 다크 모드 전환 |

검색은 `/api/products`로 이미 받아 둔 품종 163개를 클라이언트에서 거르므로 서버 왕복이 없다.
조사가 끊긴 품종에는 `N일째 조사 없음`을 붙여 오늘 시세가 아님을 알린다.
차트는 주식처럼 상승 빨강 / 하락 파랑이고, **평년가를 청록 점선**으로 겹쳐 그린다.

고른 시장은 주소(`?market=wholesale`)와 브라우저에 기억된다 — 새로고침해도, 링크를 건네도 같은 탭으로 열린다.
도매 탭에서는 **단위를 가격 옆에 크게** 적고 위에 안내를 띄운다. 도매 배추는 `10kg(그물망 3포기)` 단위라
'1포기' 소매가와 같은 눈으로 읽으면 안 되기 때문이다. 축산물은 도매 탭에 없다(아래 함정 참고).

---

## 파일

| 파일 | 하는 일 |
|---|---|
| `backend/app.py` | FastAPI 라우트. 화면이 쓰는 것은 `/api/meta`, `/api/products`, `/api/detail`, `/api/briefing` (시세판 · 띠 · 상한가/하한가 · 포춘쿠키가 모두 이 자료를 같이 쓴다). `/api/movers`, `/api/fortune` 은 지금 화면에서 부르지 않는다. 전부 `?market=retail\|wholesale` 를 받는다 (기본 retail) |
| `backend/db.py` | PostgreSQL 조회·집계. 모든 조회가 `MARKET_TYPE` 한 시장 안에서만 돈다. 대표 등급 우선순위 `RANK_PRIORITY`도 여기 있다 |
| `backend/auth.py` | 회원가입 · 로그인 · 로그아웃 (`/api/auth/*`). 다른 API 가 붙여 쓰는 `current_user` · `require_user` 의존성 |
| `frontend/index.html` | 화면 전체 (외부 리소스 0건) |
| `frontend/auth.js` · `auth.css` | 오른쪽 위 로그인 버튼과 팝업. 다른 기능이 쓰는 `window.nongsdaqAuth` |
| `backend/cart.py` | 장바구니 (`/api/cart/*`). 로그인한 회원만 쓴다 |
| `frontend/cart.js` · `cart.css` | 오른쪽 위 장바구니 버튼(로그인했을 때만)과 장바구니 패널, 상세의 '장바구니에 담기' |

---

## 로그인

**시세는 로그인 없이 본다.** 회원은 장바구니 · 레시피 정리처럼 '내 것'을 저장하는 기능에만 필요하다.

| | |
|---|---|
| 가입 정보 | 아이디(영문 소문자·숫자·`_` 4~20자, 대소문자 구분 없음) · 비밀번호(8~64자) · 닉네임(2~20자) |
| 비밀번호 | 표준 라이브러리 `hashlib.scrypt` 해시만 `TBL_USER` 에 저장. 원문은 어디에도 남지 않는다 |
| 로그인 유지 | `TBL_USER_SESSION` + HttpOnly 쿠키 `nongsdaq_session` (14일). 쿠키에는 무작위 토큰만 있고, DB 에는 그 SHA-256 만 둔다. 로그아웃하면 행을 지워 즉시 무효 |
| API | `POST /api/auth/signup` · `POST /api/auth/login` · `POST /api/auth/logout` · `GET /api/auth/me` |

새 기능에서 로그인을 쓰는 법 — 자세한 예시는 `auth.py` · `auth.js` 맨 위 주석에 있다.

```python
# 서버: 로그인 안 했으면 401. 회원 번호는 user["user_no"]
@app.get("/api/cart")
def cart(user: dict = Depends(auth.require_user)): ...
```

```js
// 화면: 로그인 안 했으면 팝업을 띄우고, 로그인하면 user 를 돌려준다 (닫으면 null)
const user = await nongsdaqAuth.require();
```

개인 데이터 테이블은 `TBL_USER.USER_NO` 를 외래키로 건다.
로그인 시도 횟수 제한(무차별 대입 방어)은 아직 없다 — 배포 전에 붙일 것.

---

## 장바구니

로그인하면 오른쪽 위에 **장바구니** 버튼이 생긴다. 누르면 메인 화면 위로 오른쪽에서 패널이 열린다
(휴대폰은 화면 전체). 메인 화면은 그대로다.

| | |
|---|---|
| 테이블 | `TBL_CART_ITEM` (`database/schema.sql`). 회원당 같은 품종 · 등급은 한 줄, 수량 1~99, 최대 50가지 |
| 가격 | 저장하지 않는다. 열 때마다 장보기 브리핑(`/api/briefing`)의 최신 **소매가**를 붙인다. 철 지나 조사가 끊긴 품목은 마지막 조사 가격을 '지금 조사 안 함'과 함께 보여준다 |
| 화면 | 합계 · 지난주 대비 · 평년 대비 막대, 품목마다 '사기 좋은 때 / 평소 가격 / 조금 기다려 보기'(평년 ±10%), 수량 조절 · 빼기 · 비우기, 더 담기, 묶음 담기(김장 · 아침 식탁 · 찌개거리) |
| 담는 곳 | 패널의 '더 담기', 메인 화면 품목 상세의 '장바구니에 담기'(로그인 안 했으면 로그인 창부터) |
| API | `GET /api/cart` · `POST /api/cart` · `POST /api/cart/bulk` · `PATCH /api/cart/{cart_no}` · `DELETE /api/cart/{cart_no}` · `DELETE /api/cart`. 쓰기는 바뀐 뒤의 장바구니 전체를 돌려준다 |

도매는 담지 않는다. 도매가는 10kg · 상자 단위라 장보기 합계에 섞으면 숫자가 의미를 잃는다.

```js
// 다른 화면에서 쓰기 (cart.js 는 auth.js 다음에 불러온다)
nongsdaqCart.open();                       // 패널 열기
nongsdaqCart.add(item, kind, rank, name);  // 한 품목 담기
```

---

## 데이터베이스

PostgreSQL 18 (`docker compose` 의 `db` 서비스). 스키마는 **`database/schema.sql` 한 파일**이다.

`TBL_DAILY_PRICE` — **128,807행** · `2025-09-01 ~ 2026-11-18` (2026-11-18 기준)

| 시장 | 행 | 가격 있는 날 | 품목 · 품종 (화면 기준) |
|---|---|---|---|
| 소매 | 67,216 | 444일 (주말은 축산물만) | 100개 · 163개 |
| 도매 | 61,591 | 295일 | 78개 · 126개 (축산물 없음) |

| 스크립트 | 하는 일 |
|---|---|
| `database/schema.sql` | 테이블 6개 · 인덱스 · 제약 · 컬럼 설명. DB 를 처음 띄울 때 자동 실행 |
| `database/migrate_from_oracle.py` | v1(Oracle) 데이터를 옮기고 모든 행을 비교하는 일회용 도구 |
| `collector/loader.py` | **전체 적재** — 빈 DB 에 CSV 전량을 넣는다 |
| `collector/kamis.py` | KAMIS OpenAPI 호출·응답 해석 (소매 01 / 도매 02). 단독 실행하면 소매 하루치를 CSV 로 떨군다 |
| **`collector/upsert.py`** | **자동 수집의 본체** — 받아서 원문을 `TBL_API_RAW` 에 남기고 `INSERT ... ON CONFLICT` 로 덮어쓴다 |
| `collector/check.py` | 최근 7일 소매·도매 수집 기록 점검 (빈 날이면 슬랙) |

| 테이블 | 담는 것 |
|---|---|
| `TBL_DAILY_PRICE` | 가격. 한 행 = (시장, 조사일, 품목, 품종, 등급). `MARKET_TYPE` 이 `소매`/`도매`. 가격 0 이하는 DB 가 거부한다 |
| `TBL_API_RAW` | KAMIS 응답 원문(JSONB). 호출 1회 = 1행. 직전 원문과 같으면 쌓지 않으므로 **KAMIS 사후 개정 이력**이 된다. 인증키는 `***` 로 가려 저장 |
| `TBL_FETCH_LOG` | 수집 이력. 시장·부류마다 1행 + 시장별 하루 요약 1행 |
| `TBL_USER` | 회원. 아이디 · scrypt 비밀번호 해시 · 닉네임 |
| `TBL_USER_SESSION` | 로그인 세션. 쿠키 토큰의 SHA-256 · 만료 시각. 회원을 지우면 같이 지워진다 |
| `TBL_CART_ITEM` | 장바구니. 회원을 지우면 같이 지워진다 |

**평소에는 아무것도 안 해도 된다.** 작업 스케줄러가 매일 17:30 에 `collector/upsert.py` 를 돌린다.
손으로 돌릴 일이 있으면:

```
uv run python -m collector.upsert [YYYY-MM-DD] [--days N] [--market retail|wholesale|all] [--dry-run]
```

`--market` 을 안 주면 소매·도매 둘 다 받는다 (하루 = 소매 6 + 도매 6 호출).

여러 번 돌려도 중복되지 않고 값만 최신이 된다 (`ON CONFLICT DO UPDATE` + `COALESCE` 라 늦게 온 `-` 가
기존 값을 지우지도 않는다). `--days N` 은 그날부터 거슬러 N일치를 함께 요청한다.

변환 규칙(등급 `-`→`없음`, 가격 `-` · `0`→`NULL`)은 `collector/loader.py` 의 함수를 그대로 import 해 쓴다.
같은 규칙을 두 곳에 적어두면 나중에 한쪽만 고쳐져 데이터가 어긋나기 때문이다.

## 자동 수집

| | |
|---|---|
| 진입점 | `run_fetch.bat` (**ASCII 전용** — 이유는 [WORKLOG.md](docs/WORKLOG.md)) |
| 작업 이름 | `KAMIS_fetch_1730` · 매일 **17:30** · 놓친 실행은 PC 가 켜지면 따라잡음 |
| 받는 범위 | `--days 7` — 오늘부터 거슬러 7일치, **소매·도매 둘 다** (실행 누락 + KAMIS 사후 개정 대응) |
| 점검 | 수집 직후 `check_fetch.bat` 이 최근 7일 소매·도매 기록을 각각 확인하고, 빈 날이 있으면 슬랙으로 알림 |
| 로그 | `logs\fetch.log` · DB 쪽은 `TBL_FETCH_LOG` |

17:30 인 이유는 **KAMIS 공표가 17:00** 이라서다. 그 전에 받으면 축산물밖에 값이 없다.
30분 여유를 두고, 그래도 늦게 올라온 값은 다음 날 `--days 7` 이 다시 받아 메운다.
실행해도 화면에는 아무것도 안 뜬다 — 출력이 전부 로그 파일로 간다.

```powershell
Get-ScheduledTaskInfo -TaskName KAMIS_fetch_1730 | Select LastRunTime, LastTaskResult
Get-Content logs\fetch.log -Tail 20 -Encoding UTF8
```

> **실행 중(17:30 직후 1분쯤)에는 작업 상태를 들여다보지 말 것** — 그 실행이 `^C` 로 죽는다.
> 끝난 뒤 로그로 확인한다. 이유는 [WORKLOG.md](docs/WORKLOG.md).

새 PC 에서 작업을 다시 등록하는 명령은 [SETUP.md](SETUP.md) 6단계에 있다.
`.bat` 은 자기 위치(`%~dp0`)로 이동하므로 경로를 고칠 필요가 없다.

화면 위쪽 최신성 표시는 `TBL_FETCH_LOG` 를 읽는다. 수집이 조용히 죽으면
어제 값이 오늘 값처럼 보이므로, 그걸 막으려고 `/api/meta` 가 `status`·`age_minutes`·`stale` 을 같이 준다.

---

## 알려진 함정

- **Windows 에서 `DB_HOST=localhost` 는 느리다.** IPv6(`::1`)를 먼저 시도하는데 Docker 는 IPv4 에만
  열려 있어 접속마다 몇 초씩 멈춘다. `127.0.0.1` 로 둔다.
- **KAMIS 는 코드는 두고 이름만 바꿀 때가 있다.** 계란은 2026-10-27 부터 `특란10구` → `XL10구`.
  품목 목록을 이름까지 묶으면 한 품종이 둘로 쪼개져 옛 이름이 'N일째 조사 없음' 으로 보인다.
  그래서 (품목, 품종, 등급) **코드로 묶고 이름은 가장 최근 행의 것**을 쓴다.
- **가격 0 은 '조사 없음' 이다.** KAMIS 가 `-` 대신 0 을 줄 때가 있다(닭 절단육). 수집기가 NULL 로 바꾸고,
  DB 도 `CHECK` 로 0 이하를 거부한다.
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
- **소매·도매는 같은 품종·등급 코드를 쓴다.** '배추 · 고랭지 · 상품' 이 양쪽에 다 있다.
  그래서 자연키에 `MARKET_TYPE` 이 들어가고, `db.py` 의 모든 조회가 시장 조건을 건다.
  하나라도 빠지면 '1포기' 소매가와 '10kg' 도매가가 한 차트·한 순위에 섞인다.
- **도매 축산물은 KAMIS 가 소매 값을 그대로 돌려준다.** `p_product_cls_code=02` 로 축산물(500)을
  요청해도 data 가 소매와 완전히 같다 (세 날짜로 확인). `collector/upsert.py` 가 같은 날 소매 응답과 비교해 같으면
  건너뛴다 — 원문만 `TBL_API_RAW` 에 남는다. KAMIS 가 따로 주기 시작하면 비교가 달라져 저절로 들어간다.
  같은 날 소매 축산물이 실패했거나 `--market wholesale` 로 돌리면 비교할 값이 없으므로 그 자리에서
  소매 축산물을 한 번 더 받아 비교한다. 그것도 실패하면 넣지 않고 ERROR 로 남긴다
  (예전에는 그대로 넣어 2026-02-15 에 도매 축산물 29행이 생겼다 — WORKLOG 2026-10-16).
- **KAMIS 응답의 `condition` 에 인증키가 그대로 돌아온다.** 원문을 저장·출력할 때는 반드시
  `collector/kamis.py` 의 `mask()` / `raw_text()` 를 거칠 것.

---

## 폴더 구조

```
project_nongsdak/
├── backend/                     FastAPI 서버 — app.py(라우트) db.py(조회) auth.py(로그인) cart.py(장바구니)
├── frontend/                    화면 — index.html · auth.js/css · cart.js/css · 이미지. 주소는 /static/...
├── collector/                   KAMIS 수집 — kamis.py(API 호출) loader.py(변환 · CSV 전체 적재)
│                                upsert.py(매일 수집 본체) check.py(수집 점검) notify.py(슬랙)
├── database/                    schema.sql(PostgreSQL 스키마) · migrate_from_oracle.py · oracle/(v1 DDL 보관)
├── data/raws/                   원본 CSV (수정 금지)
├── logs/                        fetch.log — 자동 수집 로그 (커밋 안 함)
├── tests/                       pytest — 순수 로직 · API(가짜 DB) · 실제 PostgreSQL 시험
├── config.py                    DB 접속정보·KAMIS 인증키를 한 곳에서 읽는다 (backend · collector 공용)
├── .env                         인증키·비밀번호 (커밋 안 함 / .env.example 참고)
├── docker-compose.yml           PostgreSQL (db 서비스)
├── run_fetch.bat                작업 스케줄러 진입점 (ASCII 전용) — collector.upsert → collector.check
├── check_fetch.bat              수집 점검만 따로 돌릴 때
├── README.md
├── SETUP.md                     처음 세팅하는 사람용
├── docs/WORKLOG.md              날짜별 작업 기록 (무엇을 왜 그렇게 정했는지)
├── pyproject.toml · uv.lock      의존성 (uv 로 관리 — 설치는 `uv sync`)
└── .python-version              파이썬 3.11
```

## 실행 환경

Python 3.11 · fastapi · uvicorn · psycopg 3 (+ psycopg-pool) · pandas(적재 스크립트에서만 사용)
PostgreSQL 18.7 (Docker) · 의존성은 uv 로 고정 (`uv.lock`)

## 앞으로

**KAMIS OpenAPI 자동 수집 전환은 2026-09-02 에 끝났다** — 사람이 CSV 를 받아 옮기는 과정은
없어졌고, 매일 17:30 에 저절로 갱신된다. 날짜별 기록과 결정 근거는 [WORKLOG.md](docs/WORKLOG.md) 에 있다.

2026-11 에 Oracle XE 11g 에서 PostgreSQL 로 옮겼다 (v2). 남은 것은 **배포**다 —
웹 · 수집기 · DB 를 docker compose 로 묶고, `v*` 태그가 올라오면 AWS Lightsail 서버에 배포한다.
