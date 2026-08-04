import json

import polars as pl
import pytest

from src.schemas import CableStatus
from conftest import make_brief, make_incident, make_news, make_weather


def test_upsert_incidents_idempotent(store):
    inc = make_incident()
    store.upsert_incidents([inc])
    store.upsert_incidents([inc.model_copy(update={"status": CableStatus.CUT})])
    df = store.get_active_incidents()
    rows = df.filter(pl.col("incident_id") == str(inc.incident_id))
    assert len(rows) == 1
    assert rows.row(0, named=True)["status"] == "cut"


def test_composite_score_math(store):
    store.upsert_incidents([make_incident(status="cut", fault_type="suspected_sabotage")])
    store.upsert_weather([make_weather(weather_fault_probability=0.5)])
    store.upsert_news([make_news(severity="medium")])
    assert store.refresh_cable_risk_scores() >= 1
    row = (store.get_cable_risk_scores()
           .filter(pl.col("cable_id") == "equiano").row(0, named=True))
    assert row["composite_score"] == pytest.approx(0.83)
    assert row["max_news_severity"] == "medium"
    assert row["repair_delayed"] is False


def test_news_dedup_by_link(store):
    n = make_news()
    store.upsert_news([n])
    store.upsert_news([n])
    assert store.get_latest_news().height == 1


def test_spatial_join_finds_near_region(store):
    store.upsert_incidents([make_incident(fault_location={"lat": 26.07, "lon": 50.55})])
    df = store.spatial_join_incidents_to_regions()
    assert "aws:me-south-1" in df["region_id"].to_list()


def test_risk_brief_persist_and_audit(store):
    brief = make_brief()
    store.persist_risk_brief(brief, json.dumps({"headline": "x"}))
    row = store.get_latest_risk_briefs().row(0, named=True)
    assert row["headline"] == "Test brief headline"
    assert row["risk_level"] == "high"
    raw = store.connection.execute(
        "SELECT raw_llm_response FROM risk_briefs").fetchone()[0]
    assert "model_version" in raw


def test_llm_context_empty_and_populated(store):
    assert "No active cable incidents" in store.get_incident_context_for_llm()
    store.upsert_incidents([make_incident()])
    assert "equiano" in store.get_incident_context_for_llm()


def test_prune_old_metrics_noop(store):
    assert store.prune_old_latency_metrics() == 0


def test_h3_refresh_graceful(store):
    store.upsert_incidents([make_incident()])
    assert store.refresh_h3_risk_zones() >= 0
