# 농스닥 — KAMIS OpenAPI 실시간 전환 계획

지금 서비스는 **사람이 받아 둔 CSV 한 개**(`raws/kamis_price_data_20250901_20260818.csv`)를
Oracle 에 적재해 돌린다. 이 문서는 그 자리에 **KAMIS OpenAPI 자동 수집**을 끼워 넣어
매일 최신 시세가 저절로 갱신되게 만드는 순서다.

이 문서의 모든 경로는 **프로젝트 최상위 폴더 기준**이다.

---

## 진행 상황 (2026-09-02 09:15 기준)

> **2026-10-15 현재:** 매일 **17:30** · 작업 이름 `KAMIS_fetch_1730` · `--days 7` 로 돈다.
> 수집 직후 `check_fetch.bat` 이 최근 7일을 점검한다. 아래 18:00 · `--days 3` 은 09-02 당시 기록이다.
> 바뀐 경위는 [WORKLOG.md](WORKLOG.md).

**1~9단계를 전부 끝냈다. 스케줄러가 실제로 도는 것까지 확인했다.**
16:59 에 작업 스케줄러로 실행해 543행 수집·반영, 09-02 당일가격이 29 -> 176 건이 됐다.
이제 사람이 손댈 것 없이 매일 18:00 에 저절로 갱신된다.

| 단계 | 상태 |
|---|---|
| 0 · 기존 환경 | **완료** |
| 1 · 인증키 발급 | **완료** — `.env` 에 넣어 뒀다 (커밋 안 됨) |
| 2 · 비밀값 분리 | **완료** — `config.py` |
| 3 · 응답 확인 | **완료** — `05_fetch_kamis.py --probe` |
| 4 · 수집 스크립트 | **완료** — `05_fetch_kamis.py` |
| 5 · UPSERT | **완료** — `06_upsert_daily_price.py` |
| 6 · 수집 로그 | **완료** — `07_create_fetch_log.sql` · 테이블 생성됨 |
| 7 · 스케줄러 | **완료** — `run_fetch.bat` · `KAMIS_fetch_1800` (매일 18:00 · 실행 확인됨) |
| 8 · 서비스 손보기 | **완료** — 8-1~8-5 전부 |
| 9 · 검증 | **완료** — `09_verify_against_csv.py` 통과 |

현재 DB: `TBL_DAILY_PRICE` **45,909행** · `2025-09-01 ~ 2026-09-02` (연속)

2026-09-02 에 함께 처리한 것:

- `06` 에 **`--days N`** 을 붙였다. 스케줄러는 `--days 3` 으로 돈다 (오늘·어제·그저께).
- `webservice/db.py` 의 **`TOLERANCE[1]` 을 6 -> 11** 로 올렸다. 10일 연휴까지 견딘다.

### 실제로 해 보고 알게 된 것 (계획과 달랐던 것)

| 계획서 내용 | 실제 |
|---|---|
| 응답 필드가 `itemcode` · `kindcode` | **`item_code` · `kind_code` 다.** 그대로 짰다가 가드에 걸려 175행이 전부 버려졌다 |
| `error_code` 가 최상위에 있음 | **`data` 안에 있다** (정상은 `'000'`) |
| 품종명 `(단위)` 규칙이 수집기가 만든 것일 수 있음 | **API 가 원래 그렇게 준다.** 채소류는 `여름(고랭지)(1포기)`, 축산물은 `안심`. `append_unit_except_livestock` 그대로 두면 된다 |
| 12:00 / 16:00 / 18:00 세 번 | **17:00 공표라 12:00·16:00 은 헛돈다.** 18:00 한 번으로 충분 |
| 1년치 CSV 로 충분 | **CSV 가 08-18 에서 끝나 08-19~08-31 이 비어 있었다.** API 로 메웠다 (2,061행) |

### 미리 확인해 둔 것 (코드 없이 조사한 사실)

| 확인한 것 | 결과 |
|---|---|
| 이 DB 버전 | Oracle 11g XE **11.2.0.2** · thin 미지원이라 Instant Client 로 thick 전환 필요 |
| MERGE 의 INSERT 절에 `SEQ_DAILY_PRICE.NEXTVAL` | **된다.** `ORA-02287` 안 남 — 선채번 우회 불필요 |
| `executemany` + 이름 바인드로 MERGE | 된다 |
| `NVL(:price, t.PRICE)` 로 늦게 온 NULL 방어 | 기존 값이 지켜진다 — 실제 적재로도 재확인했다 |
| 품종명에 `(단위)` 가 붙는 규칙 | **부류별로 갈린다. 예외 0건** — 아래 4단계의 함정 참조 |
| 서비스 동작 | `/api/meta`·`/api/products`·`/api/detail`·`/api/movers`·`/api/fortune` 정상 |

---

## 결정 사항과 남은 일 (2026-09-02 기준)

1~4 는 전부 마무리됐다. 실제로 남은 것은 5(배포) 하나뿐이다.
지나간 항목도 **왜 그렇게 정했는지** 때문에 지우지 않고 남겨 둔다.

### 1. 스케줄러 — 완료 (2026-09-02 16:59 확인)

`KAMIS_fetch_1800` 을 GUI 에서 실행해 전 구간이 도는 것을 확인했다.
543행 수집·반영, `DB 의 2026-09-02: 184행 · 당일가격 있는 행 176`(실행 전 29).

**실행해도 화면에는 아무것도 안 뜬다.** `run_fetch.bat` 이 출력을 전부
`>> logs\fetch.log` 로 돌리기 때문이다. 진행 상황은 로그로 본다:

```powershell
Get-ScheduledTaskInfo -TaskName KAMIS_fetch_1730 | Select LastRunTime, LastTaskResult
Get-Content logs\fetch.log -Tail 20 -Encoding UTF8
```

`LastTaskResult` 가 **0** 이고 `fetch.log` 에 `===== 시각 =====` 이 새로 찍혔으면 정상이다.
한 번 도는 데 20~30초 걸리고, GUI 의 '마지막 실행 결과' 열은 `F5` 를 눌러야 갱신된다.

> **도는 중에 상태를 폴링하지 말 것.** 실행 중에 다른 셸에서 작업 상태를 들여다보면
> 그 실행이 `0xC000013A`(^C)로 죽는다. 여러 번 재현했고, 아무도 안 볼 때 돌린
> 16:59 실행만 `^C` 없이 완주했다. 작업 자체의 결함이 아니다. 확인은 끝난 뒤에 한다.

### 2. `--days N` — 결정 완료 (`--days 3`)

하루 한 번 실행은 **그날 날짜만** 요청한다. 실행을 한 번 놓치면 그날은 영영 빈칸이다
(다음날 실행은 어제가 아니라 오늘을 요청하므로). 금요일 저녁부터 PC 를 꺼 두면 금·토·일이 빈다.

`06` 에 `--days N` 을 붙였고, `run_fetch.bat` 은 **`--days 3`** 으로 돈다.
덤으로 KAMIS 의 사후 개정도 따라간다 (2026-08-18 을 다시 받아 보니 물오징어 원양(냉동)/中
5,271 -> 5,258, 꽃게 1년전·평년 `-` -> 19,511 로 바뀌어 있었다).

주말을 겨냥한 게 아님에 주의 — 토·일은 9일 뒤에 다시 받아도 축산물 29행 그대로다.
연휴 대응은 이게 아니라 아래 3번이다.

### 3. 긴 연휴 다음 첫 조사일 — 해결 (`TOLERANCE[1] = 11`)

`TOLERANCE[1] = 6`(`webservice/db.py`) 이던 때는 **조사일 간격이 7일을 넘으면
`_compare_all` 이 모든 품목을 걸러냈다.** 6일 이상 연휴 다음 첫 조사일에
급등락·등락 요약·티커·포춘쿠키가 통째로 비었다 (품목별 시세 상세는 정상).

시뮬레이션으로 확인한 값:

| 연휴 | 조사일 간격 | 급등락 (고치기 전) |
|---|---|---|
| 5일 | 6일 | 정상 |
| **6일** | **7일** | **0개** |
| 9일 | 10일 | 0개 |

**`TOLERANCE[1]` 을 11 로 올렸다 — 10일 연휴(간격 11일)까지 견딘다.**
철 지난 품종이 섞일 걱정은 없다 — 그건 `_compare_all` 의 `max_stale`(3일)이 따로 거른다.

### 4. 인증키 — 재발급하지 않기로 했다 (2026-09-02 결정)

`--probe` 가 응답의 `condition`(KAMIS 가 요청 파라미터를 되돌려주는 필드)을 그대로 출력하는
바람에 인증키가 터미널에 한 번 찍혔다. **마스킹은 고쳤고**(`05_fetch_kamis.py` 의 `mask()`),
**지금 키를 그대로 쓴다.** 다시 제안하지 말 것.

노출 범위가 그 터미널 출력 한 번이고 밖으로 내보낸 적이 없다면 실질 위험은 낮다.
KAMIS 키는 결제·개인정보가 아니라 조회 API 호출 권한이다.

대신 이상 징후는 `TBL_FETCH_LOG` 로 본다. 내가 안 돌린 시각에 수집 기록이 있거나
호출 한도 관련 오류가 뜨면 그때 재발급한다 (`.env` 한 줄만 바꾸면 되고 코드는 손 안 댄다).

### 5. 그 뒤 — 배포

7단계까지 끝나도 **이 PC 가 켜져 있을 때만 도는 상태**다. 로컬 Oracle XE 도 마찬가지다.
남이 접속할 수 있는 서비스로 만들려면 서버와 DB 이전이 따로 필요하다. 이 문서 범위 밖이다.

---

## 먼저 짚을 것 — "실시간"의 실체

KAMIS 일별 소매가격은 **하루 한 번 공표되는 조사 자료**다. 초·분 단위로 변하는 값이 아니다.
그래서 이 프로젝트에서 실현 가능한 "실시간"은 다음 두 가지다.

| | 내용 |
|---|---|
| **자동 최신화** | 사람이 CSV 를 받아 옮기는 과정을 없애고, 스케줄러가 매일 최신 조사분을 DB 에 넣는다 |
| **최신성 표시** | 화면에 "언제 조사된 값인지 / 언제 갱신했는지"를 띄워 신선도를 보이게 한다 |

공표 시각 전에 부르면 당일 값이 비어 있다. 그래서 **하루에 여러 번 부르고, 값이 채워지면
덮어쓰는 구조**가 필요하다. 이게 이 계획에서 기존 적재 스크립트와 가장 크게 갈리는 지점이다
(→ 5단계).

---

## 방식 선택 — DB 적재형으로 간다

| | 방식 | 판단 |
|---|---|---|
| **A** | 수집기가 API → Oracle 에 넣고, 서비스는 지금처럼 DB 만 본다 | **이걸 쓴다** |
| B | 화면 요청이 올 때마다 서비스가 KAMIS 를 직접 호출한다 | 쓰지 않는다 |

B 를 버리는 이유는 셋이다.

- `webservice/db.py` 의 비교 로직은 **조사 이력 테이블을 전제**로 한다. 연휴 뒤 `PRICE_1D` 가
  비는 문제를 "직전 조사일을 이력에서 찾아서" 푸는 구조라(`db.py:191` `_nearest`),
  하루치 응답만으로는 성립하지 않는다.
- 90일 추이 차트는 90일치 이력이 있어야 그린다. API 는 하루치씩만 준다.
- 사용자가 누를 때마다 외부 API 를 때리면 KAMIS 가 느리거나 죽었을 때 서비스가 같이 죽는다.

A 로 가면 **기존 `webservice/` 코드는 거의 그대로 쓴다.** 새로 만드는 건 수집기 하나다.

---

## 순서

### 0단계 · 지금 상태를 먼저 완성해 둔다

[`SETUP.md`](SETUP.md) 의 0~5단계(Oracle 테이블 생성 → CSV 1년치 적재 → 서비스 기동)가
끝나 있어야 한다. 실시간 전환은 그 위에 얹는 것이지 대체가 아니다.

**1년치 과거 데이터는 API 로 다시 받지 않는다.** 하루에 한 번씩 252번 부르는 셈이라
받는 것보다 이미 있는 CSV 를 쓰는 게 빠르고 안전하다. API 는 **오늘부터 앞으로**만 담당한다.

---

### 1단계 · 인증키 발급

1. [kamis.or.kr](https://www.kamis.or.kr) 회원가입
2. **고객센터 > Open-API > Open-API 이용신청** 에서 신청
3. 발급되면 두 값을 받는다

| 값 | 파라미터명 | 설명 |
|---|---|---|
| 인증키 | `p_cert_key` | 신청 후 발급되는 문자열 |
| 요청자 ID | `p_cert_id` | **로그인 아이디가 아니다.** KAMIS 마이페이지에 따로 나오는 ID |

승인에 시간이 걸릴 수 있으니 **이 단계를 제일 먼저 시작한다.** 기다리는 동안 2·3단계를 진행한다.

---

### 2단계 · 비밀값을 코드 밖으로 뺀다

지금 접속 정보가 소스에 그대로 박혀 있다.

- `webservice/db.py:18` — `USER, PASSWORD = "kdt_admin", "1234"`
- `database/02_insert_daily_price.py:32` — 같은 값
- `CLIENT_LIB_DIR` — 사람마다 경로가 다른데 파일 두 곳에 중복

여기에 API 키까지 더하면 관리가 안 된다. **한 곳으로 모은다.**

`config.py` 를 새로 만든다.

```python
"""접속 정보와 인증키를 한 곳에서 읽는다. 값은 환경변수, 없으면 기본값."""
import os

# Oracle
DB_USER      = os.getenv("ORACLE_USER", "kdt_admin")
DB_PASSWORD  = os.getenv("ORACLE_PASSWORD", "1234")
DB_DSN       = {"host": os.getenv("ORACLE_HOST", "localhost"),
                "port": int(os.getenv("ORACLE_PORT", "1521")),
                "service_name": os.getenv("ORACLE_SERVICE", "xe")}
CLIENT_LIB_DIR = os.getenv(
    "ORACLE_CLIENT_DIR",
    r"C:\instantclient-basic-windows.x64-23.26.3.0.0\instantclient_23_26")

# KAMIS OpenAPI — 기본값을 두지 않는다. 없으면 즉시 터지게 한다.
KAMIS_CERT_KEY = os.environ["KAMIS_CERT_KEY"]
KAMIS_CERT_ID  = os.environ["KAMIS_CERT_ID"]
```

그리고 `db.py`·`02_insert_daily_price.py` 의 상수를 `from config import ...` 로 바꾼다.

환경변수는 PowerShell 에서 이렇게 심는다 (영구 설정).

```powershell
[Environment]::SetEnvironmentVariable("KAMIS_CERT_KEY", "발급받은키", "User")
[Environment]::SetEnvironmentVariable("KAMIS_CERT_ID",  "내아이디",   "User")
```

> 인증키를 커밋하지 않는다. `.env` 파일로 관리한다면 `.gitignore` 에 먼저 넣고 시작할 것.

---

### 3단계 · 응답을 눈으로 한 번 본다 (건너뛰지 말 것)

코드를 짜기 전에 브라우저 주소창에 아래를 넣고 실제 응답을 본다.
문서보다 **실제 응답이 먼저**다.

```
http://www.kamis.or.kr/service/price/xml.do?action=dailyPriceByCategoryList
  &p_cert_key=발급키&p_cert_id=내아이디&p_returntype=json
  &p_product_cls_code=01&p_item_category_code=200
  &p_regday=2026-08-18&p_convert_kg_yn=N
```

확인할 것 다섯 가지.

| 확인 | 왜 |
|---|---|
| `data` 가 객체인가 리스트인가 | 자료가 없는 날은 `"data": []` 로 오는 경우가 있다. 객체로만 가정하면 터진다 |
| `error_code` 값 | 정상/무자료를 코드로 구분해야 스케줄러가 실패를 오판하지 않는다 |
| `item` 이 1건일 때의 모양 | 리스트가 아니라 객체 하나로 오는 API 가 흔하다 |
| `dpr1` 의 생김새 | `"60,256"` 처럼 콤마가 들어 있고 결측은 `"-"` 다 |
| `rank` 의 `-` | 수산물에 많다. 적재할 때 `'없음'` 으로 바꿔야 한다 (아래 참조) |

---

### 4단계 · 수집 스크립트를 만든다 — `database/05_fetch_kamis.py`

**핵심은 "API 응답을 기존 CSV 와 똑같은 17컬럼 DataFrame 으로 만드는 것"** 이다.
그렇게만 하면 `02_insert_daily_price.py` 의 `build_rows()` 를 그대로 재사용할 수 있고,
변환 규칙(등급 `-`→`없음`, 가격 `-`→`NULL`)이 한 곳에만 남는다.

#### 컬럼 매핑

| CSV 컬럼 | API 필드 | 주의 |
|---|---|---|
| 조사일자 | *(응답에 없음)* | 요청한 `p_regday` 를 그대로 채운다 |
| 구분 | *(응답에 없음)* | `p_product_cls_code=01` → 문자열 `"소매"` |
| 부류명 / 부류코드 | *(응답에 없음)* | 요청한 `p_item_category_code` 와 코드표에서 채운다 |
| 품목코드 | `itemcode` | |
| 품목명 | `item_name` | |
| 품종코드 | `kindcode` | 품목 안에서만 유일하다. 단독으로 쓰지 말 것 |
| 품종명 | `kind_name` | **⚠ 아래 함정 참조** |
| 등급 | `rank` | `-` 는 `build_rows` 가 `'없음'` 으로 바꾼다 |
| 단위 | `unit` | |
| 당일가격 | `dpr1` | |
| 1일전가격 | `dpr2` | |
| 1주일전가격 | `dpr3` | |
| 2주일전가격 | `dpr4` | |
| 1개월전가격 | `dpr5` | |
| 1년전가격 | `dpr6` | |
| 평년가격 | `dpr7` | |

> **⚠ 가장 걸리기 쉬운 함정 — 품종명 규칙이 부류마다 다르다**
>
> 기존 43,480행을 전부 조사한 결과, 품종명 끝에 `(단위)` 가 붙는지가 **부류에 따라
> 정확히 갈린다. 예외 0건이다.**
>
> | 부류 | 행 수 | `(단위)` 접미사 | 예시 (단위) |
> |---|---|---|---|
> | 100·200·300·400·600 | 36,172 | **100% 붙음** | `여름(고랭지)(1포기)` · `흰 콩(국산)(500g)` |
> | **500 축산물** | 7,308 | **0% 붙음** | `안심` (100g) · `삼겹살` (100g) · `흰우유` (1L) |
>
> 그래서 `f"{kind_name}({unit})"` 로 일괄 처리하면 **축산물 7,308행이 어긋난다.**
>
> 이 차이가 API 에서 온 것인지 예전 수집기가 붙인 것인지는 실제 응답을 봐야 안다.
> 그래서 `config.KAMIS_KIND_NAME_MODE` 로 갈아끼울 수 있게 해 두고,
> 기본값을 **`append_unit_except_livestock`** 으로 둔다. 이 규칙은
> "이미 `(단위)` 로 끝나면 다시 붙이지 않는다" 는 가드가 있어 **두 경우 모두에서 맞는다.**
>
> | | API 가 `여름(고랭지)(1포기)` 를 줄 때 | API 가 `여름(고랭지)` 를 줄 때 |
> |---|---|---|
> | `verbatim` | 맞음 | **틀림** |
> | `append_unit_except_livestock` | 맞음 (가드가 막음) | 맞음 |
>
> 인증키가 오면 `database/09_verify_against_csv.py` 가 어느 쪽인지 확정해 준다.

#### 요청 파라미터 — 기존 데이터와 반드시 맞출 값

| 파라미터 | 값 | 틀리면 |
|---|---|---|
| `p_product_cls_code` | `01` (소매) | `02` 는 도매다. 기존 43,480행은 전부 소매다 |
| `p_convert_kg_yn` | `N` | `Y` 로 하면 전부 1kg 환산가로 와서 과거분과 자릿수가 어긋난다 |
| `p_country_code` | **넣지 않는다** | 지역코드를 넣으면 그 지역 값이 온다. 기존 데이터는 지역 구분이 없는 전국값이다 |
| `p_item_category_code` | `100`~`600` 을 순회 | 한 번에 한 부류만 준다. 6번 부른다 |
| `p_returntype` | `json` | |

#### 스크립트 뼈대

```python
"""KAMIS OpenAPI 로 하루치 소매 시세를 받아 CSV 와 같은 모양의 DataFrame 으로 만든다.

  실행:  .venv\\Scripts\\python.exe database\\05_fetch_kamis.py [YYYY-MM-DD]
  기본값: 오늘
"""
import importlib.util, sys, time
from datetime import date
from pathlib import Path

import pandas as pd
import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import config

BASE = "http://www.kamis.or.kr/service/price/xml.do"

# 부류코드 -> 부류명. 01_create_kamis_table.sql 의 CATEGORY_CODE 주석과 같은 값이다.
CATEGORIES = {"100": "식량작물", "200": "채소류", "300": "특용작물",
              "400": "과실류",   "500": "축산물", "600": "수산물"}

PRICE_MAP = [("당일가격", "dpr1"), ("1일전가격", "dpr2"), ("1주일전가격", "dpr3"),
             ("2주일전가격", "dpr4"), ("1개월전가격", "dpr5"),
             ("1년전가격", "dpr6"), ("평년가격", "dpr7")]


def fetch_category(cat_code, regday):
    """한 부류의 하루치를 받아 dict 목록으로 돌려준다."""
    params = {
        "action": "dailyPriceByCategoryList",
        "p_cert_key": config.KAMIS_CERT_KEY,
        "p_cert_id": config.KAMIS_CERT_ID,
        "p_returntype": "json",
        "p_product_cls_code": "01",      # 소매
        "p_item_category_code": cat_code,
        "p_regday": regday,
        "p_convert_kg_yn": "N",          # 조사단위 그대로
    }
    r = requests.get(BASE, params=params, timeout=20)
    r.raise_for_status()
    body = r.json()

    # 자료가 없는 날은 data 가 리스트로 온다. 객체로만 가정하면 터진다. (3단계에서 확인할 것)
    data = body.get("data")
    if not isinstance(data, dict):
        return []
    items = data.get("item") or []
    if isinstance(items, dict):          # 1건일 때 리스트가 아닐 수 있다
        items = [items]

    rows = []
    for it in items:
        if not it.get("itemcode"):       # 합계행 같은 빈 항목 방어
            continue
        row = {
            "조사일자": regday,
            "구분": "소매",
            "부류명": CATEGORIES[cat_code],
            "부류코드": cat_code,
            "품목코드": str(it["itemcode"]).strip(),
            "품목명": str(it["item_name"]).strip(),
            "품종코드": str(it["kindcode"]).strip(),
            # ⚠ 기존 CSV 규칙: 품종명 끝에 단위를 괄호로 붙인다
            "품종명": f"{str(it['kind_name']).strip()}({str(it['unit']).strip()})",
            "등급": str(it.get("rank", "-")).strip(),
            "단위": str(it["unit"]).strip(),
        }
        for csv_col, api_col in PRICE_MAP:
            row[csv_col] = str(it.get(api_col, "-")).strip()
        rows.append(row)
    return rows


def fetch_day(regday):
    """6개 부류를 순회해 하루치 전체를 DataFrame 으로."""
    all_rows = []
    for code in CATEGORIES:
        got = fetch_category(code, regday)
        print(f"  {code} {CATEGORIES[code]:<6} {len(got):>4}행")
        all_rows.extend(got)
        time.sleep(0.5)          # 연속 호출 간격
    return pd.DataFrame(all_rows)


if __name__ == "__main__":
    day = sys.argv[1] if len(sys.argv) > 1 else date.today().isoformat()
    df = fetch_day(day)
    print(f"\n{day} · 총 {len(df):,}행")
    if not df.empty:
        priced = (df["당일가격"] != "-").sum()
        print(f"당일가격 있는 행 {priced:,} / {len(df):,}")
    # 확인용으로 먼저 CSV 로 떨궈 눈으로 본다. DB 반영은 다음 단계.
    out = Path(__file__).resolve().parent.parent / "raws" / f"kamis_api_{day}.csv"
    df.to_csv(out, index=False, encoding="utf-8-sig")
    print(f"저장: {out}")
```

**이 단계에서는 DB 를 건드리지 않는다.** CSV 로 떨궈서 기존 파일과 같은 모양인지 먼저 확인한다.
확인이 끝나면 `04_insert_new_days.py` 에 이 파일 경로를 넘겨 한 번 넣어 볼 수 있다.

```
.venv\Scripts\python.exe database\04_insert_new_days.py raws\kamis_api_2026-08-19.csv
```

`requirements.txt` 에 `requests` 를 추가한다.

---

### 5단계 · 덮어쓰기(UPSERT)로 바꾼다 — 여기가 제일 중요하다

`04_insert_new_days.py` 는 **DB 에 이미 있는 자연키를 건너뛴다**(`04:79`).
하루 한 번 사람이 돌릴 때는 맞는 동작이지만, 자동 수집에서는 **틀린다.**

> 오전 10시에 부르면 오늘 당일가격이 아직 `-` 다. → `-`(NULL) 인 채로 43,481번째 행이 들어간다.
> 오후 4시에 다시 부르면 값이 채워져 있다. → 하지만 자연키가 이미 있으니 **건너뛴다.**
> 결과: 오늘 시세가 영원히 빈칸으로 남는다.

그래서 `database/06_upsert_daily_price.py` 를 만들어 **MERGE** 로 넣는다.
자연키(`SURVEY_DATE, ITEM_CODE, KIND_CODE, RANK_NAME`)에 이미 UNIQUE 인덱스가 걸려 있어
(`01_create_kamis_table.sql:59`) 그대로 MERGE 조건으로 쓸 수 있다.

```sql
MERGE INTO TBL_DAILY_PRICE t
USING (
    SELECT TO_DATE(:survey_date, 'YYYY-MM-DD') AS SURVEY_DATE,
           :item_code AS ITEM_CODE, :kind_code AS KIND_CODE,
           :rank_name AS RANK_NAME
    FROM DUAL
) s
ON (    t.SURVEY_DATE = s.SURVEY_DATE
    AND t.ITEM_CODE   = s.ITEM_CODE
    AND t.KIND_CODE   = s.KIND_CODE
    AND t.RANK_NAME   = s.RANK_NAME)
WHEN MATCHED THEN UPDATE SET
    t.PRICE_TODAY  = :price_today,
    t.PRICE_1D     = :price_1d,
    t.PRICE_1W     = :price_1w,
    t.PRICE_2W     = :price_2w,
    t.PRICE_1M     = :price_1m,
    t.PRICE_1Y     = :price_1y,
    t.PRICE_NORMAL = :price_normal
WHEN NOT MATCHED THEN INSERT
    (PRICE_NO, SURVEY_DATE, MARKET_TYPE, CATEGORY_NAME, CATEGORY_CODE,
     ITEM_CODE, ITEM_NAME, KIND_CODE, KIND_NAME, RANK_NAME, UNIT,
     PRICE_TODAY, PRICE_1D, PRICE_1W, PRICE_2W, PRICE_1M, PRICE_1Y, PRICE_NORMAL)
VALUES
    (SEQ_DAILY_PRICE.NEXTVAL, s.SURVEY_DATE, :market_type, :category_name, :category_code,
     s.ITEM_CODE, :item_name, s.KIND_CODE, :kind_name, s.RANK_NAME, :unit,
     :price_today, :price_1d, :price_1w, :price_2w, :price_1m, :price_1y, :price_normal)
```

`executemany` 로 넣되 바인드는 **이름 방식**(`:survey_date`)을 쓴다.
`build_rows()` 가 돌려주는 튜플을 dict 로 바꾸는 얇은 어댑터 하나만 붙이면 된다.

**NULL 로 덮어쓰지 않는다.** 이미 값이 있는 행에 늦게 도착한 응답의 `-`(NULL)를 그대로
UPDATE 하면 있던 값이 지워진다. UPDATE 절을 `NVL(:price_today, t.PRICE_TODAY)` 로 감싼다.

#### 이 DB(11.2.0.2)에서 실제로 확인한 것

| 확인 | 결과 |
|---|---|
| MERGE 의 INSERT 절에 `SEQ_DAILY_PRICE.NEXTVAL` | **된다.** `ORA-02287` 안 남 — 선채번 우회 불필요 |
| `executemany` + 이름 바인드로 MERGE | 된다 |
| UPDATE 절에 ON 조건 컬럼을 넣으면 | `ORA-38104`. 위 문장은 자연키 4개를 UPDATE 에서 뺐다 |
| 같은 값을 다시 넣으면 | 174행 갱신, **값·행수 모두 불변** (신규 0) |
| 가격이 전부 `-` 인 응답을 다시 넣으면 | **기존 값 그대로 살아남음** (169행 유지) |
| 없는 자연키를 넣으면 | `PRICE_NO` 채번되고 `-` 는 NULL 로 들어감 |

---

### 6단계 · 수집 이력 테이블을 만든다 — `TBL_FETCH_LOG`

자동화는 **실패가 눈에 보여야** 산다. 스케줄러가 조용히 죽으면 화면은 어제 값을 오늘 값처럼
계속 보여준다. 지금 구조에서는 그걸 알아챌 방법이 없다.

```sql
CREATE TABLE TBL_FETCH_LOG
(
    LOG_NO        NUMBER               NOT NULL,
    FETCHED_AT    DATE DEFAULT SYSDATE NOT NULL,  -- 수집 실행 시각
    SURVEY_DATE   DATE                 NOT NULL,  -- 요청한 조사일자
    CATEGORY_CODE VARCHAR2(5 CHAR),               -- 부류코드 (전체면 NULL)
    STATUS        VARCHAR2(20 CHAR)    NOT NULL,  -- OK / NO_DATA / ERROR
    ROWS_FETCHED  NUMBER DEFAULT 0     NOT NULL,
    ROWS_UPSERTED NUMBER DEFAULT 0     NOT NULL,
    MESSAGE       VARCHAR2(500 CHAR),             -- 오류 메시지
    CONSTRAINT PK_FETCH_LOG PRIMARY KEY (LOG_NO)
);

CREATE SEQUENCE SEQ_FETCH_LOG START WITH 1 INCREMENT BY 1 NOCACHE;
CREATE INDEX IX_FETCH_LOG_TIME ON TBL_FETCH_LOG (FETCHED_AT DESC);
```

`database/07_create_fetch_log.sql` 로 두고, 수집기가 매 실행마다 한 줄씩 남긴다.

---

### 7단계 · 자동 실행 — Windows 작업 스케줄러

**실제로 등록한 내용은 아래와 같다** (계획 초안의 12:00/16:00/18:00 세 번은 폐기했다 —
KAMIS 공표가 17:00 이라 그 전 두 번은 축산물만 받아 오는 헛돈이다. **18:00 한 번**으로 간다).

> **2026-10-15 갱신:** 지금은 **17:30 · `KAMIS_fetch_1730` · `--days 7`** 이고, bat 은
> 경로를 박아 두지 않고 `cd /d "%~dp0"` 로 자기 위치에 간다. 아래 bat 은 09-02 당시 초판이다 —
> **현재 내용은 저장소의 `run_fetch.bat` 을 볼 것.** 등록 명령은 현재 기준으로 고쳐 두었다.

`run_fetch.bat` — `logs\` 는 bat 이 알아서 만든다. (09-02 초판)

```bat
@echo off
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
cd /d "C:\Users\euclid_edu\Desktop\Hyun\project_grocery_price_insights_service"
if not exist logs mkdir logs
.venv\Scripts\python.exe database\06_upsert_daily_price.py --days 3 >> logs\fetch.log 2>&1
exit /b %ERRORLEVEL%
```

**이 bat 은 주석까지 ASCII 로만 쓴다.** cmd 는 배치 파일을 그때그때의 콘솔 코드페이지로
읽어서(개발 셸은 65001, 작업 스케줄러는 949), 한글이 한 글자라도 들어가면 — `rem` 줄
안이라도 — 파서가 바이트 위치에서 어긋나 그 뒤 줄이 통째로 깨진다. 실제로 그렇게 한 번
터졌다(`'THONUTF8' is not recognized`). 중간에 `chcp 65001` 을 넣는 것도 같은 이유로 안 된다.
한글 설명은 이 문서와 `06_upsert_daily_price.py` 첫 주석에 둔다.
로그를 UTF-8 로 남기는 건 `PYTHONUTF8`·`PYTHONIOENCODING` 두 줄이 맡는다.

등록은 PowerShell 에서 (`$dir` 만 자기 프로젝트 폴더로 바꾼다):

```powershell
$dir = "C:\Users\본인계정\Desktop\Hyun\project_nongsdak"
$action  = New-ScheduledTaskAction -Execute "cmd.exe" -Argument ('/c "' + $dir + '\run_fetch.bat"') -WorkingDirectory $dir
$trigger = New-ScheduledTaskTrigger -Daily -At (Get-Date -Hour 17 -Minute 30 -Second 0)
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries `
              -DontStopIfGoingOnBatteries -ExecutionTimeLimit (New-TimeSpan -Hours 1) `
              -MultipleInstances IgnoreNew
Register-ScheduledTask -TaskName "KAMIS_fetch_1730" -Action $action -Trigger $trigger -Settings $settings
```

옵션을 그렇게 준 이유:

| 옵션 | 왜 |
|---|---|
| `-StartWhenAvailable` | 18:00 에 노트북이 꺼져 있으면 그날 수집이 통째로 날아간다. 켜지면 바로 따라잡게 한다 |
| `-AllowStartIfOnBatteries` · `-DontStopIfGoingOnBatteries` | 기본값이 **배터리면 시작 안 함 / 배터리로 바뀌면 중단**이다. 노트북에서는 이게 그대로 결번이 된다 |
| `-MultipleInstances IgnoreNew` | 앞 실행이 안 끝났는데 또 뜨는 걸 막는다 |
| `-Execute "cmd.exe" -Argument "/c ..."` | `.bat` 을 직접 Execute 로 넣는 것보다 실행 경로가 확실하다 |

5단계의 UPSERT 덕분에 하루에 여러 번 돌려도 중복되지 않고 값만 최신으로 갱신된다.
낮에 한 번 더 받고 싶으면 트리거만 추가하면 된다.

> 첫 주는 스케줄러를 믿지 말고 `logs\fetch.log` 와 `TBL_FETCH_LOG` 를 매일 눈으로 볼 것.

---

### 8단계 · 서비스 쪽 손보기

여기까지 하면 DB 는 저절로 갱신된다. 남은 건 화면이 그걸 제대로 보여주는 일이다.

| # | 파일 | 할 일 | 이유 |
|---|---|---|---|
| 8-1 | `webservice/app.py` | `@app.on_event("startup")` 에서 `db._init_pool()` 호출 | 지금은 첫 요청 때 붙는다. 첫 사용자만 몇 초 기다린다 |
| 8-2 | `webservice/db.py` | `list_products()` 에 **60초 TTL 캐시** | 요청마다 43,480행 전체를 GROUP BY 한다. 데이터가 쌓일수록 느려진다 |
| 8-3 | `webservice/db.py` `get_meta()` | `TBL_FETCH_LOG` 의 최근 성공 시각을 `updated_at` 으로 함께 반환 | "실시간"의 근거를 화면에 댈 값 |
| 8-4 | `static/index.html` | 헤더에 `조사일 2026-08-19 · 3분 전 갱신` 표시 | 사용자가 신선도를 판단할 수 있게 |
| 8-5 | `static/index.html` | 마지막 수집이 **24시간을 넘겼으면 경고 배지** | 수집기가 죽은 걸 사용자도, 우리도 알게 |

8-2 캐시는 이 정도면 충분하다.

```python
import time

_products_cache = {"at": 0.0, "data": None}
PRODUCTS_TTL = 60          # 초. 수집은 하루 몇 번뿐이라 이보다 짧을 이유가 없다.

def list_products():
    now = time.time()
    if _products_cache["data"] is not None and now - _products_cache["at"] < PRODUCTS_TTL:
        return _products_cache["data"]
    out = _list_products_uncached()      # 지금 함수 본문을 그대로 옮긴다
    _products_cache.update(at=now, data=out)
    return out
```

---

### 9단계 · 검증 — API 값과 CSV 값이 같은지 대조한다

**이 단계를 통과해야 과거 CSV 1년치와 신규 API 분을 한 테이블에서 섞어 쓸 수 있다.**

이미 CSV 로 적재해 둔 날짜 하나(예: `2026-08-18`)를 API 로 다시 받아 대조한다.

```
.venv\Scripts\python.exe database\05_fetch_kamis.py 2026-08-18
```

떨어진 `raws/kamis_api_2026-08-18.csv` 를 원본 CSV 의 같은 날짜분과 비교해 확인한다.

| 확인 항목 | 기대 |
|---|---|
| 행 수 | 같아야 한다 |
| 품종명 | `여름(고랭지)(1포기)` 처럼 **단위 괄호가 붙어** 있어야 한다 |
| 등급 `-` 개수 | 원본과 같아야 한다 |
| 당일가격 | 품목 몇 개를 골라 값이 일치해야 한다 |
| 단위 | `100g`, `1포기` 등 그대로. `1kg` 로 통일돼 있으면 `p_convert_kg_yn` 이 `Y` 다 |

값이 다르면 **DB 에 넣지 말고** 4단계 파라미터부터 다시 본다.
과거분과 신규분이 다른 기준으로 섞이면 나중에 어느 쪽이 틀렸는지 가려낼 수 없다.

---

## 만들거나 고칠 파일 정리

| 파일 | 상태 | 내용 |
|---|---|---|
| `config.py` | **신규** | Oracle·KAMIS 접속 정보 한 곳에 모음 (2단계) |
| `database/05_fetch_kamis.py` | **신규** | API 호출 → CSV 모양 DataFrame (4단계) |
| `database/06_upsert_daily_price.py` | **신규** | MERGE 적재 + 수집 로그 기록 (5단계) |
| `database/07_create_fetch_log.sql` | **신규** | `TBL_FETCH_LOG` DDL (6단계) |
| `run_fetch.bat` | **신규** | 스케줄러가 부를 진입점 (7단계) |
| `webservice/db.py` | 수정 | config 사용 · 캐시 · `get_meta()` 에 `updated_at` (2·8단계) |
| `webservice/app.py` | 수정 | startup 에서 풀 초기화 (8단계) |
| `webservice/static/index.html` | 수정 | 갱신 시각 표시 · 지연 경고 (8단계) |
| `database/02_insert_daily_price.py` | 수정 | config 사용. `build_rows()` 는 그대로 재사용 (2단계) |
| `requirements.txt` | 수정 | `requests` 추가 |
| `database/01_create_kamis_table.sql` | 그대로 | 스키마 변경 없음 |
| `database/04_insert_new_days.py` | 그대로 | 수동 CSV 보정용으로 남겨 둔다 |

**테이블 스키마는 바꾸지 않는다.** 기존 17컬럼이 API 응답과 1:1로 맞는다 — 애초에 이 CSV 가
같은 API 로 수집된 것이기 때문이다.

---

## 운영하면서 걸릴 것들

- **공휴일·주말엔 조사가 없다.** 응답이 비어 오는 게 정상이다. `NO_DATA` 를 `ERROR` 로 기록하면
  경고가 매주 울려 아무도 안 보게 된다. 둘을 구분할 것.
- **연휴 다음 조사일은 당일가격이 거의 비어 있다.** 2026-08-17 은 167행 중 29행만 값이 있었다
  (결측 82.6%). API 로 받아도 똑같다. 적재 실패가 아니다.
- **품목·품종 코드는 늘어난다.** 새 품종이 나타나도 스키마는 그대로지만,
  `db.py` 의 `RANK_PRIORITY`(`db.py:25`)에 없는 등급이면 정렬에서 맨 뒤로 밀린다.
  월 1회쯤 목록에 없는 등급이 새로 생겼는지 확인한다.
- **평년가격은 KAMIS 가 계산해 준 값**(최근 5년 중 최고·최저 연도를 뺀 3개년 평균)이라
  연초에 기준선이 통째로 바뀔 수 있다. 우리가 계산하는 값이 아니다.
- **인증키가 만료되거나 호출량이 제한될 수 있다.** 401/403 응답을 `TBL_FETCH_LOG` 에
  메시지째로 남겨 두면 원인 찾기가 빠르다.
- **`raws/` 원본 CSV 는 덮어쓰지 않는다.** API 수집분은 `kamis_api_YYYY-MM-DD.csv` 처럼
  다른 이름으로 떨군다.

기존 데이터의 다른 함정은 [`README.md`](README.md) 의 '알려진 함정' 을 볼 것.

---

## 참고

- [KAMIS Open-API 이용안내](https://www.kamis.or.kr/customer/reference/openapi_list.do?action=detail&boardno=1) — `dailyPriceByCategoryList` 스펙
- [`SETUP.md`](SETUP.md) — 로컬 Oracle 세팅
- [`README.md`](README.md) — 프로젝트 전체 설명과 알려진 함정
