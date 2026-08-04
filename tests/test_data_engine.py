import json

import polars as pl
import pytest
from pandera.errors import SchemaError

from src.data_engine import (
    compute_anomaly_enriched_h3, incidents_to_lazyframe, quarantine_payload,
    validate_incidents,
)
from conftest import make_incident


def test_empty_incidents_lazyframe_has_full_schema():
    cols = incidents_to_lazyframe([]).collect().columns
    assert {"incident_id", "repair_vessel_assigned", "estimated_repair_days"} <= set(cols)


def test_incidents_to_lazyframe_values():
    df = incidents_to_lazyframe([make_incident(status="cut")]).collect()
    row = df.row(0, named=True)
    assert row["status"] == "cut" and row["zone"] == "west_africa_coast"


def test_pandera_gate_rejects_bad_fault_type():
    bad = pl.DataFrame([{
        "cable_id": "x", "fault_type": "meteor", "status": "cut",
        "lat": 0.0, "lon": 0.0, "estimated_repair_days": 5,
    }])
    with pytest.raises(SchemaError):
        validate_incidents(bad.lazy())


def test_pandera_gate_passes_good_row():
    good = pl.DataFrame([{
        "cable_id": "x", "fault_type": "anchor_drag", "status": "cut",
        "lat": 10.0, "lon": 10.0, "estimated_repair_days": 5,
    }])
    assert validate_incidents(good.lazy()).collect().height == 1


def test_quarantine_writes_reason_and_payload(settings):
    p = quarantine_payload({"a": 1}, "bad shape", settings)
    rec = json.loads(p.read_text())
    assert rec["reason"] == "bad shape" and rec["payload"] == {"a": 1}


def test_h3_enrichment_fills_anomaly():
    inc = pl.DataFrame([{"zone": "baltic_sea", "incident_count": 1}])
    lat = pl.DataFrame([{"origin_region": "baltic_sea", "anomaly_score": 0.7}])
    out = compute_anomaly_enriched_h3(inc, lat)
    assert out["anomaly_score"].to_list() == [0.7]


def test_h3_enrichment_empty_incidents():
    out = compute_anomaly_enriched_h3(pl.DataFrame(), pl.DataFrame())
    assert set(out.columns) >= {"h3_index", "incident_count", "avg_anomaly_score"}
