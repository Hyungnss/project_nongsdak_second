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
