"""
Subsea Infrastructure & Cloud Risk Engine — Streamlit application shell.
Pass C: glassmorphic theme + living header layered over the working engine.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

APP_ROOT = Path(__file__).resolve().parent
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))

import streamlit as st
from loguru import logger

from src.config import EngineSettings, get_settings
from src.db_engine import RiskEngineStore
from src.theme import (
    hero_html,
    inject_theme,
    led_strip_html,
    render_alert_chime_control,
    ticker_html,
)


def initialize_store() -> RiskEngineStore:
    """Initialize or retrieve the DuckDB store from Streamlit session state."""
    if "store" not in st.session_state:
        settings = get_settings()
        store = RiskEngineStore(settings)
        store.bootstrap_schema()
        st.session_state["store"] = store
        st.session_state["settings"] = settings
        logger.info("RiskEngineStore initialized and schema bootstrapped")
    return st.session_state["store"]


def _gemini_present() -> bool:
    try:
        s = st.session_state.get("settings")
        return bool(
            os.environ.get("GOOGLE_API_KEY")
            or os.environ.get("GEMINI_API_KEY")
            or (getattr(s, "gemini_api_key", "") if s else "")
        )
    except Exception:
        return False


def main() -> None:
    """Main application shell with navigation sidebar."""
    st.set_page_config(
        page_title="Subsea Risk Engine",
        page_icon="🌊",
        layout="wide",
        initial_sidebar_state="expanded",
    )
    inject_theme()
    render_alert_chime_control()

    st.markdown(
        ticker_html(["SUBSEA RISK ENGINE ONLINE", "FUSION PIPELINE READY", "GEMINI 3.5‑FLASH"]),
        unsafe_allow_html=True,
    )
    st.markdown(
        hero_html(
            "🌊 Subsea Infrastructure & Cloud Risk Engine",
            "Production decision-support: cable faults × marine weather × conflict news × shadow-fleet AIS → fused cloud-risk verdicts.",
        ),
        unsafe_allow_html=True,
    )

    store_ok = False
    try:
        store = initialize_store()
        store_ok = True
    except Exception as exc:
        st.error(f"❌ Failed to initialize store: {exc}")
        logger.exception("Store initialization failed")
        store = None

    st.markdown(
        led_strip_html([
            ("DuckDB", "ok" if store_ok else "crit"),
            ("Gemini", "ok" if _gemini_present() else "warn"),
            ("Weather", "ok"),
            ("News RSS", "ok"),
            ("Live Feeds", "warn"),
        ]),
        unsafe_allow_html=True,
    )

    if store is not None:
        col1, col2, col3, col4 = st.columns(4)
        with col1:
            st.metric("Total Incidents", store.connection.execute("SELECT COUNT(*) FROM cable_incidents").fetchone()[0])
        with col2:
            st.metric("Active Faults", store.connection.execute(
                "SELECT COUNT(*) FROM cable_incidents WHERE status IN ('cut','degraded','under_repair')"
            ).fetchone()[0])
        with col3:
            st.metric("Cloud Regions", store.connection.execute("SELECT COUNT(*) FROM cloud_regions").fetchone()[0])
        with col4:
            st.metric("Risk Briefs", store.connection.execute("SELECT COUNT(*) FROM risk_briefs").fetchone()[0])
        st.success("✅ DuckDB store connected and schema validated.")

    st.markdown(
        """
        ### Intelligence Basis
        This engine operationalizes risk signals from:
        - **Chokepoint concentration** — Red Sea, Baltic Sea, Taiwan/Luzon Strait, Malacca/Singapore
        - **State-linked sabotage** — shadow-fleet anchor-dragging (C‑Lion1, BCS East‑West, Estlink 2)
        - **Conflict-zone severance** — Houthi Red Sea attacks (AAE‑1, EIG, Seacom, TGN‑Gulf)
        - **Repair fleet scarcity** — ~60 global ships, 2–4 week SLA
        - **Hyperscaler ownership** — Google (Curie, Dunant, Grace Hopper, Topaz), Meta (2Africa, Bifrost)
        - **Latency correlation** — cloud inter-region anomalies as leading fault indicators
        """
    )


main()
