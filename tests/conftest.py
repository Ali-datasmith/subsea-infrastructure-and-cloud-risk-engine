from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import httpx
import pytest

from src.config import EngineSettings
from src.schemas import (
    CableIncidentPayload, CloudLatencyMetric, NewsRiskSignal, WeatherRiskSignal,
)

REPO_ROOT = Path(__file__).resolve().parents[1]


# --- HTTPX Fakes (shared across ingestion and free_feeds tests) ---
class FakeResponse:
    def __init__(self, data, status=200):
        self._data, self.status_code = data, status

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError(
                "boom", request=httpx.Request("GET", "http://t"),
                response=httpx.Response(self.status_code))

    def json(self):
        return self._data


def fake_client(handler):
    class _Client:
        def __init__(self, *a, **k): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def get(self, url, **kw): return handler(url, **kw)
    return _Client
# ------------------------------------------------------------------


@pytest.fixture()
def settings(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)  # isolate data/ + quarantine writes per test
    return EngineSettings(
        duckdb_path="data/test.duckdb",
        ddl_path=str(REPO_ROOT / "ddl.sql"),
        log_file="logs/test.jsonl",
    )


@pytest.fixture()
def store(settings):
    from src.db_engine import RiskEngineStore
    s = RiskEngineStore(settings)
    s.bootstrap_schema()
    yield s
    s.close()


def make_incident(**over) -> CableIncidentPayload:
    base = dict(
        incident_id=uuid4(), cable_id="equiano", cable_name="Equiano",
        fault_type="equipment_failure", status="degraded", zone="west_africa_coast",
        fault_location={"lat": 6.5, "lon": 3.4},
        detected_at=datetime.now(timezone.utc), reported_by="pytest",
        estimated_repair_days=10,
    )
    base.update(over)
    return CableIncidentPayload(**base)


def make_metric(**over) -> CloudLatencyMetric:
    base = dict(
        provider="aws", origin_region="us-east-1", destination_region="eu-west-1",
        sampled_at=datetime.now(timezone.utc), latency_ms=120.0,
        baseline_latency_ms=100.0, packet_loss_pct=1.0, anomaly_score=0.5,
    )
    base.update(over)
    return CloudLatencyMetric(**base)


def make_weather(**over) -> WeatherRiskSignal:
    base = dict(
        zone="west_africa_coast", sample_lat=6.5, sample_lon=3.4,
        sampled_at=datetime.now(timezone.utc), weather_fault_probability=0.5,
    )
    base.update(over)
    return WeatherRiskSignal(**base)


def make_news(**over) -> NewsRiskSignal:
    base = dict(
        source="pytest", title="Subsea cable cut test", link="https://t/1",
        published_at=datetime.now(timezone.utc), zone="west_africa_coast",
        severity="medium",
    )
    base.update(over)
    return NewsRiskSignal(**base)


def make_brief(**over):
    from src.schemas import (
        CloudProvider, GeminiRiskBrief, GeopoliticalZone, RecommendedAction, RiskLevel,
    )
    base = dict(
        related_incident_ids=[uuid4()], headline="Test brief headline",
        executive_summary="Structured test summary.", risk_level=RiskLevel.HIGH,
        affected_zones=[GeopoliticalZone.RED_SEA],
        affected_cloud_providers=[CloudProvider.AWS],
        estimated_impacted_traffic_pct=35.0, confidence_score=0.85,
        recommended_actions=[RecommendedAction(
            action="Reroute traffic", priority=RiskLevel.HIGH, rationale="test")],
    )
    base.update(over)
    return GeminiRiskBrief(**base)
