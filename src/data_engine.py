"""
Polars LazyFrame processing transforms and Pandera quality gates.
Ensures all data conforms to expected schemas before DuckDB ingestion.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from uuid import UUID

import pandera.polars as pa
import polars as pl
from loguru import logger
from pandera.polars import Check, Column, DataFrameSchema

from src.config import EngineSettings
from src.schemas import CableIncidentPayload, CloudLatencyMetric


# =============================================================================
# Pandera schema gates
# =============================================================================

cable_incidents_schema = DataFrameSchema(
    {
        "cable_id": Column(pl.Utf8, nullable=False),
        "fault_type": Column(
            pl.Utf8,
            Check.isin(
                [
                    "anchor_drag",
                    "seismic_activity",
                    "fishing_trawler",
                    "suspected_sabotage",
                    "shark_bite",
                    "equipment_failure",
                    "unknown",
                ]
            ),
        ),
        "status": Column(
            pl.Utf8,
            Check.isin(["active", "degraded", "cut", "under_repair", "planned"]),
        ),
        "lat": Column(pl.Float64, Check.between(-90, 90)),
        "lon": Column(pl.Float64, Check.between(-180, 180)),
        "estimated_repair_days": Column(pl.Int64, Check.between(0, 365), nullable=True),
    },
    strict=False,
    coerce=True,
)

latency_metrics_schema = DataFrameSchema(
    {
        "provider": Column(pl.Utf8, Check.isin(["aws", "azure", "gcp", "oci"])),
        "origin_region": Column(pl.Utf8, nullable=False),
        "destination_region": Column(pl.Utf8, nullable=False),
        "latency_ms": Column(pl.Float64, Check.greater_than_or_equal_to(0)),
        "baseline_latency_ms": Column(pl.Float64, Check.greater_than_or_equal_to(0)),
        "packet_loss_pct": Column(pl.Float64, Check.between(0, 100)),
        "anomaly_score": Column(pl.Float64, Check.between(0, 1)),
    },
    strict=False,
    coerce=True,
)


# =============================================================================
# Transform functions
# =============================================================================


def incidents_to_lazyframe(incidents: list[CableIncidentPayload]) -> pl.LazyFrame:
    """
    Convert validated CableIncidentPayload models into a Polars LazyFrame
    suitable for Pandera validation and DuckDB ingestion.
    """
    if not incidents:
        logger.warning("Empty incident list — returning empty LazyFrame")
        return pl.DataFrame(
            schema={
                "incident_id": pl.Utf8,
                "cable_id": pl.Utf8,
                "fault_type": pl.Utf8,
                "status": pl.Utf8,
                "zone": pl.Utf8,
                "lat": pl.Float64,
                "lon": pl.Float64,
                "detected_at": pl.Datetime(time_zone="UTC"),
                "reported_by": pl.Utf8,
                "affected_segment_km": pl.Float64,
                "repair_vessel_assigned": pl.Utf8,
                "estimated_repair_days": pl.Int64,
            }
        ).lazy()

    rows = []
    for inc in incidents:
        rows.append(
            {
                "incident_id": str(inc.incident_id),
                "cable_id": inc.cable_id,
                "fault_type": inc.fault_type.value,
                "status": inc.status.value,
                "zone": inc.zone.value,
                "lat": inc.fault_location.lat,
                "lon": inc.fault_location.lon,
                "detected_at": inc.detected_at,
                "reported_by": inc.reported_by,
                "affected_segment_km": inc.affected_segment_km,
                "repair_vessel_assigned": inc.repair_vessel_assigned,
                "estimated_repair_days": inc.estimated_repair_days,
            }
        )

    lf = pl.DataFrame(rows).lazy()
    logger.info("Converted {} incidents to LazyFrame", len(rows))
    return lf


def latency_to_lazyframe(metrics: list[CloudLatencyMetric]) -> pl.LazyFrame:
    """Convert validated CloudLatencyMetric models into a Polars LazyFrame."""
    if not metrics:
        logger.warning("Empty metrics list — returning empty LazyFrame")
        return pl.DataFrame(
            schema={
                "metric_id": pl.Utf8,
                "provider": pl.Utf8,
                "origin_region": pl.Utf8,
                "destination_region": pl.Utf8,
                "sampled_at": pl.Datetime(time_zone="UTC"),
                "latency_ms": pl.Float64,
                "baseline_latency_ms": pl.Float64,
                "packet_loss_pct": pl.Float64,
                "anomaly_score": pl.Float64,
                "nearest_cable_id": pl.Utf8,
            }
        ).lazy()

    rows = []
    for m in metrics:
        rows.append(
            {
                "metric_id": str(m.metric_id),
                "provider": m.provider.value,
                "origin_region": m.origin_region,
                "destination_region": m.destination_region,
                "sampled_at": m.sampled_at,
                "latency_ms": m.latency_ms,
                "baseline_latency_ms": m.baseline_latency_ms,
                "packet_loss_pct": m.packet_loss_pct,
                "anomaly_score": m.anomaly_score,
                "nearest_cable_id": m.nearest_cable_id,
            }
        )

    lf = pl.DataFrame(rows).lazy()
    logger.info("Converted {} latency metrics to LazyFrame", len(rows))
    return lf


# =============================================================================
# Quality gate functions
# =============================================================================


def validate_incidents(lf: pl.LazyFrame) -> pl.LazyFrame:
    """
    Apply Pandera schema gate to incident LazyFrame.
    Collects → validates → returns as LazyFrame.
    Raises pandera.errors.SchemaError on validation failure.
    """
    df = lf.collect(engine="streaming")
    if len(df) == 0:
        logger.info("Empty incidents DataFrame — skipping validation")
        return df.lazy()

    validated = cable_incidents_schema.validate(df)
    logger.info("Pandera gate passed for {} incident rows", len(validated))
    return validated.lazy()


def validate_latency_metrics(lf: pl.LazyFrame) -> pl.LazyFrame:
    """
    Apply Pandera schema gate to latency metrics LazyFrame.
    Collects → validates → returns as LazyFrame.
    """
    df = lf.collect(engine="streaming")
    if len(df) == 0:
        logger.info("Empty latency DataFrame — skipping validation")
        return df.lazy()

    validated = latency_metrics_schema.validate(df)
    logger.info("Pandera gate passed for {} latency metric rows", len(validated))
    return validated.lazy()


# =============================================================================
# Quarantine handler
# =============================================================================


def quarantine_payload(
    payload: dict,
    reason: str,
    settings: EngineSettings,
) -> Path:
    """
    Write a rejected payload to the quarantine directory with metadata.
    Returns the path to the quarantined file.
    """
    quarantine_dir = settings.quarantine_dir
    quarantine_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%f")
    filename = f"quarantine_{timestamp}.json"
    filepath = quarantine_dir / filename

    quarantine_record = {
        "quarantined_at": datetime.now(timezone.utc).isoformat(),
        "reason": reason,
        "payload": payload,
    }

    filepath.write_text(json.dumps(quarantine_record, indent=2, default=str), encoding="utf-8")
    logger.warning("Quarantined malformed payload to {}: {}", filepath, reason)
    return filepath


# =============================================================================
# H3 aggregation helper (Polars-side pre-processing)
# =============================================================================


def compute_anomaly_enriched_h3(
    incidents_df: pl.DataFrame,
    latency_df: pl.DataFrame,
) -> pl.DataFrame:
    """
    Enrich H3 zones with average anomaly scores from latency data.
    This supplements the DuckDB-side H3 materialization with latency correlation.
    """
    if len(incidents_df) == 0:
        logger.info("No incidents for H3 enrichment")
        return pl.DataFrame(
            schema={
                "h3_index": pl.Utf8,
                "incident_count": pl.Int64,
                "avg_anomaly_score": pl.Float64,
                "max_risk_level": pl.Utf8,
            }
        )

    if len(latency_df) == 0:
        logger.info("No latency data for H3 enrichment — using zero anomaly scores")
        return incidents_df

    enriched = incidents_df.join(
        latency_df.select(["origin_region", "anomaly_score"]),
        left_on="zone",
        right_on="origin_region",
        how="left",
    ).with_columns(pl.col("anomaly_score").fill_null(0.0))

    logger.info("H3 enrichment complete: {} rows", len(enriched))
    return enriched
