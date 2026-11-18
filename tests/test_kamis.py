"""collector/kamis.py — KAMIS OpenAPI 응답을 해석하는 부분.

실제 API 를 부르지 않는다. 실제 응답과 같은 모양의 dict 를 직접 만들어 넣는다.
"""

import json

import pytest

from collector import kamis


def _body(items, error_code="000"):
    """KAMIS 정상 응답 모양. error_code 는 문서와 달리 data 안에 들어 있다."""
    return {
        "condition": [{"p_cert_key": "SECRET-KEY", "p_cert_id": "my-id", "p_regday": "2026-11-17"}],
        "data": {"error_code": error_code, "item": items},
    }


ITEM = {
    "item_name": "배추", "item_code": "211", "kind_name": "가을", "kind_code": "01",
    "rank": "상품", "rank_code": "04", "unit": "1포기",
    "day1": "당일 (11/17)", "dpr1": "3,980",
    "day2": "1일전 (11/14)", "dpr2": "4,010",
    "day3": "1주일전 (11/10)", "dpr3": "-",
    "day4": "2주일전 (11/03)", "dpr4": "4,200",
    "dpr5": "4,300", "dpr6": "3,500", "dpr7": "4,100",
}


# ── 응답 모양이 흔들려도 견디는지 ────────────────────────────────────────
def test_extract_items_normal_list():
    assert kamis.extract_items(_body([ITEM, ITEM])) == [ITEM, ITEM]


def test_extract_items_single_item_as_dict():
    """1건뿐인 날은 item 이 리스트가 아니라 객체 하나로 온다."""
    assert kamis.extract_items(_body(ITEM)) == [ITEM]


def test_extract_items_no_data_day():
    """자료가 없는 날(주말 등)은 data 가 리스트로 온다."""
    assert kamis.extract_items({"data": ["001"]}) == []


def test_error_code_inside_data_or_top_level():
    assert kamis.error_code_of(_body([])) == "000"
    assert kamis.error_code_of({"error_code": "200", "data": []}) == "200"
    assert kamis.error_code_of({"data": {}}) is None


# ── '1일전 (11/14)' 같은 라벨에서 실제 날짜 꺼내기 ───────────────────────
@pytest.mark.parametrize(
    "label, regday, expected",
    [
        ("1일전 (11/14)", "2026-11-17", "2026-11-14"),
        ("2주일전 (12/22)", "2027-01-05", "2026-12-22"),   # 연초: 조사일보다 뒤면 작년
        ("1일전", "2026-11-17", None),                     # 날짜가 없음
        ("1일전 (13/40)", "2026-11-17", None),             # 있을 수 없는 날짜
        ("2주일전 (03/01)", "2026-11-17", None),           # 두 달 넘게 멀면 연도 추정이 틀린 것
        (None, "2026-11-17", None),
    ],
)
def test_label_date(label, regday, expected):
    assert kamis.label_date(label, regday) == expected


# ── 품종명에 단위 붙이기 ─────────────────────────────────────────────────
def test_build_kind_name_appends_unit_except_livestock():
    assert kamis.build_kind_name("가을", "1포기", "200") == "가을(1포기)"
    assert kamis.build_kind_name("가을(1포기)", "1포기", "200") == "가을(1포기)"   # 이미 붙어 있으면 그대로
    assert kamis.build_kind_name("안심", "100g", kamis.LIVESTOCK) == "안심"        # 축산물은 안 붙인다


# ── 응답 하나 -> DB 에 넣을 행 ───────────────────────────────────────────
def test_rows_from_maps_fields():
    (row,) = kamis.rows_from(_body([ITEM]), "200", "2026-11-17", kamis.RETAIL)
    assert row["조사일자"] == "2026-11-17"
    assert row["구분"] == "소매"
    assert row["부류명"] == "채소류"
    assert (row["품목코드"], row["품종코드"], row["등급"]) == ("211", "01", "상품")
    assert row["품종명"] == "가을(1포기)"
    assert row["당일가격"] == "3,980" and row["1주일전가격"] == "-"   # 숫자 변환은 loader 가 한다
    assert row["1일전일자"] == "2026-11-14"


def test_rows_from_skips_items_without_code():
    """합계행처럼 품목코드가 빈 항목은 건너뛴다."""
    assert kamis.rows_from(_body([{**ITEM, "item_code": ""}]), "200", "2026-11-17") == []


def test_rows_from_wholesale_label():
    (row,) = kamis.rows_from(_body([ITEM]), "200", "2026-11-17", kamis.WHOLESALE)
    assert row["구분"] == "도매"


# ── 인증키가 저장 · 출력에 새지 않는지 ───────────────────────────────────
def test_raw_text_masks_cert_key_and_hash_is_stable():
    body = _body([ITEM])
    text, digest = kamis.raw_text(body)
    assert "SECRET-KEY" not in text and "my-id" not in text
    assert json.loads(text)["condition"][0]["p_cert_key"] == "***"
    # 같은 응답이면 해시도 같아야 TBL_API_RAW 에 중복으로 쌓이지 않는다
    assert kamis.raw_text(json.loads(json.dumps(body)))[1] == digest
