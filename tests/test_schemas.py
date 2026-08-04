import pytest
from pydantic import ValidationError

from src.schemas import (
    CableIncidentPayload, CloudLatencyMetric, GeminiRiskBrief, RiskLevel, VesselCorrelation,
)
from conftest import make_incident, make_metric, make_brief


def test_valid_incident_parses_and_utc_normalizes():
    inc = make_incident(detected_at="2026-08-01T00:00:00")
    assert inc.detected_at.tzinfo is not None


def test_lat_out_of_bounds_rejected():
    with pytest.raises(ValidationError):
        make_incident(fault_location={"lat": 91.0, "lon": 0.0})


def test_extra_fields_forbidden_at_edge():
    with pytest.raises(ValidationError):
        make_incident(unexpected_field=1)


def test_mmsi_must_be_nine_chars():
    with pytest.raises(ValidationError):
        VesselCorrelation(mmsi="123", distance_to_fault_km=1.0)


def test_latency_delta_pct():
    assert make_metric(latency_ms=150.0, baseline_latency_ms=100.0).latency_delta_pct == 50.0
    assert make_metric(baseline_latency_ms=0.0).latency_delta_pct == 0.0


def test_risk_level_enum_contract():
    assert RiskLevel.HIGH.value == "high"  # actual enum value


def test_brief_extra_keys_ignored_and_limits():
    b = make_brief()
    assert GeminiRiskBrief(**{**b.model_dump(), "unknown": 1}).brief_id == b.brief_id
    with pytest.raises(ValidationError):
        make_brief(headline="x" * 141)
    with pytest.raises(ValidationError):
        make_brief(recommended_actions=[])
