"""Postgres readiness (driver present, URL normalisation) and the price table maths."""
import pytest
from sqlalchemy.engine import Engine

from app.db import make_engine, normalize_database_url
from app.pricing import PRICES_USD_PER_MTOK, estimate_usd, parse_usage_detail, resolve_model


def test_postgres_url_builds_engine_with_psycopg3_without_connecting():
    eng = make_engine("postgresql+psycopg://seva:secret@db.example.internal:5432/sevadesk")
    assert isinstance(eng, Engine) and eng.dialect.name == "postgresql" and eng.dialect.driver == "psycopg"
    assert eng.pool._pre_ping is True
    eng.dispose()


@pytest.mark.parametrize("url,expected", [
    ("postgres://u:p@h/db", "postgresql+psycopg://u:p@h/db"),
    ("postgresql://u:p@h/db", "postgresql+psycopg://u:p@h/db"),
    ("postgresql+psycopg://u:p@h/db", "postgresql+psycopg://u:p@h/db"),
    ("sqlite:///./x.db", "sqlite:///./x.db"),
])
def test_normalize_database_url(url, expected):
    assert normalize_database_url(url) == expected
    assert make_engine(url).dialect.name in ("postgresql", "sqlite")


def test_sqlite_engine_allows_cross_thread_use(tmp_path):
    eng = make_engine(f"sqlite:///{tmp_path}/t.db")
    assert eng.dialect.name == "sqlite"
    with eng.connect() as c:
        assert c.exec_driver_sql("select 1").scalar() == 1


def test_estimate_usd_matches_price_table():
    p = PRICES_USD_PER_MTOK["claude-haiku-5-5"]
    assert estimate_usd("claude-haiku-5-5", 1_000_000, 0) == pytest.approx(p["input"])
    assert estimate_usd("claude-haiku-5-5", 0, 1_000_000) == pytest.approx(p["output"])
    assert estimate_usd("claude-opus-5-5", 5000, 150, 2000, 0) == pytest.approx((5000 * 4 + 150 * 20 + 2000 * 0.20) / 1e6)
    assert estimate_usd("not-a-model", 1_000_000) == pytest.approx(PRICES_USD_PER_MTOK["claude-opus-5-5"]["input"])


def test_parse_usage_detail_and_fallbacks():
    assert resolve_model("claude-sonnet-5-5") == ("claude-sonnet-5-5", False)
    assert resolve_model("", "claude-haiku-5-5") == ("claude-haiku-5-5", True)
    assert resolve_model("mystery", "also-mystery") == ("claude-opus-5-5", True)
    u = parse_usage_detail('{"model":"claude-sonnet-5-5","input_tokens":10,"output_tokens":5,"cache_read_input_tokens":3,"cache_creation_input_tokens":2,"calls":1}')
    assert u.total_tokens == 20 and not u.assumed_model and u.usd == pytest.approx((10 * 2 + 5 * 10 + 3 * 0.2 + 2 * 2.5) / 1e6)
    legacy = parse_usage_detail('{"input_tokens": 10, "calls": 1}', "claude-haiku-5-5")
    assert legacy.model == "claude-haiku-5-5" and legacy.assumed_model
    assert parse_usage_detail("not json") is None and parse_usage_detail("[1]") is None
