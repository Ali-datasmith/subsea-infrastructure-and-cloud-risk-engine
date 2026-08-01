"""
Geospatial risk map — rendered with Folium + Leaflet (NOT pydeck).

Why Leaflet instead of pydeck here:
  Streamlit Cloud renders st.pydeck_chart inside a sandboxed iframe where
  deck.gl's hosted/Mapbox vector basemap styles fail to load their sprites /
  glyphs / sources. The failure mode is a solid colour wash that changes hue
  on zoom/scroll (cyan / magenta / red / yellow) — exactly the bug we hit.
  Leaflet draws the basemap as plain PNG tile <img> tags (no WebGL, no
  style.json), so a real dark world map renders reliably and can never wash
  out. We embed the resulting HTML via streamlit.components.v1.html.

Layers (all native Leaflet, on Carto Dark raster tiles, free / no key):
  - cable routes   -> curved PolyLine coloured by live status
  - active faults  -> CircleMarker with hover tooltips
  - cloud regions  -> CircleMarker sized by anomaly score
  - risk density   -> folium.plugins.HeatMap over incident points

Every layer addition is individually guarded so one bad row can never blank
the map. folium is imported lazily so a missing install degrades to an HTML
error card instead of a red traceback.
"""
from __future__ import annotations

import math
from typing import Optional

import polars as pl
from loguru import logger

# =============================================================================
# Colour maps (RGB ints -> hex for Leaflet)
# =============================================================================
STATUS_RGB: dict[str, list[int]] = {
    "active": [46, 204, 113],
    "degraded": [241, 196, 15],
    "cut": [231, 76, 60],
    "under_repair": [52, 152, 219],
    "planned": [149, 165, 166],
}
SEVERITY_WEIGHT: dict[str, float] = {
    "cut": 1.0,
    "under_repair": 0.8,
    "degraded": 0.5,
    "active": 0.2,
    "planned": 0.1,
}
HEAT_GRADIENT: dict[float, str] = {
    0.2: "#1a9850",
    0.4: "#fee08b",
    0.6: "#fc8d59",
    0.8: "#d73027",
    1.0: "#a50026",
}


def _hex(rgb: list[int]) -> str:
    return "#{:02x}{:02x}{:02x}".format(rgb[0], rgb[1], rgb[2])


def _status_hex(status: Optional[str]) -> str:
    return _hex(STATUS_RGB.get(status or "active", [120, 120, 120]))


def _curve(lon1: float, lat1: float, lon2: float, lat2: float,
           bow: float = 0.18, steps: int = 48) -> list[list[float]]:
    """Quadratic Bezier that bows the segment northward so routes read as
    elegant arcs on a 2D Web-Mercator map (the pydeck ArcLayer aesthetic)."""
    mid_lon = (lon1 + lon2) / 2.0
    mid_lat = (lat1 + lat2) / 2.0
    dist = math.hypot(lon2 - lon1, lat2 - lat1)
    cx = mid_lon
    cy = mid_lat + dist * bow  # northward bow, orientation-independent
    pts: list[list[float]] = []
    for i in range(steps + 1):
        t = i / steps
        x = (1 - t) ** 2 * lon1 + 2 * (1 - t) * t * cx + t ** 2 * lon2
        y = (1 - t) ** 2 * lat1 + 2 * (1 - t) * t * cy + t ** 2 * lat2
        pts.append([y, x])  # Leaflet wants [lat, lon]
    return pts


# =============================================================================
# Map builder
# =============================================================================
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
    """Return a self-contained HTML string with a dark Leaflet risk map."""
    try:
        import folium
        from folium import plugins
    except Exception as exc:  # pragma: no cover - install guard
        logger.error("folium not available: {}", exc)
        return (
            "<div style='font-family:sans-serif;color:#ffd1d1;background:#1a0d12;"
            "padding:24px;border-radius:12px'>Map unavailable: the <code>folium</code> "
            "package is not installed. Add <code>folium&gt;=0.16</code> to "
            "requirements.txt and redeploy.</div>"
        )

    zoom = max(1, int(zoom))
    m = folium.Map(
        location=[center_lat, center_lon],
        zoom_start=zoom,
        tiles=None,  # we add the dark raster layer explicitly below
        prefer_canvas=True,
        control_scale=False,
        zoom_control=True,
    )

    # Carto Dark raster tiles — plain PNG images, reliable in any iframe.
    folium.TileLayer(
        tiles="https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}.png",
        attr="&copy; OpenStreetMap contributors &copy; CARTO",
        subdomains="abcd",
        name="Carto Dark",
        max_zoom=19,
    ).add_to(m)

    # --- Risk heat (density of active incidents) ----------------------------
    if show_heat and len(incidents_df) > 0:
        try:
            heat_pts: list[list[float]] = []
            for row in incidents_df.to_dicts():
                w = SEVERITY_WEIGHT.get(str(row.get("status")), 0.3)
                heat_pts.append([float(row["lat"]), float(row["lon"]), w])
            if heat_pts:
                fg_heat = folium.FeatureGroup(name="Risk Heat", show=True)
                plugins.HeatMap(
                    heat_pts,
                    radius=20,
                    blur=14,
                    max_zoom=7,
                    min_opacity=0.35,
                    gradient=HEAT_GRADIENT,
                ).add_to(fg_heat)
                fg_heat.add_to(m)
                logger.debug("HeatMap built with {} points", len(heat_pts))
        except Exception as exc:
            logger.warning("HeatMap layer skipped: {}", exc)

    # --- Cable routes as bowed arcs -----------------------------------------
    if show_cables and len(cables_df) > 0:
        try:
            fg_cables = folium.FeatureGroup(name="Cable Routes", show=True)
            for row in cables_df.to_dicts():
                try:
                    pts = _curve(
                        float(row["source_lon"]), float(row["source_lat"]),
                        float(row["target_lon"]), float(row["target_lat"]),
                    )
                    folium.PolyLine(
                        pts,
                        color=_status_hex(row.get("status")),
                        weight=3,
                        opacity=0.9,
                        tooltip=f"{row.get('cable_name', row.get('cable_id', 'cable'))} — {row.get('status', 'active')}",
                    ).add_to(fg_cables)
                except Exception as exc:
                    logger.debug("Cable arc skipped: {}", exc)
            fg_cables.add_to(m)
        except Exception as exc:
            logger.warning("Cable layer skipped: {}", exc)

    # --- Cloud regions (DC nodes) -------------------------------------------
    if show_dc and len(regions_df) > 0:
        try:
            fg_dc = folium.FeatureGroup(name="Cloud Regions", show=True)
            for row in regions_df.to_dicts():
                try:
                    anomaly = float(row.get("anomaly_score") or 0.0)
                    folium.CircleMarker(
                        [float(row["lat"]), float(row["lon"])],
                        radius=6 + anomaly * 12,
                        color="#ff9900",
                        weight=1.5,
                        fill=True,
                        fill_color="#ffb347",
                        fill_opacity=0.55,
                        tooltip=(
                            f"{row.get('display_name', row.get('region_id', 'region'))} "
                            f"[{row.get('provider', '')}] anomaly={anomaly:.2f}"
                        ),
                    ).add_to(fg_dc)
                except Exception as exc:
                    logger.debug("DC marker skipped: {}", exc)
            fg_dc.add_to(m)
        except Exception as exc:
            logger.warning("Cloud region layer skipped: {}", exc)

    # --- Active fault markers -----------------------------------------------
    if show_incidents and len(incidents_df) > 0:
        try:
            fg_inc = folium.FeatureGroup(name="Active Faults", show=True)
            for row in incidents_df.to_dicts():
                try:
                    status = str(row.get("status", "active"))
                    folium.CircleMarker(
                        [float(row["lat"]), float(row["lon"])],
                        radius=9 if status == "cut" else 6,
                        color="#ffffff",
                        weight=1.5,
                        fill=True,
                        fill_color=_status_hex(status),
                        fill_opacity=0.95,
                        tooltip=(
                            f"{row.get('cable_id', '?')} · {status} · "
                            f"{row.get('fault_type', '')} · {row.get('zone', '')}"
                        ),
                    ).add_to(fg_inc)
                except Exception as exc:
                    logger.debug("Incident marker skipped: {}", exc)
            fg_inc.add_to(m)
        except Exception as exc:
            logger.warning("Incident layer skipped: {}", exc)

    # In-map toggle control + dark loading background
    try:
        folium.LayerControl(collapsed=True, position="topright").add_to(m)
    except Exception as exc:
        logger.debug("LayerControl skipped: {}", exc)

    m.get_root().header.add_child(
        folium.Element(
            "<style>"
            "html,body{margin:0;padding:0;height:100%;background:#0b1020;}"
            ".folium-map{width:100%!important;height:100%!important;}"
            ".leaflet-container{background:#0b1020!important;}"
            "</style>"
        )
    )
    m.get_root().width = "100%"
    m.get_root().height = "100%"

    logger.info(
        "Folium map built | center=({}, {}) zoom={} | cables={} dc={} incidents={}",
        center_lat, center_lon, zoom,
        len(cables_df), len(regions_df), len(incidents_df),
    )
    return m.get_root().render()
