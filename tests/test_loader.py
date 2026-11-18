"""collector/loader.py — KAMIS 값을 DB 에 넣을 모양으로 바꾸는 규칙.

DB 에 접속하지 않는다. 변환 함수만 부른다.
"""

import pandas as pd
import pytest

from collector import loader


# ── to_price: 가격 문자열 -> 숫자 / NULL ─────────────────────────────────
@pytest.mark.parametrize(
    "raw, expected",
    [
        ("5258", 5258.0),        # 평범한 가격
        ("1,234", 1234.0),       # KAMIS 는 천 단위 콤마를 붙여 준다
        (" 980 ", 980.0),        # 앞뒤 공백
        (12.5, 12.5),            # 이미 숫자인 값
        ("-", None),             # 조사 없음
        ("", None),              # 빈 칸
        (None, None),            # 값 자체가 없음
        ("abc", None),           # 숫자가 아닌 값은 버린다
    ],
)
def test_to_price_basic(raw, expected):
    assert loader.to_price(raw) == expected


@pytest.mark.parametrize("raw", ["0", "0.00", "0.0", 0, "-5"])
def test_to_price_zero_or_negative_is_null(raw):
    """0원 · 음수는 '조사 없음' 으로 본다 (2026-11-18 닭 절단육이 0원으로 보이던 버그).

    이 시험이 깨지면 화면에 다시 '현재가 0원' 이 뜬다.
    """
    assert loader.to_price(raw) is None


# ── build_rows: CSV 모양 DataFrame -> DB 바인드 튜플 ─────────────────────
def _frame(**overrides):
    """CSV 17컬럼짜리 한 행. 필요한 칸만 바꿔 쓴다."""
    row = {
        "조사일자": "2026-11-17", "구분": "소매", "부류명": "축산물", "부류코드": "500",
        "품목코드": "9901", "품목명": "닭", "품종코드": "24", "품종명": "절단육",
        "등급": "절단육", "단위": "1kg",
        "당일가격": "8,537", "1일전가격": "-", "1주일전가격": "0", "2주일전가격": "8,500",
        "1개월전가격": "8,400", "1년전가격": "", "평년가격": "8,152",
    }
    row.update(overrides)
    return pd.DataFrame([row])


def test_build_rows_converts_text_and_prices():
    (row,) = loader.build_rows(_frame())
    # 앞 10칸은 글자, 뒤 7칸은 가격
    assert row[:10] == ("2026-11-17", "소매", "축산물", "500", "9901", "닭", "24", "절단육", "절단육", "1kg")
    assert row[10:] == (8537.0, None, None, 8500.0, 8400.0, None, 8152.0)


@pytest.mark.parametrize("rank", ["-", "", "nan"])
def test_build_rows_missing_rank_becomes_eopseum(rank):
    """등급이 비면 '없음'. 등급은 자연키(UNIQUE 인덱스)라 NULL 이면 중복을 못 막는다."""
    (row,) = loader.build_rows(_frame(등급=rank))
    assert row[8] == "없음"


def test_build_rows_missing_column_fails_loudly():
    """컬럼이 빠진 CSV 는 조용히 넘어가지 말고 바로 알린다."""
    with pytest.raises(KeyError):
        loader.build_rows(_frame().drop(columns=["평년가격"]))
