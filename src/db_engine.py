"""
DuckDB analytical store with native GEOMETRY + VARIANT types.
Zero-copy Arrow interop with Polars LazyFrames.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional
from uuid import UUID

import duckdb
import polars as pl
from loguru import logger

from src.config import EngineSettings
from src.schemas import CableIncidentPayload, CloudLatencyMetric, GeminiRiskBrief


class RiskEngineStore:
    """Manages the DuckDB connection, schema bootstrap, and all CRUD operations."""

    def __init__(self, settings: EngineSettings) -> None:
        self._settings = settings
        db_dir = Path(settings.duckdb_path).parent
        db_dir.mkdir(parents=True, exist_ok=True)
        self._con = duckdb.connect(settings.duckdb_path)
        self._h3_available = False
        self._load_extensions()
        logger.info("DuckDB connected at {} with spatial + h3 extensions", settings.duckdb_path)

    def _load_extensions(self) -> None:
        """
        Load DuckDB extensions with full resilience for ephemeral Cloud containers.
        - spatial (official repo) is REQUIRED for GEOMETRY types.
        - h3 (community repo) is OPTIONAL; gated behind allow_community_extensions
          and wrapped so a download hiccup never crashes app startup.
        """
        try:
            self._con.execute("INSTALL spatial")
        except Exception as exc:
            logger.warning("spatial INSTALL note (may already be cached): {}", exc)
        self._con.execute("LOAD spatial")
        logger.info("DuckDB spatial extension loaded")

        for flag_stmt in (
            "SET allow_community_extensions = true",
            "SET allow_unsigned_extensions = true",
        ):
            try:
                self._con.execute(flag_stmt)
            except Exception as exc:
                logger.debug("Extension flag not applicable on this build: {}", exc)

        try:
            self._con.execute("INSTALL h3 FROM community")
        except Exception as exc:
            logger.warning("h3 INSTALL skipped (community repo unreachable): {}", exc)
        try:
            self._con.execute("LOAD h3")
            self._h3_available = True
            logger.info("DuckDB h3 extension loaded")
        except Exception as exc:
            self._h3_available = False
            logger.warning("h3 LOAD skipped — H3HexagonLayer will render empty: {}", exc)

    @property
    def connection(self) -> duckdb.DuckDBPyConnection:
        return self._con

    def bootstrap_schema(self) -> None:
        """Execute DDL script to create all tables and seed reference data."""
        ddl_path = Path(self._settings.ddl_path)
        if not ddl_path.exists():
            logger.error("DDL file not found at {}", ddl_path.resolve())
            raise FileNotFoundError(f"DDL file not found: {ddl_path.resolve()}")
        ddl_sql = ddl_path.read_text(encoding="utf-8")
        self._con.execute(ddl_sql)
        logger.info("DuckDB schema bootstrapped from {}", ddl_path.resolve())

    # =========================================================================
    # Incident upsert (zero-copy Arrow from Polars)
    # =========================================================================
    def upsert_incidents(self, incidents: list[CableIncidentPayload]) -> int:
        """
        Convert validated Pydantic models → Polars DataFrame → DuckDB via Arrow.
        Spatial POINT constructed in SQL from lat/lon columns.
        """
        if not incidents:
            logger.warning("No incidents to upsert — skipping")
            return 0

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
                    "vessel_correlations": json.dumps(
                        [vc.model_dump(mode="json") for vc in inc.vessel_correlations]
                    ),
                    "raw_source_payload": json.dumps(inc.raw_source_payload),
                }
            )

        incidents_df = pl.DataFrame(rows)
        logger.debug("Prepared {} incident rows for Arrow transfer", len(rows))

        self._con.execute(
            """
            INSERT OR REPLACE INTO cable_incidents (
                incident_id, cable_id, fault_type, status, zone,
                fault_location, detected_at, reported_by,
                affected_segment_km, repair_vessel_assigned,
                estimated_repair_days, vessel_correlations,
                raw_source_payload, ingested_at
            )
            SELECT
                incident_id::UUID,
                cable_id,
                fault_type,
                status,
                zone,
                ST_Point(lon, lat) AS fault_location,
                detected_at,
                reported_by,
                affected_segment_km,
                repair_vessel_assigned,
                estimated_repair_days,
                vessel_correlations::VARIANT,
                raw_source_payload::VARIANT,
                current_timestamp
            FROM incidents_df
            """
        )
        row_count = self._con.execute("SELECT changes()").fetchone()[0]
        logger.info("Upserted {} cable incidents via zero-copy Arrow", row_count)
        return row_count

    # =========================================================================
    # Latency metrics upsert
    # =========================================================================
    def upsert_latency_metrics(self, metrics: list[CloudLatencyMetric]) -> int:
        """Insert cloud latency metrics via Polars → Arrow → DuckDB."""
        if not metrics:
            logger.warning("No latency metrics to upsert — skipping")
            return 0

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

        metrics_df = pl.DataFrame(rows)
        self._con.execute(
            """
            INSERT OR REPLACE INTO cloud_latency_metrics
            SELECT * FROM metrics_df
            """
        )
        row_count = self._con.execute("SELECT changes()").fetchone()[0]
        logger.info("Upserted {} latency metrics via zero-copy Arrow", row_count)
        return row_count

    # =========================================================================
    # Risk brief persistence
    # =========================================================================
    def persist_risk_brief(self, brief: GeminiRiskBrief, raw_response: str) -> None:
        """Store a validated Gemini risk brief with full raw audit trail."""
        actions_json = json.dumps([a.model_dump(mode="json") for a in brief.recommended_actions])
        incident_ids = [str(iid) for iid in brief.related_incident_ids]
        zones = [z.value for z in brief.affected_zones]
        providers = [p.value for p in brief.affected_cloud_providers]

        self._con.execute(
            """
            INSERT OR REPLACE INTO risk_briefs (
                brief_id, generated_at, related_incident_ids,
                headline, executive_summary, risk_level,
                affected_zones, affected_cloud_providers,
                estimated_impacted_traffic_pct, confidence_score,
                recommended_actions, model_version, raw_llm_response
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?::VARIANT, ?, ?::VARIANT)
            """,
            [
                str(brief.brief_id),
                brief.generated_at,
                incident_ids,
                brief.headline,
                brief.executive_summary,
                brief.risk_level.value,
                zones,
                providers,
                brief.estimated_impacted_traffic_pct,
                brief.confidence_score,
                actions_json,
                brief.model_version,
                raw_response,
            ],
        )
        logger.info("Persisted risk brief {} (risk={})", brief.brief_id, brief.risk_level.value)

    # =========================================================================
    # Spatial join: incidents → nearest cloud regions
    # =========================================================================
    def spatial_join_incidents_to_regions(self) -> pl.DataFrame:
        """
        Execute ST_DWithin spatial join: each incident matched to cloud regions
        within the configured radius. Returns Polars DataFrame via Arrow (no pandas).
        """
        radius_m = self._settings.spatial_join_radius_km * 1000.0
        result = self._con.execute(
            f"""
            SELECT
                ci.incident_id::VARCHAR AS incident_id,
                ci.cable_id,
                ci.fault_type,
                ci.status,
                ci.zone,
                ST_X(ci.fault_location) AS incident_lon,
                ST_Y(ci.fault_location) AS incident_lat,
                ci.detected_at,
                cr.region_id,
                cr.provider,
                cr.display_name AS region_name,
                ST_X(cr.location_geom) AS region_lon,
                ST_Y(cr.location_geom) AS region_lat,
                ST_Distance_Sphere(ci.fault_location, cr.location_geom) / 1000.0 AS distance_km
            FROM cable_incidents ci
            CROSS JOIN cloud_regions cr
            WHERE ST_DWithin(ci.fault_location, cr.location_geom, {radius_m})
            ORDER BY ci.detected_at DESC, distance_km ASC
            """
        )
        arrow_table = result.fetch_arrow_table()
        pl_df = pl.from_arrow(arrow_table)
        if pl_df is None:
            pl_df = pl.DataFrame()
        logger.info("Spatial join returned {} incident-region pairs", len(pl_df))
        return pl_df

    # =========================================================================
    # H3 risk zone materialization
    # =========================================================================
    def refresh_h3_risk_zones(self) -> int:
        """
        Rebuild h3_risk_zones from cable_incidents using H3 hexagonal indexing.
        No-ops gracefully if the h3 extension could not be loaded on this host.
        """
        if not self._h3_available:
            logger.warning("h3 extension unavailable — skipping H3 zone refresh")
            return 0

        resolution = self._settings.h3_resolution
        try:
            self._con.execute("DELETE FROM h3_risk_zones")
            self._con.execute(
                f"""
                INSERT INTO h3_risk_zones (h3_index, resolution, incident_count, max_risk_level, avg_anomaly_score, affected_cable_ids, computed_at)
                SELECT
                    h3_latlng_to_cell(ST_Y(fault_location), ST_X(fault_location), {resolution}) AS h3_index,
                    {resolution} AS resolution,
                    COUNT(*) AS incident_count,
                    CASE
                        WHEN SUM(CASE WHEN status = 'cut' THEN 1 ELSE 0 END) > 0 THEN 'critical'
                        WHEN SUM(CASE WHEN status = 'under_repair' THEN 1 ELSE 0 END) > 0 THEN 'high'
                        WHEN SUM(CASE WHEN status = 'degraded' THEN 1 ELSE 0 END) > 0 THEN 'medium'
                        ELSE 'low'
                    END AS max_risk_level,
                    0.0 AS avg_anomaly_score,
                    LIST(DISTINCT cable_id) AS affected_cable_ids,
                    current_timestamp AS computed_at
                FROM cable_incidents
                GROUP BY h3_index
                """
            )
            count = self._con.execute("SELECT COUNT(*) FROM h3_risk_zones").fetchone()[0]
            logger.info("Refreshed h3_risk_zones: {} cells at resolution {}", count, resolution)
            return count
        except Exception as exc:
            logger.error("H3 refresh failed (non-fatal): {}", exc)
            return 0

    # =========================================================================
    # Query helpers (return Polars DataFrames via Arrow)
    # =========================================================================
    def get_cables_with_endpoints(self) -> pl.DataFrame:
        """Retrieve cable arcs with source/target landing point coordinates."""
        result = self._con.execute(
            """
            SELECT
                sc.cable_id,
                sc.cable_name,
                COALESCE(
                    (SELECT ci.status FROM cable_incidents ci
                     WHERE ci.cable_id = sc.cable_id
                     ORDER BY ci.detected_at DESC LIMIT 1),
                    'active'
                ) AS status,
                ST_X(lp_src.location_geom) AS source_lon,
                ST_Y(lp_src.location_geom) AS source_lat,
                ST_X(lp_tgt.location_geom) AS target_lon,
                ST_Y(lp_tgt.location_geom) AS target_lat
            FROM subsea_cables sc
            JOIN cable_landing_points lp_src
                ON lp_src.cable_id = sc.cable_id
                AND lp_src.landing_id = (
                    SELECT MIN(landing_id) FROM cable_landing_points WHERE cable_id = sc.cable_id
                )
            JOIN cable_landing_points lp_tgt
                ON lp_tgt.cable_id = sc.cable_id
                AND lp_tgt.landing_id = (
                    SELECT MAX(landing_id) FROM cable_landing_points WHERE cable_id = sc.cable_id
                )
            """
        )
        arrow_table = result.fetch_arrow_table()
        df = pl.from_arrow(arrow_table)
        logger.debug("Retrieved {} cable arcs with endpoints", len(df))
        return df

    def get_cloud_regions_with_anomaly(self) -> pl.DataFrame:
        """Retrieve cloud regions joined with latest anomaly scores."""
        result = self._con.execute(
            """
            SELECT
                cr.region_id,
                cr.display_name,
                cr.provider,
                ST_X(cr.location_geom) AS lon,
                ST_Y(cr.location_geom) AS lat,
                COALESCE(latest_anomaly.anomaly_score, 0.0) AS anomaly_score
            FROM cloud_regions cr
            LEFT JOIN (
                SELECT
                    origin_region,
                    provider,
                    anomaly_score,
                    ROW_NUMBER() OVER (
                        PARTITION BY origin_region, provider
                        ORDER BY sampled_at DESC
                    ) AS rn
                FROM cloud_latency_metrics
            ) latest_anomaly
                ON latest_anomaly.origin_region = cr.region_code
                AND latest_anomaly.provider = cr.provider
                AND latest_anomaly.rn = 1
            """
        )
        arrow_table = result.fetch_arrow_table()
        df = pl.from_arrow(arrow_table)
        logger.debug("Retrieved {} cloud regions with anomaly data", len(df))
        return df

    def get_h3_risk_zones(self) -> pl.DataFrame:
        """Retrieve materialized H3 risk zones for visualization."""
        result = self._con.execute(
            """
            SELECT h3_index, incident_count, avg_anomaly_score, max_risk_level
            FROM h3_risk_zones
            """
        )
        arrow_table = result.fetch_arrow_table()
        df = pl.from_arrow(arrow_table)
        logger.debug("Retrieved {} H3 risk zones", len(df))
        return df

    def get_active_incidents(self) -> pl.DataFrame:
        """Retrieve active (non-resolved) incidents for scatter plot markers."""
        result = self._con.execute(
            """
            SELECT
                incident_id::VARCHAR AS incident_id,
                cable_id,
                fault_type,
                status,
                zone,
                ST_X(fault_location) AS lon,
                ST_Y(fault_location) AS lat,
                detected_at,
                estimated_repair_days
            FROM cable_incidents
            WHERE status IN ('cut', 'degraded', 'under_repair')
            ORDER BY detected_at DESC
            """
        )
        arrow_table = result.fetch_arrow_table()
        df = pl.from_arrow(arrow_table)
        logger.debug("Retrieved {} active incidents", len(df))
        return df

    def get_latest_risk_briefs(self, limit: int = 10) -> pl.DataFrame:
        """Retrieve most recent risk briefs for the digest page."""
        result = self._con.execute(
            f"""
            SELECT
                brief_id::VARCHAR AS brief_id,
                generated_at,
                headline,
                executive_summary,
                risk_level,
                affected_zones,
                affected_cloud_providers,
                estimated_impacted_traffic_pct,
                confidence_score,
                model_version
            FROM risk_briefs
            ORDER BY generated_at DESC
            LIMIT {limit}
            """
        )
        arrow_table = result.fetch_arrow_table()
        df = pl.from_arrow(arrow_table)
        logger.debug("Retrieved {} risk briefs", len(df))
        return df

    def get_incident_context_for_llm(self, limit: int = 20) -> str:
        """
        Build a structured text context of recent incidents for Gemini prompt.
        Groups by zone and includes vessel correlations.
        """
        result = self._con.execute(
            f"""
            SELECT
                incident_id::VARCHAR AS incident_id,
                cable_id,
                fault_type,
                status,
                zone,
                ST_Y(fault_location) AS lat,
                ST_X(fault_location) AS lon,
                detected_at,
                reported_by,
                estimated_repair_days,
                vessel_correlations
            FROM cable_incidents
            WHERE status IN ('cut', 'degraded', 'under_repair')
            ORDER BY detected_at DESC
            LIMIT {limit}
            """
        )
        arrow_table = result.fetch_arrow_table()
        df = pl.from_arrow(arrow_table)

        if len(df) == 0:
            return "No active cable incidents currently in the system."

        context_lines: list[str] = [
            "ACTIVE SUBSEA CABLE INCIDENTS FOR RISK ASSESSMENT:",
            "=" * 60,
        ]
        for row in df.to_dicts():
            context_lines.append(
                f"- [{row['zone']}] {row['cable_id']} | "
                f"type={row['fault_type']} | status={row['status']} | "
                f"location=({row['lat']:.2f}, {row['lon']:.2f}) | "
                f"detected={row['detected_at']} | "
                f"repair_eta={row['estimated_repair_days']}d | "
                f"vessels={row['vessel_correlations']}"
            )

        context_lines.append("=" * 60)
        context_lines.append(
            "Generate a structured risk brief assessing cloud infrastructure impact."
        )
        return "\n".join(context_lines)

    def get_quarantine_count(self) -> int:
        """Return count of quarantined payload files on disk."""
        quarantine_dir = self._settings.quarantine_dir
        if not quarantine_dir.exists():
            return 0
        return len(list(quarantine_dir.glob("*.json")))

    def prune_old_latency_metrics(self, retention_days: int = 90) -> int:
        """Remove latency metrics older than retention window."""
        self._con.execute(
            f"""
            DELETE FROM cloud_latency_metrics
            WHERE sampled_at < current_timestamp - INTERVAL '{retention_days}' DAY
            """
        )
        pruned = self._con.execute("SELECT changes()").fetchone()[0]
        logger.info("Pruned {} latency metrics older than {} days", pruned, retention_days)
        return pruned

    def close(self) -> None:
        """Gracefully close the DuckDB connection."""
        self._con.close()
        logger.info("DuckDB connection closed")
