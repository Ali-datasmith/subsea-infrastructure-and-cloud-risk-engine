"""
PyDeck layer factories for the 3D geospatial risk dashboard.
All layers use explicit `id` parameters for Streamlit re-render stability.
"""
from __future__ import annotations

from typing import Optional

import polars as pl
import pydeck as pdk
from loguru import logger


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


# =============================================================================
# Layer builders
# =============================================================================


def build_cable_arc_layer(cables_df: pl.DataFrame) -> pdk.Layer:
    """
    ArcLayer: one arc per cable segment between landing points.
    Colored by live cable status (most recent incident status).
    """
    if len(cables_df) == 0:
        logger.warning("No cable data for ArcLayer — returning empty layer")
        return pdk.Layer("ArcLayer", id="cable-arcs", data=[])

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
    """
    ColumnLayer: data center nodes with elevation driven by anomaly_score.
    Color intensity scales with anomaly severity.
    """
    if len(regions_df) == 0:
        logger.warning("No region data for ColumnLayer — returning empty layer")
        return pdk.Layer("ColumnLayer", id="dc-columns", data=[])

    records = (
        regions_df.select(
            ["region_id", "display_name", "provider", "lon", "lat", "anomaly_score"]
        )
        .with_columns(
            (pl.col("anomaly_score") * 200_000 + 5_000).alias("elevation"),
            pl.col("anomaly_score").map_elements(
                lambda score: [
                    255,
                    max(0, int(140 - score * 140)),
                    0,
                    200,
                ],
                return_dtype=pl.List(pl.Int64),
            ).alias("fill_color"),
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
    """
    H3HexagonLayer: aggregated risk density across ocean zones (resolution 3).
    Fill color and elevation encode incident count and anomaly severity.
    """
    if len(h3_zones_df) == 0:
        logger.warning("No H3 zone data — returning empty layer")
        return pdk.Layer("H3HexagonLayer", id="h3-risk", data=[])

    records = (
        h3_zones_df.select(
            ["h3_index", "incident_count", "avg_anomaly_score", "max_risk_level"]
        )
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
        opacity=0.6,
    )


def build_incident_scatter_layer(incidents_df: pl.DataFrame) -> pdk.Layer:
    """
    ScatterplotLayer: pulsing fault markers at exact incident coordinates.
    Color and radius encode fault severity.
    """
    if len(incidents_df) == 0:
        logger.warning("No active incidents for ScatterplotLayer — returning empty layer")
        return pdk.Layer("ScatterplotLayer", id="incident-markers", data=[])

    records = (
        incidents_df.select(
            ["incident_id", "cable_id", "fault_type", "status", "zone", "lon", "lat"]
        )
        .with_columns(
            pl.col("status")
            .map_elements(
                lambda s: STATUS_COLOR_MAP.get(s, [200, 200, 200, 180]),
                return_dtype=pl.List(pl.Int64),
            )
            .alias("color"),
            pl.col("status")
            .map_elements(
                lambda s: 8000 if s == "cut" else 5000,
                return_dtype=pl.Int64,
            )
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
    """
    Assemble the full PyDeck Deck with all layers and a shared ViewState.
    Center defaults to Red Sea / Middle East chokepoint region.
    """
    view_state = pdk.ViewState(
        latitude=center_lat,
        longitude=center_lon,
        zoom=zoom,
        pitch=45,
        bearing=0,
    )

    layers = [
        build_h3_risk_layer(h3_zones_df),
        build_cable_arc_layer(cables_df),
        build_datacenter_column_layer(regions_df),
        build_incident_scatter_layer(incidents_df),
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
        map_style="mapbox://styles/mapbox/dark-v11",
        tooltip=tooltip,
    )
