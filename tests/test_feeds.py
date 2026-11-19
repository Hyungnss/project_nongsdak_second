"""특성 데이터 수집기 — 날씨(ASOS) · 물가(ECOS) · 예보 보관 · 스케줄러 작업들.

외부 API 는 부르지 않는다. 응답 모양을 흉내 낸 값으로 해석 · 저장 · AVAILABLE_AT 규칙을 본다.
"""

from datetime import date, datetime, time

import pytest

import config
from collector import cpi, forecast, ingest, weather
from collector import scheduler as s


# ── 공용 ──────────────────────────────────────────────────────────────────
def test_num():
    assert ingest.num("12.3") == 12.3 and ingest.num("") is None and ingest.num(" ") is None
    assert ingest.num(None, 0.0) == 0.0 and ingest.num("-") is None and ingest.num("x") is None


# ── 날씨 ──────────────────────────────────────────────────────────────────
def test_weather_parse_rain_empty_is_zero():
    rows = weather.parse([
        {"tm": "2026-11-10", "stnId": "108", "avgTa": "6.3", "minTa": "0.7", "maxTa": "12.7",
         "sumRn": "", "ddMes": "", "avgRhm": "64.0", "sumSsHr": "9.6", "minTg": ""},
        {"tm": "", "stnId": "108"},                                      # 날짜 없는 행은 뺀다
    ])
    assert len(rows) == 1
    r = rows[0]
    assert r["OBS_DATE"] == date(2026, 11, 10) and r["STN_ID"] == 108
    assert (r["AVG_TA"], r["SUM_RN"], r["DD_MES"], r["MIN_TG"]) == (6.3, 0.0, 0.0, None)


def test_weather_chunks_999_days():
    c = weather.chunks(date(2015, 1, 1), date(2026, 11, 18))
    assert c[0] == (date(2015, 1, 1), date(2017, 9, 25))   # 첫날 포함 999일 (2016 윤년) and c[-1][1] == date(2026, 11, 18)
    assert all((e - s).days + 1 <= 999 for s, e in c)


def test_weather_station_list():
    assert len(weather.STATIONS) == 97
    assert weather.STATIONS[100] == ("대관령", "강원") and weather.STATIONS[261] == ("해남", "전남")


def test_weather_available_at_rules():
    now = datetime(2026, 11, 19, 11, 30, tzinfo=config.KST)
    assert weather.available_at(date(2020, 3, 1), True, now) == datetime(2020, 3, 2, 11, 0, tzinfo=config.KST)
    assert weather.available_at(date(2026, 11, 18), False, now) == now


def test_weather_save_keeps_first_available_at(pg_db):
    weather.save_stations(pg_db, [108])
    row = {"OBS_DATE": date(2026, 11, 10), "STN_ID": 108, **{c: None for c in weather.FIELDS}, "AVG_TA": 6.3}
    weather.save(pg_db, [row], backfill=True)
    weather.save(pg_db, [{**row, "AVG_TA": 6.5}], backfill=False)               # 정정값
    v, at = pg_db.execute("SELECT AVG_TA, AVAILABLE_AT FROM TBL_WEATHER_DAILY").fetchone()
    assert float(v) == 6.5                                                       # 값은 고친다
    assert at == datetime(2026, 11, 11, 11, 0, tzinfo=config.KST)                # 처음 알게 된 시각은 그대로


# ── 물가 ──────────────────────────────────────────────────────────────────
def test_cpi_helpers():
    assert cpi.months_back("202611", 6) == "202605" and cpi.months_back("202602", 3) == "202511"
    assert cpi.backfill_available_at("202512") == datetime(2026, 1, 10, tzinfo=config.KST)
    rows = cpi.parse([{"TIME": "202610", "ITEM_CODE1": "211", "ITEM_NAME1": "농축수산물",
                       "DATA_VALUE": "123.45", "UNIT_NAME": "2020=100"},
                      {"TIME": "2026", "DATA_VALUE": "1"}, {"TIME": "202609", "DATA_VALUE": ""}])
    assert rows == [{"PERIOD": "202610", "STAT_CODE": "901Y010", "ITEM_CODE": "211", "ITEM_NAME": "농축수산물",
                     "VALUE": 123.45, "UNIT": "2020=100"}]


def test_cpi_save_keeps_first_available_at(pg_db):
    r = {"PERIOD": "202610", "STAT_CODE": "901Y010", "ITEM_CODE": "211", "ITEM_NAME": "농축수산물",
         "VALUE": 120.0, "UNIT": "2020=100"}
    cpi.save(pg_db, [r], backfill=True)
    cpi.save(pg_db, [{**r, "VALUE": 121.0}], backfill=False)
    v, at = pg_db.execute("SELECT VALUE, AVAILABLE_AT FROM TBL_CPI_MONTHLY").fetchone()
    assert float(v) == 121.0 and at == datetime(2026, 11, 10, tzinfo=config.KST)


# ── 예보 ──────────────────────────────────────────────────────────────────
def test_forecast_issuances_last_24h():
    now = datetime(2026, 11, 19, 13, 40, tzinfo=config.KST)
    assert [t.strftime("%m-%d %H") for t in forecast.issuances(now)] == ["11-18 18", "11-19 06"]
    early = datetime(2026, 11, 19, 6, 10, tzinfo=config.KST)             # 06시 발표 30분 전
    assert [t.strftime("%m-%d %H") for t in forecast.issuances(early)] == ["11-18 18"]


def test_forecast_parse():
    tm = datetime(2026, 11, 19, 6, tzinfo=config.KST)
    ta = forecast.parse_ta({"regId": "11B10101", "taMin4": 1, "taMax4": 10, "taMin4Low": 0,
                            "taMin10": "4", "taMax10": 8, "taMin5": None, "taMax5": None}, tm)
    assert ta == [(date(2026, 11, 23), 1.0, 10.0), (date(2026, 11, 29), 4.0, 8.0)]
    land = forecast.parse_land({"rnSt4Am": 20, "rnSt4Pm": 30, "wf4Am": "맑음", "wf4Pm": "구름많음",
                                "rnSt8": 40, "wf8": "흐림"}, tm)
    assert land == [(date(2026, 11, 23), 20, 30, "맑음", "구름많음"), (date(2026, 11, 27), 40, 40, "흐림", "흐림")]


def test_forecast_save_is_idempotent(pg_db):
    tm = datetime(2026, 11, 19, 6, tzinfo=config.KST)
    item = {"taMin4": 1, "taMax4": 10}
    assert forecast.save(pg_db, "ta", "11B10101", tm, item, {"response": {}}) == 1
    assert forecast.save(pg_db, "ta", "11B10101", tm, item, {"response": {}}) == 1     # 다시 넣어도
    assert pg_db.execute("SELECT COUNT(*) FROM TBL_FCST_MID_TA").fetchone()[0] == 1
    assert forecast.have(pg_db, tm) == {("ta", "11B10101")}


# ── 스케줄러 ──────────────────────────────────────────────────────────────
def test_jobs_cover_all_feeds():
    names = {j.name: j for j in s.JOBS}
    assert set(names) == {"forecast_am", "weather", "cpi", "price", "forecast_pm"}
    assert names["price"].at == s.FETCH_AT and names["price"].source is None
    # 예보는 발표(06 · 18시) 뒤, 24시간이 지나기 전에 돈다
    assert time(6, 30) <= names["forecast_am"].at < time(18) and names["forecast_pm"].at >= time(18, 30)


def test_plan_catches_up_missed_jobs(monkeypatch):
    """11:50 에 켜졌는데 오늘 날씨 · 물가 · 아침 예보 기록이 없으면 바로 돌 차례다."""
    monkeypatch.setattr(s, "ran_today", lambda now, job=None: False)
    now = datetime(2026, 11, 19, 11, 50)
    due = [job.name for at, job in s.plan(now, set()) if at <= now]
    assert sorted(due) == ["cpi", "forecast_am", "weather"]
    # 이미 돌려 본 작업은 같은 날 다시 돌지 않는다
    due = [job.name for at, job in s.plan(now, {("weather", now.date())}) if at <= now]
    assert "weather" not in due


def test_ran_today_reads_ingest_log(pg_db):
    job = next(j for j in s.JOBS if j.name == "weather")
    now = datetime(2026, 11, 19, 12, 0)
    assert s.ran_today(now, job) is False
    pg_db.execute("""INSERT INTO TBL_INGEST_LOG (SOURCE, TARGET, STATUS, FETCHED_AT)
                     VALUES ('weather', 'x', 'OK', '2026-11-19 11:31+09')""")
    assert s.ran_today(now, job) is True


@pytest.mark.parametrize("name", ["weather", "cpi"])
def test_missing_key_stops_with_message(monkeypatch, name):
    monkeypatch.setattr(ingest.config, "get", lambda k, d=None: None)
    mod = {"weather": weather, "cpi": cpi}[name]
    with pytest.raises(SystemExit, match="KEY"):
        mod.main([])


def test_hide_masks_keys(monkeypatch):
    monkeypatch.setattr(ingest.config, "get", lambda k, d=None: {"ECOS_KEY": "SECRET123"}.get(k, d))
    assert ingest.hide("https://ecos/api/x/SECRET123/json") == "https://ecos/api/x/***/json"
