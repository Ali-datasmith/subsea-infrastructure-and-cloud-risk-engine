import asyncio

import httpx
import pytest

from src.ingestion import (
    CableFaultFeedClient, CloudProbeClient, run_ingestion_cycle,
)
from conftest import make_incident, FakeResponse, fake_client


def test_fetch_quarantines_malformed(settings, monkeypatch):
    good = make_incident().model_dump(mode="json")
    monkeypatch.setattr("httpx.AsyncClient",
                        fake_client(lambda url, **kw: FakeResponse([good, {"bad": 1}])))
    out = asyncio.run(CableFaultFeedClient(settings).fetch_incidents("2026-01-01T00:00:00Z"))
    assert len(out) == 1
    assert len(list(settings.quarantine_dir.glob("*.json"))) == 1


def test_retries_then_raises(settings, monkeypatch):
    monkeypatch.setattr("httpx.AsyncClient",
                        fake_client(lambda url, **kw: FakeResponse(None, 500)))
    with pytest.raises(httpx.HTTPStatusError):
        asyncio.run(CableFaultFeedClient(settings).fetch_incidents("2026-01-01T00:00:00Z"))


def test_cycle_degrades_to_empty(settings, monkeypatch):
    monkeypatch.setattr("httpx.AsyncClient",
                        fake_client(lambda url, **kw: FakeResponse(None, 500)))
    incidents, metrics = asyncio.run(run_ingestion_cycle(settings))
    assert incidents == [] and metrics == []   # degrade-by-design


def test_unknown_provider_returns_empty(settings):
    assert asyncio.run(CloudProbeClient(settings).fetch_latency_metrics("oci")) == []


def test_cloud_probe_quarantines_mismatch(settings, monkeypatch):
    monkeypatch.setattr("httpx.AsyncClient",
                        fake_client(lambda url, **kw: FakeResponse([{"status": "ok"}])))
    out = asyncio.run(CloudProbeClient(settings).fetch_latency_metrics("aws"))
    assert out == []
    assert len(list(settings.quarantine_dir.glob("*.json"))) >= 1
