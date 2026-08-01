"""
Page 2 — Status: live geospatial risk map (Folium + Leaflet, neon skin),
risk summary, active-incident detail, and the Pass-B external-signals panel.
Pass C: glassmorphic theme + living header; Folium render path preserved.
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
from src.theme import hero_html, inject_theme, led_strip_html, render_alert_chime_control, ticker_html

st.set_page_config(page_title="Live Risk Map", page_icon="🗺️", layout="wide")
inject_theme()
render_alert_chime_control()


def get_store() -> RiskEngineStore:
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
        for k in ("cables_df", "regions_df", "incidents_df"):
            st.session_state.pop(k, None)
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
# Living header (ticker reflects live faults)
# =============================================================================
ticker_items = [f"{r['cable_id']}={r['status']}" for r in incidents_df.to_dicts()] if len(incidents_df) > 0 else []
st.markdown(ticker_html(ticker_items), unsafe_allow_html=True)
st.markdown(hero_html("🗺️ Subsea Infrastructure & Cloud Risk — Live Status", "Folium + Leaflet · Carto dark matter · neon fiber vectors · risk heat"), unsafe_allow_html=True)

n_crit = store.connection.execute("SELECT COUNT(*) FROM cable_incidents WHERE status='cut'").fetchone()[0]
st.markdown(led_strip_html([
    ("Map", "ok"),
    ("Cables", "ok" if len(cables_df) > 0 else "off"),
    ("Faults", "crit" if n_crit > 0 else ("warn" if len(incidents_df) > 0 else "ok")),
    ("Heat", "ok" if show_heat else "off"),
]), unsafe_allow_html=True)

# =============================================================================
# Render the neon Folium / Leaflet map
# =============================================================================
map_html = build_folium_map(
    cables_df=cables_df, regions_df=regions_df, incidents_df=incidents_df,
    center_lat=center_lat, center_lon=center_lon, zoom=int(round(zoom_level)),
    show_cables=show_cables, show_dc=show_dc, show_heat=show_heat, show_incidents=show_incidents,
)
components.html(map_html, height=720, scrolling=False)
st.caption("Basemap: Folium + Leaflet · Carto dark matter · token-free · renders reliably inside Streamlit Cloud.")

# =============================================================================
# Risk summary
# =============================================================================
st.divider()
st.subheader("📈 Risk Summary")
col1, col2, col3, col4, col5 = st.columns(5)
active_incidents = store.connection.execute("SELECT COUNT(*) FROM cable_incidents WHERE status IN ('cut','degraded','under_repair')").fetchone()[0]
cut_count = store.connection.execute("SELECT COUNT(*) FROM cable_incidents WHERE status='cut'").fetchone()[0]
zones_affected = store.connection.execute("SELECT COUNT(DISTINCT zone) FROM cable_incidents WHERE status IN ('cut','degraded','under_repair')").fetchone()[0]
h3_cells = store.connection.execute("SELECT COUNT(*) FROM h3_risk_zones").fetchone()[0]
avg_repair = store.connection.execute("SELECT COALESCE(AVG(estimated_repair_days),0) FROM cable_incidents WHERE status IN ('cut','under_repair')").fetchone()[0]
with col1: st.metric("Active Faults", active_incidents)
with col2: st.metric("Full Cuts", cut_count, delta_color="inverse")
with col3: st.metric("Zones Affected", zones_affected)
with col4: st.metric("H3 Risk Cells", h3_cells)
with col5: st.metric("Avg Repair ETA (days)", f"{avg_repair:.0f}")

# =============================================================================
# Active incidents table
# =============================================================================
st.divider()
st.subheader("🔴 Active Incidents Detail")
if len(incidents_df) > 0:
    st.dataframe(
        store.get_active_incidents(), width="stretch", hide_index=True,
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
# External free-tier signals (Pass B) — news lives here as a panel
# =============================================================================
st.divider()
with st.expander("🛰️ External Signals — weather · news · composite risk", expanded=True):
    scores_df = store.get_cable_risk_scores()
    weather_df = store.get_latest_weather()
    news_df = store.get_latest_news(limit=10)
    st.markdown("**Composite cable risk** (incident 50% · weather 30% · news 40%, clipped 0–1)")
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

logger.info("Status page rendered: {} cables, {} regions, {} incidents", len(cables_df), len(regions_df), len(incidents_df))

