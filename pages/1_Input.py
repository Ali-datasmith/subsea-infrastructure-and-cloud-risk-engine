"""
Page 1 — Input: feed configuration, manual ingestion triggers, quarantine viewer.
Pass C: glassmorphic theme + living header; all ingestion logic intact.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

APP_ROOT = Path(__file__).resolve().parent.parent
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))

import streamlit as st
from loguru import logger

from src.config import EngineSettings, get_settings
from src.data_engine import (
    incidents_to_lazyframe,
    latency_to_lazyframe,
    quarantine_payload,
    validate_incidents,
    validate_latency_metrics,
)
from src.db_engine import RiskEngineStore
from src.ingestion import CableFaultFeedClient, CloudProbeClient, run_ingestion_cycle
from src.schemas import CableIncidentPayload, CloudLatencyMetric
from src.free_feeds import OpenMeteoClient, RssNewsClient, make_synthetic_news, make_synthetic_weather
from src.theme import hero_html, inject_theme, led_strip_html, render_alert_chime_control, ticker_html

st.set_page_config(page_title="Input & Ingestion", page_icon="📥", layout="wide")
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


def get_settings_from_state() -> EngineSettings:
    if "settings" not in st.session_state:
        st.session_state["settings"] = get_settings()
    return st.session_state["settings"]


settings = get_settings_from_state()
store = get_store()

st.markdown(ticker_html(["INGESTION CONTROL", "PANDERA GATES ARMED", "QUARANTINE MONITORED"]), unsafe_allow_html=True)
st.markdown(hero_html("📥 Feed Configuration & Ingestion", "Resilient async ingest · Pydantic edge validation · keyless live feeds"), unsafe_allow_html=True)
st.markdown(led_strip_html([
    ("Store", "ok"),
    ("Gemini", "ok" if (os.environ.get("GOOGLE_API_KEY") or os.environ.get("GEMINI_API_KEY") or settings.gemini_api_key) else "warn"),
    ("Open‑Meteo", "ok"),
    ("News RSS", "ok"),
    ("Cable Feed", "warn"),
]), unsafe_allow_html=True)

# =============================================================================
# Feed Configuration
# =============================================================================
st.header("⚙️ Feed Configuration")
col1, col2 = st.columns(2)
with col1:
    st.subheader("Cable Fault Feed")
    st.text_input("Cable Fault API Base URL", value=settings.cable_fault_feed_url, key="cable_url_input")
    st.caption(f"Current: `{settings.cable_fault_feed_url}`")
with col2:
    st.subheader("Cloud Status Probes")
    st.text_input("AWS Health URL", value=settings.cloud_status_aws_url, key="aws_url")
    st.text_input("Azure Status URL", value=settings.cloud_status_azure_url, key="azure_url")
    st.text_input("GCP Incidents URL", value=settings.cloud_status_gcp_url, key="gcp_url")

st.divider()

# =============================================================================
# Manual Ingestion Triggers
# =============================================================================
st.header("🚀 Manual Ingestion Triggers")
col_ingest, col_demo = st.columns(2)

with col_ingest:
    st.subheader("Live Feed Ingestion")
    st.markdown("Trigger async ingestion from configured feed endpoints.")
    if st.button("▶️ Run Full Ingestion Cycle", type="primary", use_container_width=True):
        with st.spinner("Running ingestion cycle..."):
            try:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                incidents, metrics = loop.run_until_complete(run_ingestion_cycle(settings))
                loop.close()
                if incidents:
                    lf = incidents_to_lazyframe(incidents)
                    validated_lf = validate_incidents(lf)
                    count = store.upsert_incidents(incidents)
                    st.success(f"✅ Ingested {count} cable incidents")
                else:
                    st.info("ℹ️ No new cable incidents from feed")
                if metrics:
                    mlf = latency_to_lazyframe(metrics)
                    validated_mlf = validate_latency_metrics(mlf)
                    m_count = store.upsert_latency_metrics(metrics)
                    st.success(f"✅ Ingested {m_count} latency metrics")
                else:
                    st.info("ℹ️ No new latency metrics from probes")
                store.refresh_h3_risk_zones()
                logger.info("Manual ingestion cycle completed successfully")
            except Exception as exc:
                st.error(f"❌ Ingestion failed: {exc}")
                logger.exception("Manual ingestion cycle failed")

with col_demo:
    st.subheader("Demo Data Injection")
    st.markdown("Inject synthetic incident data for testing/development.")
    if st.button("💉 Inject Demo Incidents", use_container_width=True):
        demo_incidents = [
            CableIncidentPayload(cable_id="aae-1", cable_name="AAE-1", fault_type="suspected_sabotage", status="cut", zone="red_sea_bab_el_mandeb", fault_location={"lat": 12.6, "lon": 43.5}, detected_at=datetime.now(timezone.utc), reported_by="demo_injector", affected_segment_km=45.0, estimated_repair_days=21, vessel_correlations=[{"mmsi": "412345678", "vessel_name": "MV Shadow Runner", "flag_state": "UNKNOWN", "distance_to_fault_km": 2.3, "is_flagged_shadow_fleet": True}], raw_source_payload={"source": "demo", "injected": True}),
            CableIncidentPayload(cable_id="c-lion1", cable_name="C-Lion1", fault_type="anchor_drag", status="under_repair", zone="baltic_sea", fault_location={"lat": 58.5, "lon": 20.0}, detected_at=datetime.now(timezone.utc), reported_by="demo_injector", affected_segment_km=12.0, repair_vessel_assigned="CS Responder", estimated_repair_days=14, vessel_correlations=[{"mmsi": "273456789", "vessel_name": "MV Baltic Ghost", "flag_state": "CM", "distance_to_fault_km": 0.8, "is_flagged_shadow_fleet": True}], raw_source_payload={"source": "demo", "injected": True}),
            CableIncidentPayload(cable_id="topaz", cable_name="Topaz", fault_type="seismic_activity", status="degraded", zone="taiwan_luzon_strait", fault_location={"lat": 22.0, "lon": 121.5}, detected_at=datetime.now(timezone.utc), reported_by="demo_injector", affected_segment_km=8.0, estimated_repair_days=28, raw_source_payload={"source": "demo", "injected": True}),
            CableIncidentPayload(cable_id="seacom", cable_name="Seacom", fault_type="fishing_trawler", status="degraded", zone="red_sea_bab_el_mandeb", fault_location={"lat": 14.5, "lon": 42.0}, detected_at=datetime.now(timezone.utc), reported_by="demo_injector", affected_segment_km=5.0, estimated_repair_days=18, raw_source_payload={"source": "demo", "injected": True}),
            CableIncidentPayload(cable_id="equiano", cable_name="Equiano", fault_type="equipment_failure", status="degraded", zone="west_africa_coast", fault_location={"lat": 6.5, "lon": 3.4}, detected_at=datetime.now(timezone.utc), reported_by="demo_injector", affected_segment_km=2.0, estimated_repair_days=10, raw_source_payload={"source": "demo", "injected": True}),
        ]
        try:
            lf = incidents_to_lazyframe(demo_incidents)
            validated_lf = validate_incidents(lf)
            count = store.upsert_incidents(demo_incidents)
            store.refresh_h3_risk_zones()
            demo_zones = ["red_sea_bab_el_mandeb", "baltic_sea", "taiwan_luzon_strait", "west_africa_coast"]
            w_signals = [make_synthetic_weather(z) for z in demo_zones]
            n_signals = [n for z in demo_zones for n in make_synthetic_news(z)]
            store.upsert_weather(w_signals)
            store.upsert_news(n_signals)
            scored = store.refresh_cable_risk_scores()
            st.success(f"✅ Injected {count} incidents + {len(w_signals)} weather + {len(n_signals)} news signals; scored {scored} cables")
            st.session_state.pop("cables_df", None)
            st.session_state.pop("incidents_df", None)
            logger.info("Demo inject complete: incidents={} weather={} news={} scores={}", count, len(w_signals), len(n_signals), scored)
        except Exception as exc:
            st.error(f"❌ Demo injection failed: {exc}")
            logger.exception("Demo injection failed")

st.divider()

# =============================================================================
# Live Free Feeds (keyless)
# =============================================================================
st.header("🌐 Live Free Feeds (no API key)")
st.markdown("Pulls **real, free, keyless** data: marine weather from Open‑Meteo and a conflict/anchor/sabotage keyword watch from Google News RSS. Failures degrade gracefully.")
col_w, col_n = st.columns(2)
with col_w:
    if st.button("🌦️ Pull Live Weather (Open‑Meteo)", use_container_width=True):
        with st.spinner("Fetching marine weather per corridor…"):
            try:
                loop = asyncio.new_event_loop(); asyncio.set_event_loop(loop)
                w_sigs = loop.run_until_complete(OpenMeteoClient(settings).fetch_all_zones()); loop.close()
                w_count = store.upsert_weather(w_sigs); store.refresh_cable_risk_scores()
                st.success(f"✅ Stored {w_count} live weather samples")
            except Exception as exc:
                st.error(f"❌ Weather pull failed: {exc}"); logger.exception("Live weather pull failed")
with col_n:
    if st.button("📰 Pull Live News (Google RSS)", use_container_width=True):
        with st.spinner("Scanning news for cable-risk keywords…"):
            try:
                loop = asyncio.new_event_loop(); asyncio.set_event_loop(loop)
                n_sigs = loop.run_until_complete(RssNewsClient(settings).fetch_all()); loop.close()
                n_count = store.upsert_news(n_sigs); store.refresh_cable_risk_scores()
                st.success(f"✅ Stored {n_count} live news hits")
            except Exception as exc:
                st.error(f"❌ News pull failed: {exc}"); logger.exception("Live news pull failed")

st.divider()

# =============================================================================
# Quarantine Viewer
# =============================================================================
st.header("🚫 Quarantine Viewer")
quarantine_dir = settings.quarantine_dir
quarantine_files = sorted(quarantine_dir.glob("*.json"), reverse=True) if quarantine_dir.exists() else []
st.markdown(f"**{len(quarantine_files)}** quarantined payload(s) on disk.")
if quarantine_files:
    selected_file = st.selectbox("Select quarantined payload", options=[f.name for f in quarantine_files])
    if selected_file:
        st.json(json.loads((quarantine_dir / selected_file).read_text(encoding="utf-8")))
    if st.button("🗑️ Clear All Quarantined Files"):
        for f in quarantine_files:
            f.unlink()
        st.success("Quarantine directory cleared")
        logger.info("Quarantine directory cleared: {} files removed", len(quarantine_files))
else:
    st.info("No quarantined payloads. All ingestion data passed validation. ✅")

st.divider()

# =============================================================================
# Pipeline Observability
# =============================================================================
st.header("📊 Pipeline Observability")
col_a, col_b, col_c = st.columns(3)
with col_a:
    st.metric("Total Incidents (DB)", store.connection.execute("SELECT COUNT(*) FROM cable_incidents").fetchone()[0])
with col_b:
    st.metric("Latency Metrics (DB)", store.connection.execute("SELECT COUNT(*) FROM cloud_latency_metrics").fetchone()[0])
with col_c:
    st.metric("Quarantined Files", len(quarantine_files))
if st.button("🧹 Prune Old Latency Metrics (>90 days)"):
    pruned = store.prune_old_latency_metrics(retention_days=90)
    st.info(f"Pruned {pruned} old metrics")
