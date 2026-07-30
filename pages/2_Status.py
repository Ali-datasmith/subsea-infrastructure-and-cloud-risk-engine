"""
Page 2 — Status: Live 3D PyDeck geospatial risk map.
Renders ArcLayer (cables), ColumnLayer (DCs), H3HexagonLayer (risk zones),
and ScatterplotLayer (active incidents).
"""
from __future__ import annotations

import sys
from pathlib import Path

APP_ROOT = Path(__file__).resolve().parent.parent
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))

import polars as pl
import streamlit as st
from loguru import logger

from src.config import get_settings
from src.db_engine import RiskEngineStore
from src.viz_layers import build_deck


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
    show_h3 = st.checkbox("Show H3 Risk Zones", value=True)
    show_incidents = st.checkbox("Show Incident Markers", value=True)

    if st.button("🔄 Refresh Data", use_container_width=True):
        st.session_state.pop("cables_df", None)
        st.session_state.pop("regions_df", None)
        st.session_state.pop("h3_df", None)
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

if "h3_df" not in st.session_state:
    with st.spinner("Loading H3 risk zones..."):
        st.session_state["h3_df"] = store.get_h3_risk_zones()

if "incidents_df" not in st.session_state:
    with st.spinner("Loading active incidents..."):
        st.session_state["incidents_df"] = store.get_active_incidents()

cables_df: pl.DataFrame = st.session_state["cables_df"]
regions_df: pl.DataFrame = st.session_state["regions_df"]
h3_df: pl.DataFrame = st.session_state["h3_df"]
incidents_df: pl.DataFrame = st.session_state["incidents_df"]

# =============================================================================
# Apply layer visibility filters
# =============================================================================

if not show_cables:
    cables_df = pl.DataFrame(
        schema={
            "cable_id": pl.Utf8,
            "cable_name": pl.Utf8,
            "status": pl.Utf8,
            "source_lon": pl.Float64,
            "source_lat": pl.Float64,
            "target_lon": pl.Float64,
            "target_lat": pl.Float64,
        }
    )

if not show_dc:
    regions_df = pl.DataFrame(
        schema={
            "region_id": pl.Utf8,
            "display_name": pl.Utf8,
            "provider": pl.Utf8,
            "lon": pl.Float64,
            "lat": pl.Float64,
            "anomaly_score": pl.Float64,
        }
    )

if not show_h3:
    h3_df = pl.DataFrame(
        schema={
            "h3_index": pl.Utf8,
            "incident_count": pl.Int64,
            "avg_anomaly_score": pl.Float64,
            "max_risk_level": pl.Utf8,
        }
    )

if not show_incidents:
    incidents_df = pl.DataFrame(
        schema={
            "incident_id": pl.Utf8,
            "cable_id": pl.Utf8,
            "fault_type": pl.Utf8,
            "status": pl.Utf8,
            "zone": pl.Utf8,
            "lon": pl.Float64,
            "lat": pl.Float64,
        }
    )

# =============================================================================
# Render PyDeck chart
# =============================================================================

deck = build_deck(
    cables_df=cables_df,
    regions_df=regions_df,
    h3_zones_df=h3_df,
    incidents_df=incidents_df,
    center_lat=center_lat,
    center_lon=center_lon,
    zoom=zoom_level,
)

st.pydeck_chart(deck, use_container_width=True)

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

h3_cells = len(h3_df) if show_h3 else store.connection.execute(
    "SELECT COUNT(*) FROM h3_risk_zones"
).fetchone()[0]

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
        use_container_width=True,
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

