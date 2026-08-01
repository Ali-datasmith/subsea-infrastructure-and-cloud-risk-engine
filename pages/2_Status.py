"""
Page 2 — Status: live geospatial risk map (Folium + Leaflet), risk summary,
active-incident detail, and the Pass-B external-signals panel.
"""
from __future__ import annotations

import sys
from pathlib import Path

APP_ROOT = Path(__file__).resolve().parent.parent
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))

import polars as pl
import streamlit as st
import streamlit.components.v1 as components
from loguru import logger

from src.config import get_settings
from src.db_engine import RiskEngineStore
from src.viz_layers import build_folium_map

st.set_page_config(page_title="Live Risk Map", page_icon="🗺️", layout="wide")
st.title("🗺️ Subsea Infrastructure & Cloud Risk — Live Status")


def get_store() -> RiskEngineStore:
    """Retrieve or initialize the DuckDB store."""
    if "store" not in st.session_state:
        settings = get_settings()
        store = RiskEngineStore(settings)
        store.bootstrap_schema()
        st.session_state["store"] = store
        st.session_state["settings"] = settings
    return st.session_state["store"]


store = get_store()

# =============================================================================
# Sidebar controls
# =============================================================================
with st.sidebar:
    st.header("🎛️ Map Controls")

    center_lat = st.slider("Center Latitude", -60.0, 70.0, 25.0, 1.0)
    center_lon = st.slider("Center Longitude", -180.0, 180.0, 35.0, 1.0)
    zoom_level = st.slider("Zoom Level", 1.0, 8.0, 2.0, 0.1)

    show_cables = st.checkbox("Show Cable Arcs", value=True)
    show_dc = st.checkbox("Show Data Centers", value=True)
    show_heat = st.checkbox("Show Risk Heatmap", value=True)
    show_incidents = st.checkbox("Show Incident Markers", value=True)

    if st.button("🔄 Refresh Data", use_container_width=True):
        st.session_state.pop("cables_df", None)
        st.session_state.pop("regions_df", None)
        st.session_state.pop("incidents_df", None)
        st.rerun()

# =============================================================================
# Data loading (cached in session state)
# =============================================================================
if "cables_df" not in st.session_state:
    with st.spinner("Loading cable data..."):
        st.session_state["cables_df"] = store.get_cables_with_endpoints()

if "regions_df" not in st.session_state:
    with st.spinner("Loading cloud region data..."):
        st.session_state["regions_df"] = store.get_cloud_regions_with_anomaly()

if "incidents_df" not in st.session_state:
    with st.spinner("Loading active incidents..."):
        st.session_state["incidents_df"] = store.get_active_incidents()

cables_df: pl.DataFrame = st.session_state["cables_df"]
regions_df: pl.DataFrame = st.session_state["regions_df"]
incidents_df: pl.DataFrame = st.session_state["incidents_df"]

# =============================================================================
# Render the Folium / Leaflet map (reliable dark basemap on Cloud)
# =============================================================================
map_html = build_folium_map(
    cables_df=cables_df,
    regions_df=regions_df,
    incidents_df=incidents_df,
    center_lat=center_lat,
    center_lon=center_lon,
    zoom=int(round(zoom_level)),
    show_cables=show_cables,
    show_dc=show_dc,
    show_heat=show_heat,
    show_incidents=show_incidents,
)
components.html(map_html, height=720, scrolling=False)
st.caption(
    "Basemap: Folium + Leaflet over Carto Dark raster tiles "
    "(token-free; renders reliably inside Streamlit Cloud)."
)

# =============================================================================
# Summary metrics below map
# =============================================================================
st.divider()
st.subheader("📈 Risk Summary")

col1, col2, col3, col4, col5 = st.columns(5)

active_incidents = store.connection.execute(
    "SELECT COUNT(*) FROM cable_incidents WHERE status IN ('cut', 'degraded', 'under_repair')"
).fetchone()[0]
cut_count = store.connection.execute(
    "SELECT COUNT(*) FROM cable_incidents WHERE status = 'cut'"
).fetchone()[0]
zones_affected = store.connection.execute(
    "SELECT COUNT(DISTINCT zone) FROM cable_incidents WHERE status IN ('cut', 'degraded', 'under_repair')"
).fetchone()[0]
h3_cells = store.connection.execute("SELECT COUNT(*) FROM h3_risk_zones").fetchone()[0]
avg_repair = store.connection.execute(
    "SELECT COALESCE(AVG(estimated_repair_days), 0) FROM cable_incidents WHERE status IN ('cut', 'under_repair')"
).fetchone()[0]

with col1:
    st.metric("Active Faults", active_incidents)
with col2:
    st.metric("Full Cuts", cut_count, delta_color="inverse")
with col3:
    st.metric("Zones Affected", zones_affected)
with col4:
    st.metric("H3 Risk Cells", h3_cells)
with col5:
    st.metric("Avg Repair ETA (days)", f"{avg_repair:.0f}")

# =============================================================================
# Active incidents table
# =============================================================================
st.divider()
st.subheader("🔴 Active Incidents Detail")

if len(incidents_df) > 0:
    display_df = store.get_active_incidents()
    st.dataframe(
        display_df,
        width="stretch",
        hide_index=True,
        column_config={
            "incident_id": st.column_config.TextColumn("ID", width="small"),
            "cable_id": st.column_config.TextColumn("Cable"),
            "fault_type": st.column_config.TextColumn("Fault Type"),
            "status": st.column_config.TextColumn("Status"),
            "zone": st.column_config.TextColumn("Zone"),
            "lon": st.column_config.NumberColumn("Lon", format="%.2f"),
            "lat": st.column_config.NumberColumn("Lat", format="%.2f"),
            "detected_at": st.column_config.DatetimeColumn("Detected"),
            "estimated_repair_days": st.column_config.NumberColumn("Repair ETA (d)"),
        },
    )
else:
    st.success("✅ No active cable incidents. All systems nominal.")

# =============================================================================
# External free-tier signals (Pass B)
# =============================================================================
st.divider()
with st.expander("🛰️ External Signals — weather · news · composite risk", expanded=True):
    scores_df = store.get_cable_risk_scores()
    weather_df = store.get_latest_weather()
    news_df = store.get_latest_news(limit=10)

    st.markdown("**Composite cable risk** (incident 50 % · weather 30 % · news 40 %, clipped 0–1)")
    if len(scores_df) > 0:
        st.dataframe(scores_df, width="stretch", hide_index=True)
    else:
        st.info("No scores yet — inject demo data or pull live feeds on the Input page.")

    sc1, sc2 = st.columns(2)
    with sc1:
        st.markdown("**Marine weather by zone**")
        if len(weather_df) > 0:
            st.dataframe(weather_df, width="stretch", hide_index=True)
        else:
            st.caption("No weather samples.")
    with sc2:
        st.markdown("**Latest risk news**")
        if len(news_df) > 0:
            st.dataframe(news_df, width="stretch", hide_index=True)
        else:
            st.caption("No news hits.")

logger.info(
    "Status page rendered: {} cables, {} regions, {} incidents",
    len(cables_df),
    len(regions_df),
    len(incidents_df),
)

