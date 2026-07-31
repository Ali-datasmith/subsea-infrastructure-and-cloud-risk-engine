"""
PyDeck layer factories for the 3D geospatial risk dashboard.

Basemap note: we deliberately do NOT pass an external style.json URL — on
Streamlit Cloud that path renders as a broken solid-colour wash. Omitting
map_style lets pydeck use its built-in, token-free, always-renders basemap.
A styled dark map is reintroduced in the Pass-C visual overhaul.

H3 note: deck.gl's H3HexagonLayer needs a valid hex cell id; an invalid one can
render a degenerate world-covering polygon. We therefore keep only records whose
h3_index matches the H3 hex-string format, so a bad/empty value degrades to an
empty layer instead of painting the map.
"""
from __future__ import annotations

import re
from typing import Optional

import polars as pl
import pydeck as pdk
from loguru import logger

# A valid H3 hex-string index is 15-16 hex characters.
_H3_HEX_RE = re.compile(r"^[0-9a-fA-F]{15,16}$")

# =============================================================================
# Color maps
# =============================================================================

STATUS_COLOR_MAP: dict[str, list[int]] = {
    "active": [46, 204, 113, 160],
    "degraded": [241, 196, 15, 200],
    "cut": [231, 76, 60, 230],
    "under_repair": [52, 152, 219, 200],
    "planned": [149, 165, 166, 120],
}

RISK_COLOR_MAP: dict[str, list[int]] = {
    "low": [26, 152, 80, 100],
    "medium": [253, 224, 139, 140],
    "high": [252, 141, 89, 180],
    "critical": [215, 48, 39, 220],
}

PROVIDER_COLOR_MAP: dict[str, list[int]] = {
    "aws": [255, 153, 0, 200],
    "azure": [0, 120, 212, 200],
    "gcp": [66, 133, 244, 200],
    "oci": [193, 53, 132, 200],
}


def _empty_layer(kind: str, layer_id: str) -> pdk.Layer:
    """Safe empty layer used when data is missing or a builder fails."""
    return pdk.Layer(kind, id=layer_id, data=[])


# =============================================================================
# Layer builders
# =============================================================================

def build_cable_arc_layer(cables_df: pl.DataFrame) -> pdk.Layer:
    """ArcLayer: one arc per cable segment, colored by live status."""
    if len(cables_df) == 0:
        logger.warning("No cable data for ArcLayer — returning empty layer")
        return _empty_layer("ArcLayer", "cable-arcs")

    records = cables_df.select(
        ["cable_id", "cable_name", "status", "source_lon", "source_lat", "target_lon", "target_lat"]
    ).to_dicts()

    for record in records:
        record["color"] = STATUS_COLOR_MAP.get(record.get("status", "active"), [120, 120, 120, 150])

    logger.debug("Built ArcLayer with {} cable arcs", len(records))
    return pdk.Layer(
        "ArcLayer",
        id="cable-arcs",
        data=records,
        get_source_position=["source_lon", "source_lat"],
        get_target_position=["target_lon", "target_lat"],
        get_source_color="color",
        get_target_color="color",
        get_width=3,
        get_height=0.25,
        pickable=True,
        auto_highlight=True,
    )


def build_datacenter_column_layer(regions_df: pl.DataFrame) -> pdk.Layer:
    """ColumnLayer: data center nodes, elevation driven by anomaly_score."""
    if len(regions_df) == 0:
        logger.warning("No region data for ColumnLayer — returning empty layer")
        return _empty_layer("ColumnLayer", "dc-columns")

    records = (
        regions_df.select(["region_id", "display_name", "provider", "lon", "lat", "anomaly_score"])
        .with_columns(
            (pl.col("anomaly_score") * 200_000 + 5_000).alias("elevation"),
            pl.col("anomaly_score")
            .map_elements(
                lambda score: [255, max(0, int(140 - score * 140)), 0, 200],
                return_dtype=pl.List(pl.Int64),
            )
            .alias("fill_color"),
        )
        .to_dicts()
    )

    logger.debug("Built ColumnLayer with {} data center nodes", len(records))
    return pdk.Layer(
        "ColumnLayer",
        id="dc-columns",
        data=records,
        get_position=["lon", "lat"],
        get_elevation="elevation",
        elevation_scale=1,
        radius=25_000,
        get_fill_color="fill_color",
        pickable=True,
        auto_highlight=True,
    )


def build_h3_risk_layer(h3_zones_df: pl.DataFrame) -> pdk.Layer:
    """H3HexagonLayer: aggregated risk density. Invalid hex ids are dropped so a
    bad cell can never render a world-covering polygon."""
    if len(h3_zones_df) == 0:
        logger.warning("No H3 zone data — returning empty layer")
        return _empty_layer("H3HexagonLayer", "h3-risk")

    raw_records = (
        h3_zones_df.select(["h3_index", "incident_count", "avg_anomaly_score", "max_risk_level"])
        .with_columns(
            pl.col("max_risk_level")
            .map_elements(
                lambda level: RISK_COLOR_MAP.get(level, [120, 120, 120, 100]),
                return_dtype=pl.List(pl.Int64),
            )
            .alias("fill_color"),
            (pl.col("incident_count") * 15_000).alias("elevation"),
        )
        .to_dicts()
    )

    # Keep only records with a valid H3 hex-string id.
    records = [r for r in raw_records if _H3_HEX_RE.match(str(r.get("h3_index", "")))]
    dropped = len(raw_records) - len(records)
    if dropped:
        logger.warning("H3 layer dropped {} record(s) with invalid h3_index", dropped)
    if not records:
        logger.warning("No valid H3 hex ids after filtering — returning empty layer")
        return _empty_layer("H3HexagonLayer", "h3-risk")

    logger.debug("Built H3HexagonLayer with {} hexagons", len(records))
    return pdk.Layer(
        "H3HexagonLayer",
        id="h3-risk",
        data=records,
        get_hexagon="h3_index",
        get_fill_color="fill_color",
        get_elevation="elevation",
        elevation_scale=1,
        extruded=True,
        pickable=True,
        opacity=0.5,
    )


def build_incident_scatter_layer(incidents_df: pl.DataFrame) -> pdk.Layer:
    """ScatterplotLayer: fault markers at exact incident coordinates."""
    if len(incidents_df) == 0:
        logger.warning("No active incidents for ScatterplotLayer — returning empty layer")
        return _empty_layer("ScatterplotLayer", "incident-markers")

    records = (
        incidents_df.select(["incident_id", "cable_id", "fault_type", "status", "zone", "lon", "lat"])
        .with_columns(
            pl.col("status")
            .map_elements(
                lambda s: STATUS_COLOR_MAP.get(s, [200, 200, 200, 180]),
                return_dtype=pl.List(pl.Int64),
            )
            .alias("color"),
            pl.col("status")
            .map_elements(lambda s: 8000 if s == "cut" else 5000, return_dtype=pl.Int64)
            .alias("radius"),
        )
        .to_dicts()
    )

    logger.debug("Built ScatterplotLayer with {} incident markers", len(records))
    return pdk.Layer(
        "ScatterplotLayer",
        id="incident-markers",
        data=records,
        get_position=["lon", "lat"],
        get_fill_color="color",
        get_radius="radius",
        radius_units="meters",
        pickable=True,
        auto_highlight=True,
        stroked=True,
        get_line_color=[255, 255, 255, 120],
        line_width_units="pixels",
        get_line_width=1,
    )


def _safe_build(builder, df: pl.DataFrame, kind: str, layer_id: str) -> pdk.Layer:
    """Run a layer builder; on any unexpected error return an empty layer so one
    bad frame can never blank the whole deck."""
    try:
        return builder(df)
    except Exception as exc:
        logger.error("Layer {} build failed (degraded to empty): {}", layer_id, exc)
        return _empty_layer(kind, layer_id)


# =============================================================================
# Deck assembly
# =============================================================================

def build_deck(
    cables_df: pl.DataFrame,
    regions_df: pl.DataFrame,
    h3_zones_df: pl.DataFrame,
    incidents_df: pl.DataFrame,
    center_lat: float = 25.0,
    center_lon: float = 35.0,
    zoom: float = 2.0,
) -> pdk.Deck:
    """Assemble the full PyDeck Deck. No external basemap URL (reliable default)."""
    view_state = pdk.ViewState(
        latitude=center_lat,
        longitude=center_lon,
        zoom=zoom,
        pitch=45,
        bearing=0,
    )

    layers = [
        _safe_build(build_h3_risk_layer, h3_zones_df, "H3HexagonLayer", "h3-risk"),
        _safe_build(build_cable_arc_layer, cables_df, "ArcLayer", "cable-arcs"),
        _safe_build(build_datacenter_column_layer, regions_df, "ColumnLayer", "dc-columns"),
        _safe_build(build_incident_scatter_layer, incidents_df, "ScatterplotLayer", "incident-markers"),
    ]

    tooltip = {
        "html": (
            "<b>{cable_name}{display_name}{cable_id}</b><br/>"
            "Status: {status}<br/>"
            "Provider: {provider}<br/>"
            "Risk: {max_risk_level}<br/>"
            "Incidents: {incident_count}<br/>"
            "Anomaly: {avg_anomaly_score}"
        ),
        "style": {"backgroundColor": "#111827", "color": "white", "fontSize": "12px"},
    }

    logger.info(
        "Built PyDeck with {} layers | center=({}, {}) zoom={}",
        len(layers),
        center_lat,
        center_lon,
        zoom,
    )

    return pdk.Deck(
        layers=layers,
        initial_view_state=view_state,
        # Intentionally NO map_style: pydeck's built-in basemap renders reliably
        # on Cloud without a token. (Dark styled map returns in Pass C.)
        tooltip=tooltip,
    )
