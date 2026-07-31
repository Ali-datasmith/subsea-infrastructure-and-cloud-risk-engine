"""
Async resilient ingestion clients for cable fault feeds, AIS vessel tracking,
and cloud latency/status probes. All network calls use httpx + tenacity.

The full ingestion cycle is DEGRADE-BY-DESIGN: a dead feed (e.g. the placeholder
cable tracker) yields an empty list with a warning, never a raised exception that
blanks the UI.
"""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Any, Optional

import httpx
from loguru import logger
from tenacity import (
    before_sleep_log,
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from src.config import EngineSettings
from src.data_engine import quarantine_payload
from src.schemas import CableIncidentPayload, CloudLatencyMetric, VesselCorrelation


# =============================================================================
# Cable Fault Feed Client
# =============================================================================

class CableFaultFeedClient:
    """Async client for subsea cable fault/incident feeds."""

    def __init__(self, settings: EngineSettings) -> None:
        self._base_url = settings.cable_fault_feed_url
        self._settings = settings
        self._timeout = httpx.Timeout(8.0, connect=3.0)

    @retry(
        stop=stop_after_attempt(2),  # short: a dead host must not hang the UI
        wait=wait_exponential(multiplier=1, min=1, max=3),
        retry=retry_if_exception_type(
            (httpx.HTTPStatusError, httpx.ConnectError, httpx.TimeoutException)
        ),
        reraise=True,
    )
    async def fetch_incidents(self, since_iso: str) -> list[CableIncidentPayload]:
        """Fetch + validate incidents; quarantine malformed entries."""
        logger.info("Fetching cable incidents since {} from {}", since_iso, self._base_url)

        async with httpx.AsyncClient(base_url=self._base_url, timeout=self._timeout) as client:
            resp = await client.get("/incidents", params={"since": since_iso})
            resp.raise_for_status()
            raw_items: list[dict[str, Any]] = resp.json()

        validated: list[CableIncidentPayload] = []
        rejected_count = 0
        for item in raw_items:
            try:
                payload = CableIncidentPayload.model_validate(item)
                validated.append(payload)
            except Exception as exc:
                rejected_count += 1
                quarantine_payload(
                    payload=item,
                    reason=f"CableIncidentPayload validation failed: {exc}",
                    settings=self._settings,
                )

        logger.info(
            "Fetched {} valid incidents ({} rejected/quarantined) from {}",
            len(validated),
            rejected_count,
            self._base_url,
        )
        return validated


# =============================================================================
# AIS Vessel Correlation Client
# =============================================================================

class AISVesselClient:
    """Async client for AIS vessel tracking — shadow fleet correlation."""

    def __init__(self, settings: EngineSettings) -> None:
        self._base_url = settings.ais_feed_url
        self._settings = settings
        self._timeout = httpx.Timeout(20.0, connect=5.0)

    @retry(
        stop=stop_after_attempt(4),
        wait=wait_exponential(multiplier=1, min=2, max=20),
        retry=retry_if_exception_type(
            (httpx.HTTPStatusError, httpx.ConnectError, httpx.TimeoutException)
        ),
        reraise=True,
    )
    async def fetch_vessels_near(
        self,
        lat: float,
        lon: float,
        radius_km: float = 50.0,
        since_iso: Optional[str] = None,
    ) -> list[VesselCorrelation]:
        """Query AIS feed for vessels within radius_km of a coordinate."""
        params: dict[str, Any] = {"lat": lat, "lon": lon, "radius_km": radius_km}
        if since_iso:
            params["since"] = since_iso

        logger.info("Querying AIS vessels near ({}, {}) radius={}km", lat, lon, radius_km)

        async with httpx.AsyncClient(base_url=self._base_url, timeout=self._timeout) as client:
            resp = await client.get("/vessels/near", params=params)
            resp.raise_for_status()
            raw_vessels: list[dict[str, Any]] = resp.json()

        correlations: list[VesselCorrelation] = []
        for vessel in raw_vessels:
            try:
                corr = VesselCorrelation.model_validate(vessel)
                correlations.append(corr)
            except Exception as exc:
                logger.warning("Rejected malformed AIS vessel record: {}", exc)

        logger.info("Found {} vessels near ({}, {})", len(correlations), lat, lon)
        return correlations


# =============================================================================
# Cloud Latency / Status Probe Client
# =============================================================================

class CloudProbeClient:
    """Async client for cloud provider latency and status telemetry."""

    def __init__(self, settings: EngineSettings) -> None:
        self._settings = settings
        self._timeout = httpx.Timeout(15.0, connect=5.0)
        self._provider_urls: dict[str, str] = {
            "aws": settings.cloud_status_aws_url,
            "azure": settings.cloud_status_azure_url,
            "gcp": settings.cloud_status_gcp_url,
        }

    @retry(
        stop=stop_after_attempt(2),
        wait=wait_exponential(multiplier=1, min=1, max=6),
        retry=retry_if_exception_type(
            (httpx.HTTPStatusError, httpx.ConnectError, httpx.TimeoutException)
        ),
        reraise=True,
    )
    async def fetch_latency_metrics(self, provider: str) -> list[CloudLatencyMetric]:
        """Fetch probe results; follow_redirects fixes the Azure 301. Mismatched
        payloads (status pages vs latency schema) are quarantined, not raised."""
        base_url = self._provider_urls.get(provider)
        if not base_url:
            logger.error("No configured URL for provider '{}'", provider)
            return []

        logger.info("Fetching latency metrics for provider '{}' from {}", provider, base_url)

        async with httpx.AsyncClient(timeout=self._timeout, follow_redirects=True) as client:
            resp = await client.get(base_url, params={"format": "json", "type": "latency"})
            resp.raise_for_status()
            raw_metrics: list[dict[str, Any]] = resp.json()

        validated: list[CloudLatencyMetric] = []
        for item in raw_metrics:
            try:
                if "provider" not in item:
                    item["provider"] = provider
                metric = CloudLatencyMetric.model_validate(item)
                validated.append(metric)
            except Exception as exc:
                quarantine_payload(
                    payload=item,
                    reason=f"CloudLatencyMetric validation failed for {provider}: {exc}",
                    settings=self._settings,
                )

        logger.info("Fetched {} valid latency metrics for '{}'", len(validated), provider)
        return validated

    async def fetch_all_providers(self) -> list[CloudLatencyMetric]:
        """Fetch latency metrics from all configured providers concurrently."""
        tasks = [self.fetch_latency_metrics(provider) for provider in self._provider_urls.keys()]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        all_metrics: list[CloudLatencyMetric] = []
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                provider = list(self._provider_urls.keys())[i]
                logger.warning("Provider '{}' probe unavailable (degraded): {}", provider, result)
            else:
                all_metrics.extend(result)

        logger.info("Total latency metrics fetched across all providers: {}", len(all_metrics))
        return all_metrics


# =============================================================================
# Orchestrator: run full ingestion cycle (degrade-by-design)
# =============================================================================

async def run_ingestion_cycle(settings: EngineSettings) -> tuple[
    list[CableIncidentPayload],
    list[CloudLatencyMetric],
]:
    """Execute a full ingestion cycle. A failing feed degrades to an empty list
    instead of raising, so the UI button never shows a scary traceback."""
    logger.info("Starting full ingestion cycle")

    cable_client = CableFaultFeedClient(settings)
    cloud_client = CloudProbeClient(settings)

    since_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    incidents_task = cable_client.fetch_incidents(since_iso=since_iso)
    metrics_task = cloud_client.fetch_all_providers()

    results = await asyncio.gather(incidents_task, metrics_task, return_exceptions=True)

    incidents = results[0] if isinstance(results[0], list) else []
    metrics = results[1] if isinstance(results[1], list) else []

    if isinstance(results[0], Exception):
        logger.warning("Cable fault feed unavailable (degraded, non-fatal): {}", results[0])
    if isinstance(results[1], Exception):
        logger.warning("Cloud probes unavailable (degraded, non-fatal): {}", results[1])

    logger.info(
        "Ingestion cycle complete: {} incidents, {} latency metrics",
        len(incidents),
        len(metrics),
    )
    return incidents, metrics
