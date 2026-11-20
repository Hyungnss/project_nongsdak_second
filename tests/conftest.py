"""시험 공용 준비물.

pg_db : 실제 PostgreSQL 로 도는 시험용 DB.
  · 개발 DB(nongsdak)와 따로 '<DB_NAME>_test' 를 만들어 쓴다. 개발 데이터는 건드리지 않는다.
  · 시험 세션마다 DB 를 새로 만들고 database/schema.sql 과 database/migrations/*.sql 을
    서버와 같은 순서로 적용한다 — 스키마와 마이그레이션 자체도 검증된다.
  · 시험 함수마다 모든 테이블을 비운다 (서로 영향 없게).
  · 로컬에서 Postgres 가 안 떠 있으면 건너뛴다 (docker compose up -d db 로 띄운다).
    CI 에서는(CI=true) 건너뛰지 않고 실패시킨다 — DB 시험이 조용히 빠지면 안 되기 때문이다.
"""

import os
from pathlib import Path

import psycopg
import pytest
from psycopg import sql

import config

ROOT = Path(__file__).resolve().parent.parent
SCHEMA = ROOT / "database" / "schema.sql"
MIGRATIONS = sorted((ROOT / "database" / "migrations").glob("[0-9][0-9][0-9]_*.sql"))
TABLES = ["TBL_MODEL_RUN", "TBL_PRICE_FORECAST", "TBL_INGEST_LOG", "TBL_WEATHER_DAILY", "TBL_WEATHER_STATION", "TBL_CPI_MONTHLY",
          "TBL_FCST_RAW", "TBL_FCST_MID_TA", "TBL_FCST_MID_LAND",
          "TBL_BACKFILL_JOB", "TBL_API_USAGE_DAILY", "TBL_API_KEY",
          "TBL_CART_ITEM", "TBL_USER_SESSION", "TBL_USER",
          "TBL_DAILY_PRICE", "TBL_FETCH_LOG", "TBL_API_RAW"]


@pytest.fixture(scope="session")
def pg_test_db():
    """시험용 DB 를 새로 만들고 config.PG 가 그 DB 를 가리키게 한다. (세션에 한 번)"""
    base = dict(config.PG)
    test_name = f"{base['dbname']}_test"
    assert test_name.endswith("_test")       # 실수로 개발 DB 를 지우지 않도록

    try:
        admin = psycopg.connect(**{**base, "dbname": "postgres"}, autocommit=True, connect_timeout=5)
    except psycopg.OperationalError as e:
        if os.environ.get("CI"):
            raise
        pytest.skip(f"PostgreSQL 에 붙을 수 없어 DB 시험을 건너뜀 (docker compose up -d db): {e}")

    with admin:
        admin.execute(sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(sql.Identifier(test_name)))
        admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(test_name)))

    with psycopg.connect(**{**base, "dbname": test_name}, autocommit=True) as conn:
        conn.execute(SCHEMA.read_text(encoding="utf-8"))
        for m in MIGRATIONS:
            with conn.transaction():
                conn.execute(m.read_text(encoding="utf-8"))
        conn.execute(f"ALTER DATABASE {test_name} SET timezone = 'Asia/Seoul'")

    # 앱 · 수집기가 쓰는 접속 정보를 시험 DB 로 돌린다 (config.PG 는 dict 라 제자리에서 바꾼다)
    config.PG["dbname"] = test_name
    yield test_name
    config.PG["dbname"] = base["dbname"]


@pytest.fixture
def pg_db(pg_test_db):
    """시험 하나마다 빈 테이블로 시작한다. 커넥션 하나를 넘겨준다 (autocommit)."""
    from backend import app as app_module

    db = app_module.db
    with psycopg.connect(**config.PG, autocommit=True) as conn:
        conn.execute(f"TRUNCATE {', '.join(TABLES)} RESTART IDENTITY CASCADE")
        db._products_cache.clear()          # 품목 목록 60초 캐시가 앞 시험 값을 들고 있지 않게
        app_module.api_v1._items_cache.clear()
        app_module.api_v1.limiter.reset()   # 호출 제한 카운터도 시험마다 새로
        yield conn
    if db._pool is not None:                # 시험 DB 를 가리키던 풀은 닫는다
        db._pool.close()
        db._pool = None


def add_price(conn, day, item="211", kind="01", rank="상품", price=1000.0, market="소매",
              item_name="배추", kind_name="가을(1포기)", unit="1포기", category="200",
              category_name="채소류", normal=None, year_ago=None):
    """시세 한 행을 바로 넣는다 (시험 데이터 만들기용)."""
    conn.execute(
        """INSERT INTO TBL_DAILY_PRICE (SURVEY_DATE, MARKET_TYPE, CATEGORY_NAME, CATEGORY_CODE,
               ITEM_CODE, ITEM_NAME, KIND_CODE, KIND_NAME, RANK_NAME, UNIT,
               PRICE_TODAY, PRICE_NORMAL, PRICE_1Y)
           VALUES (%s::date, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
        (day, market, category_name, category, item, item_name, kind, kind_name, rank, unit,
         price, normal, year_ago),
    )
