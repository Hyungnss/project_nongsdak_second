"""운영 모델 학습 · 롤백 (collector/train.py) — 실제 PostgreSQL. 학습 → TBL_MODEL_RUN · current.json → 매일 예측.

가짜 가격(평일, 3년, 계절 모양)을 넣고 학습 작업을 그대로 돌린다.
"""

from datetime import date

import pytest

from collector import predict as predict_job
from collector import train as job
from ml import model
from tests.test_pg_forecast import _fill


@pytest.fixture
def conn(pg_db, tmp_path, monkeypatch):
    monkeypatch.setenv("MODEL_DIR", str(tmp_path))
    # 앞선 시험이 같은 프로세스에서 lightgbm(OpenMP)을 이미 돌렸다 — fork 한 자식이 멈출 수 있어 깨끗한 프로세스로
    monkeypatch.setenv("MODEL_MP_CONTEXT", "spawn")
    for n, item in enumerate(["211", "212", "213"]):
        _fill(pg_db, item=item, kind="01", base=1500.0 + 500 * n)
    return pg_db


def test_train_records_run_and_deploys_when_gate_passes(conn):
    job.main(["train", "--market", "소매", "--n-jobs", "1"])
    run = conn.execute("""SELECT MODEL_VERSION, MARKET_TYPE, DATA_END, TRAIN_ROWS, HOLDOUT_END, SCORE, BLEND_SCORE,
                                 PARITY_DIFF, PASSED, DEPLOYED, REASON FROM TBL_MODEL_RUN""").fetchall()
    assert len(run) == 1
    version, market, data_end, rows, hold_end, score, blend, parity, passed, deployed, reason = run[0]
    assert version.startswith("lgbm-retail-") and market == "소매" and data_end == date(2026, 11, 18)
    assert rows > 1000 and hold_end < data_end and parity < 1e-9 and passed == deployed
    assert (float(score) < float(blend)) == passed and (reason == "통과") == passed
    log = conn.execute("SELECT STATUS, TARGET FROM TBL_INGEST_LOG WHERE SOURCE = 'train'").fetchall()
    assert log == [("OK", f"소매 {version}")]

    # 배포됐으면 매일 예측이 그 모델로, 아니면 blend 로
    predict_job.main(["--market", "소매"])
    models = {r[0] for r in conn.execute("SELECT DISTINCT MODEL_VERSION FROM TBL_PRICE_FORECAST").fetchall()}
    assert models == ({version} if passed else {"blend-1"})


def test_rollback_and_status(conn, capsys):
    for v in ("lgbm-retail-20261115-0300", "lgbm-retail-20261122-0300"):
        d = model.model_dir() / "retail" / v
        d.mkdir(parents=True)
        (d / "model.txt").write_text("x", encoding="utf-8")
        model.promote("소매", v)
    job.main(["rollback", "--market", "소매"])
    assert model.read_current()["retail"]["current"] == "lgbm-retail-20261115-0300"
    msg = conn.execute("SELECT MESSAGE FROM TBL_INGEST_LOG WHERE SOURCE = 'train'").fetchone()[0]
    assert msg == "lgbm-retail-20261122-0300 → lgbm-retail-20261115-0300"
    job.main(["status"])
    assert "소매: lgbm-retail-20261115-0300 · 이력 2개" in capsys.readouterr().out
    with pytest.raises(SystemExit):
        job.main(["rollback"])                          # 시장을 정하지 않으면 거절


def test_retail_model_uses_wholesale_when_db_has_it(conn):
    """도매 가격이 있으면 소매 모델이 도매 특성까지 넣어 학습하고, 매일 예측도 그 모델로 낸다."""
    for n, item in enumerate(["211", "212"]):
        _fill(conn, item=item, kind="01", market="도매", base=900.0 + 300 * n)
    job.main(["train", "--market", "소매", "--n-jobs", "1"])
    meta = conn.execute("SELECT META FROM TBL_MODEL_RUN WHERE MARKET_TYPE = '소매'").fetchone()[0]
    assert meta["inputs"] == "price+wholesale" and meta["features"][-3:] == ["wh_ret5", "wh_ret20", "wh_gap20"]
    if meta["gate"]["passed"]:
        predict_job.main(["--market", "소매"])
        got = {r[0] for r in conn.execute("SELECT DISTINCT MODEL_VERSION FROM TBL_PRICE_FORECAST").fetchall()}
        assert got == {meta["version"]}
