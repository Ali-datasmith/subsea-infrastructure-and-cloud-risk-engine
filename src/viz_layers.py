"""
Geospatial risk map — Folium + Leaflet, skinned to "Deep Ocean & Electric Cyan".

Why Folium (not pydeck): Streamlit Cloud renders pydeck's hosted/Mapbox vector
basemap styles inside a sandboxed iframe where their sprites/glyphs fail to load,
producing a solid colour that shifts hue on zoom (the old cyan/magenta wash).
Leaflet draws the basemap as plain PNG tiles -> a real dark world map that can
never wash out. Embedded via streamlit.components.v1.html.

Neon styling per the theme spec:
  - basemap  : Carto dark matter raster tiles (the proven, token-free source;
               visually identical to the spec's "CartoDB dark_matter"), blended
               into the navy field via a #050c1a container background.
  - cables   : glowing neon paths (translucent halo + bright 2.5px core);
               healthy = electric cyan #00f2fe; faults shift to neon amber/red/blue.
  - faults   : halo + bright core CircleMarkers (cut gets an extra radar halo).
  - cloud DCs: vivid-purple #bd00ff markers, radius scaled by anomaly_score.
  - density  : HeatMap on a cyan->blue->purple->red gradient.

Every layer addition is individually guarded; folium is imported lazily so a
missing install degrades to an HTML card, never a traceback.
"""
from __future__ import annotations

import math
from typing import Optional

import polars as pl
from loguru import logger

# Neon status palette (healthy == spec's electric cyan; faults stay in-family)
NEON_STATUS: dict[str, str] = {
    "active": "#00f2fe",
    "degraded": "#ffbe0b",
    "cut": "#ff2e63",
    "under_repair": "#4facfe",
    "planned": "#5b6b86",
}
SEVERITY_WEIGHT: dict[str, float] = {
    "cut": 1.0, "under_repair": 0.8, "degraded": 0.5, "active": 0.2, "planned": 0.1,
}
DC_COLOR = "#bd00ff"          # secondary accent -> cloud data centers
HEAT_GRADIENT: dict[float, str] = {
    0.2: "#00f2fe", 0.4: "#4facfe", 0.6: "#bd00ff", 0.8: "#ff2e63", 1.0: "#ff0044",
}


def _status_color(status: Optional[str]) -> str:
    return NEON_STATUS.get(status or "active", "#00f2fe")


def _curve(lon1: float, lat1: float, lon2: float, lat2: float,
           bow: float = 0.18, steps: int = 48) -> list[list[float]]:
    """Quadratic Bezier bowing the segment northward (arc aesthetic on 2D map)."""
    mid_lon = (lon1 + lon2) / 2.0
    mid_lat = (lat1 + lat2) / 2.0
    dist = math.hypot(lon2 - lon1, lat2 - lat1)
    cx, cy = mid_lon, mid_lat + dist * bow
    pts: list[list[float]] = []
    for i in range(steps + 1):
        t = i / steps
        x = (1 - t) ** 2 * lon1 + 2 * (1 - t) * t * cx + t ** 2 * lon2
        y = (1 - t) ** 2 * lat1 + 2 * (1 - t) * t * cy + t ** 2 * lat2
        pts.append([y, x])  # Leaflet wants [lat, lon]
    return pts


def build_folium_map(
    cables_df: pl.DataFrame,
    regions_df: pl.DataFrame,
    incidents_df: pl.DataFrame,
    center_lat: float = 25.0,
    center_lon: float = 35.0,
    zoom: int = 2,
    show_cables: bool = True,
    show_dc: bool = True,
    show_heat: bool = True,
    show_incidents: bool = True,
) -> str:
    """Return a self-contained dark, neon Leaflet risk map as HTML."""
    try:
        import folium
        from folium import plugins
    except Exception as exc:  # install guard
        logger.error("folium not available: {}", exc)
        return (
            "<div style='font-family:monospace;color:#00f2fe;background:#050c1a;"
            "padding:24px;border:1px solid rgba(0,242,254,.25);border-radius:12px'>"
            "Map unavailable: add <code>folium&gt;=0.16</code> to requirements.txt.</div>"
        )

    zoom = max(1, int(zoom))
    m = folium.Map(
        location=[center_lat, center_lon], zoom_start=zoom, tiles=None,
        prefer_canvas=True, control_scale=False, zoom_control=True,
    )
    # Carto dark matter raster tiles — plain PNG images, reliable in any iframe.
    folium.TileLayer(
        tiles="https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}.png",
        attr="&copy; OpenStreetMap contributors &copy; CARTO",
        subdomains="abcd", name="Carto Dark", max_zoom=19,
    ).add_to(m)

    # --- risk heat over active incidents -----------------------------------
    if show_heat and len(incidents_df) > 0:
        try:
            heat_pts = [
                [float(r["lat"]), float(r["lon"]), SEVERITY_WEIGHT.get(str(r.get("status")), 0.3)]
                for r in incidents_df.to_dicts()
            ]
            if heat_pts:
                fg = folium.FeatureGroup(name="Risk Heat", show=True)
                plugins.HeatMap(
                    heat_pts, radius=22, blur=15, max_zoom=7, min_opacity=0.35,
                    gradient=HEAT_GRADIENT,
                ).add_to(fg)
                fg.add_to(m)
        except Exception as exc:
            logger.warning("HeatMap skipped: {}", exc)

    # --- cable routes as glowing neon arcs (halo + core) -------------------
    if show_cables and len(cables_df) > 0:
        try:
            fg = folium.FeatureGroup(name="Cable Routes", show=True)
            for row in cables_df.to_dicts():
                try:
                    pts = _curve(
                        float(row["source_lon"]), float(row["source_lat"]),
                        float(row["target_lon"]), float(row["target_lat"]),
                    )
                    color = _status_color(row.get("status"))
                    tip = f"{row.get('cable_name', row.get('cable_id', 'cable'))} — {row.get('status', 'active')}"
                    folium.PolyLine(pts, color=color, weight=8, opacity=0.22, tooltip=tip).add_to(fg)
                    folium.PolyLine(pts, color=color, weight=2.5, opacity=0.95, tooltip=tip).add_to(fg)
                except Exception as exc:
                    logger.debug("Cable arc skipped: {}", exc)
            fg.add_to(m)
        except Exception as exc:
            logger.warning("Cable layer skipped: {}", exc)

    # --- cloud regions (DC nodes, vivid purple) ----------------------------
    if show_dc and len(regions_df) > 0:
        try:
            fg = folium.FeatureGroup(name="Cloud Regions", show=True)
            for row in regions_df.to_dicts():
                try:
                    anomaly = float(row.get("anomaly_score") or 0.0)
                    r = 6 + anomaly * 12
                    tip = (f"{row.get('display_name', row.get('region_id', 'region'))} "
                           f"[{row.get('provider', '')}] anomaly={anomaly:.2f}")
                    folium.CircleMarker(
                        [float(row["lat"]), float(row["lon"])], radius=r + 6,
                        color=DC_COLOR, weight=0, fill=True, fill_color=DC_COLOR,
                        fill_opacity=0.18, tooltip=tip,
                    ).add_to(fg)
                    folium.CircleMarker(
                        [float(row["lat"]), float(row["lon"])], radius=r,
                        color="#ffffff", weight=1.2, fill=True, fill_color=DC_COLOR,
                        fill_opacity=0.85, tooltip=tip,
                    ).add_to(fg)
                except Exception as exc:
                    logger.debug("DC marker skipped: {}", exc)
            fg.add_to(m)
        except Exception as exc:
            logger.warning("Cloud region layer skipped: {}", exc)

    # --- active fault markers (halo + core; cut gets a radar halo) ---------
    if show_incidents and len(incidents_df) > 0:
        try:
            fg = folium.FeatureGroup(name="Active Faults", show=True)
            for row in incidents_df.to_dicts():
                try:
                    status = str(row.get("status", "active"))
                    color = _status_color(status)
                    core_r = 9 if status == "cut" else 6
                    tip = (f"{row.get('cable_id', '?')} · {status} · "
                           f"{row.get('fault_type', '')} · {row.get('zone', '')}")
                    if status == "cut":
                        folium.CircleMarker(
                            [float(row["lat"]), float(row["lon"])], radius=22,
                            color=color, weight=1, fill=True, fill_color=color,
                            fill_opacity=0.12, tooltip=tip,
                        ).add_to(fg)
                    folium.CircleMarker(
                        [float(row["lat"]), float(row["lon"])], radius=core_r + 5,
                        color=color, weight=0, fill=True, fill_color=color,
                        fill_opacity=0.25, tooltip=tip,
                    ).add_to(fg)
                    folium.CircleMarker(
                        [float(row["lat"]), float(row["lon"])], radius=core_r,
                        color="#ffffff", weight=1.5, fill=True, fill_color=color,
                        fill_opacity=0.95, tooltip=tip,
                    ).add_to(fg)
                except Exception as exc:
                    logger.debug("Incident marker skipped: {}", exc)
            fg.add_to(m)
        except Exception as exc:
            logger.warning("Incident layer skipped: {}", exc)

    try:
        folium.LayerControl(collapsed=True, position="topright").add_to(m)
    except Exception as exc:
        logger.debug("LayerControl skipped: {}", exc)

    m.get_root().header.add_child(
        folium.Element(
            "<style>html,body{margin:0;height:100%;background:#050c1a;}"
            ".folium-map{width:100%!important;height:100%!important;}"
            ".leaflet-container{background:#050c1a!important;}"
            ".leaflet-control-zoom a{background:#0a192f!important;color:#00f2fe!"
            "important;border-color:rgba(0,242,254,.3)!important;}"
            ".leaflet-control-layers{background:rgba(10,25,47,.85)!important;"
            "color:#e6f1ff!important;border:1px solid rgba(0,242,254,.25)!important;}"
            "</style>"
        )
    )
    m.get_root().width = "100%"
    m.get_root().height = "100%"

    logger.info(
        "Folium neon map built | center=({}, {}) zoom={} | cables={} dc={} incidents={}",
        center_lat, center_lon, zoom, len(cables_df), len(regions_df), len(incidents_df),
    )
    return m.get_root().render()
