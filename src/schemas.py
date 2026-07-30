"""
Pydantic v2 edge-validation models for all ingestion payloads and LLM outputs.
These are the ONLY accepted shapes crossing the ingestion boundary.
"""
from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Optional
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator


# =============================================================================
# Shared enums
# =============================================================================


class FaultType(str, Enum):
    ANCHOR_DRAG = "anchor_drag"
    SEISMIC_ACTIVITY = "seismic_activity"
    FISHING_TRAWLER = "fishing_trawler"
    SUSPECTED_SABOTAGE = "suspected_sabotage"
    SHARK_BITE = "shark_bite"
    EQUIPMENT_FAILURE = "equipment_failure"
    UNKNOWN = "unknown"


class CableStatus(str, Enum):
    ACTIVE = "active"
    DEGRADED = "degraded"
    CUT = "cut"
    UNDER_REPAIR = "under_repair"
    PLANNED = "planned"


class RiskLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class CloudProvider(str, Enum):
    AWS = "aws"
    AZURE = "azure"
    GCP = "gcp"
    ORACLE = "oci"


class GeopoliticalZone(str, Enum):
    RED_SEA = "red_sea_bab_el_mandeb"
    BALTIC_SEA = "baltic_sea"
    TAIWAN_LUZON_STRAIT = "taiwan_luzon_strait"
    MALACCA_SINGAPORE = "malacca_singapore_strait"
    WEST_AFRICA = "west_africa_coast"
    EGYPT_LAND_BRIDGE = "egypt_land_bridge"
    OTHER = "other"


# =============================================================================
# 2.1 Cable Incident Payload (ingestion edge model)
# =============================================================================


class LatLon(BaseModel):
    model_config = ConfigDict(frozen=True)
    lat: float = Field(..., ge=-90, le=90)
    lon: float = Field(..., ge=-180, le=180)


class VesselCorrelation(BaseModel):
    """AIS-derived vessel present near fault location/time window."""

    model_config = ConfigDict(extra="forbid")

    mmsi: str = Field(..., min_length=9, max_length=9)
    vessel_name: Optional[str] = None
    flag_state: Optional[str] = None
    distance_to_fault_km: float = Field(..., ge=0)
    is_flagged_shadow_fleet: bool = False


class CableIncidentPayload(BaseModel):
    """Validated shape for a single subsea cable fault/incident event."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    incident_id: UUID = Field(default_factory=uuid4)
    cable_id: str = Field(..., min_length=1, description="Stable cable system identifier")
    cable_name: str
    fault_type: FaultType
    status: CableStatus
    zone: GeopoliticalZone
    fault_location: LatLon
    detected_at: datetime
    reported_by: str = Field(..., description="Source feed name")
    affected_segment_km: Optional[float] = Field(default=None, ge=0)
    repair_vessel_assigned: Optional[str] = None
    estimated_repair_days: Optional[int] = Field(default=None, ge=0, le=365)
    vessel_correlations: list[VesselCorrelation] = Field(default_factory=list)
    raw_source_payload: dict = Field(
        default_factory=dict, description="Preserved for VARIANT storage"
    )

    @field_validator("detected_at")
    @classmethod
    def _tz_aware(cls, v: datetime) -> datetime:
        if v.tzinfo is None:
            return v.replace(tzinfo=timezone.utc)
        return v


# =============================================================================
# 2.2 Cloud Latency Metric (ingestion edge model)
# =============================================================================


class CloudLatencyMetric(BaseModel):
    """Validated shape for a single inter-region latency/health sample."""

    model_config = ConfigDict(extra="forbid")

    metric_id: UUID = Field(default_factory=uuid4)
    provider: CloudProvider
    origin_region: str = Field(..., description="e.g. us-east-1, westeurope")
    destination_region: str
    sampled_at: datetime
    latency_ms: float = Field(..., ge=0)
    baseline_latency_ms: float = Field(..., ge=0)
    packet_loss_pct: float = Field(..., ge=0, le=100)
    anomaly_score: float = Field(..., ge=0, le=1, description="0=nominal, 1=severe anomaly")
    nearest_cable_id: Optional[str] = Field(
        default=None,
        description="Populated post spatial-join in DuckDB, nullable at ingest",
    )

    @field_validator("sampled_at")
    @classmethod
    def _tz_aware(cls, v: datetime) -> datetime:
        if v.tzinfo is None:
            return v.replace(tzinfo=timezone.utc)
        return v

    @property
    def latency_delta_pct(self) -> float:
        if self.baseline_latency_ms == 0:
            return 0.0
        return ((self.latency_ms - self.baseline_latency_ms) / self.baseline_latency_ms) * 100


# =============================================================================
# 2.3 Gemini Output Brief (LLM structured output contract)
# =============================================================================


class RecommendedAction(BaseModel):
    # extra="ignore" (NOT "forbid") so the JSON schema sent to Gemini as
    # response_schema contains no "additionalProperties" key — Gemini rejects
    # that key with 400 INVALID_ARGUMENT.
    model_config = ConfigDict(extra="ignore")
    action: str
    priority: RiskLevel
    rationale: str


class GeminiRiskBrief(BaseModel):
    """
    Strict schema passed to Gemini as response_schema / JSON schema constraint.
    Round-tripped via model_validate_json() on the response before persistence.
    """

    # extra="ignore" so model_json_schema() omits "additionalProperties"
    # (Gemini's response_schema rejects that key — see the 400 INVALID_ARGUMENT).
    model_config = ConfigDict(extra="ignore")

    brief_id: UUID = Field(default_factory=uuid4)
    generated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    related_incident_ids: list[UUID]
    headline: str = Field(..., max_length=140)
    executive_summary: str = Field(..., max_length=1200)
    risk_level: RiskLevel
    affected_zones: list[GeopoliticalZone]
    affected_cloud_providers: list[CloudProvider]
    estimated_impacted_traffic_pct: float = Field(..., ge=0, le=100)
    confidence_score: float = Field(..., ge=0, le=1)
    recommended_actions: list[RecommendedAction] = Field(..., min_length=1, max_length=6)
    model_version: str = Field(default="gemini-2.0-flash")
# =============================================================================
# 2.4 Pass B — external free-tier signal models (weather + news + score)
# These are ingestion/read models only (never sent to Gemini as response_schema),
# so extra="ignore" keeps them lenient against messy external sources.
# =============================================================================


class NewsRiskSignal(BaseModel):
    """A keyword-matched news headline tagged to a geopolitical zone + severity."""

    model_config = ConfigDict(extra="ignore")

    news_id: UUID = Field(default_factory=uuid4)
    source: str
    title: str
    link: str
    published_at: datetime
    zone: str
    severity: str = Field(default="medium")
    matched_keywords: list[str] = Field(default_factory=list)
    raw_payload: dict = Field(default_factory=dict)

    @field_validator("published_at")
    @classmethod
    def _tz_aware(cls, v: datetime) -> datetime:
        if v.tzinfo is None:
            return v.replace(tzinfo=timezone.utc)
        return v


class WeatherRiskSignal(BaseModel):
    """Marine/forecast sample over a cable corridor, scored for fault risk."""

    model_config = ConfigDict(extra="ignore")

    sample_id: UUID = Field(default_factory=uuid4)
    cable_id: Optional[str] = None
    zone: str
    sample_lat: float = Field(..., ge=-90, le=90)
    sample_lon: float = Field(..., ge=-180, le=180)
    sampled_at: datetime
    wind_speed_kmh: float = Field(default=0.0, ge=0)
    wind_gust_kmh: float = Field(default=0.0, ge=0)
    wave_height_m: float = Field(default=0.0, ge=0)
    precipitation_mm: float = Field(default=0.0, ge=0)
    weather_fault_probability: float = Field(..., ge=0, le=1)
    repair_vessel_delayed: bool = False
    raw_payload: dict = Field(default_factory=dict)

    @field_validator("sampled_at")
    @classmethod
    def _tz_aware(cls, v: datetime) -> datetime:
        if v.tzinfo is None:
            return v.replace(tzinfo=timezone.utc)
        return v


class CableRiskScore(BaseModel):
    """Per-cable composite risk (read model from the scorer)."""

    model_config = ConfigDict(extra="ignore")

    cable_id: str
    zone: str
    incident_score: float = Field(..., ge=0, le=1)
    weather_score: float = Field(..., ge=0, le=1)
    news_score: float = Field(..., ge=0, le=1)
    composite_score: float = Field(..., ge=0, le=1)
    max_news_severity: Optional[str] = None
    repair_delayed: bool = False
    computed_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
