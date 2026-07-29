"""
Subsea Infrastructure & Cloud Risk Engine — Streamlit application shell.
Entry point that initializes the DuckDB store and provides navigation context.
"""
from __future__ import annotations

import sys
from pathlib import Path

# Ensure src/ is importable from pages/
APP_ROOT = Path(__file__).resolve().parent
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))

import streamlit as st
from loguru import logger

from src.config import EngineSettings, get_settings
from src.db_engine import RiskEngineStore


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


def main() -> None:
    """Main application shell with navigation sidebar."""
    st.set_page_config(
        page_title="Subsea Risk Engine",
        page_icon="🌊",
        layout="wide",
        initial_sidebar_state="expanded",
    )

    st.title("🌊 Subsea Infrastructure & Cloud Risk Engine")
    st.markdown(
        """
        **Production decision-support engine** for subsea cable fault monitoring
        and cloud infrastructure risk assessment.

        ---

        ### Navigation

        Use the sidebar to access:

        | Page | Function |
        |------|----------|
        | **1 — Input** | Feed configuration, manual ingestion triggers, quarantine viewer |
        | **2 — Status** | Live 3D geospatial risk map (PyDeck) |
        | **3 — Digest** | Gemini-generated executive risk briefs |

        ---

        ### System Status
        """
    )

    try:
        store = initialize_store()

        col1, col2, col3, col4 = st.columns(4)
        with col1:
            incident_count = store.connection.execute(
                "SELECT COUNT(*) FROM cable_incidents"
            ).fetchone()[0]
            st.metric("Total Incidents", incident_count)
        with col2:
            active_count = store.connection.execute(
                "SELECT COUNT(*) FROM cable_incidents WHERE status IN ('cut', 'degraded', 'under_repair')"
            ).fetchone()[0]
            st.metric("Active Faults", active_count)
        with col3:
            region_count = store.connection.execute(
                "SELECT COUNT(*) FROM cloud_regions"
            ).fetchone()[0]
            st.metric("Cloud Regions", region_count)
        with col4:
            brief_count = store.connection.execute(
                "SELECT COUNT(*) FROM risk_briefs"
            ).fetchone()[0]
            st.metric("Risk Briefs", brief_count)

        st.success("✅ DuckDB store connected and schema validated.")

    except Exception as exc:
        st.error(f"❌ Failed to initialize store: {exc}")
        logger.exception("Store initialization failed")

    st.markdown(
        """
        ---
        ### Intelligence Basis

        This engine operationalizes risk signals from:
        - **Chokepoint concentration**: Red Sea, Baltic Sea, Taiwan/Luzon Strait, Malacca/Singapore
        - **State-linked sabotage**: Shadow fleet anchor-dragging (C-Lion1, BCS East-West, Estlink 2)
        - **Conflict-zone severance**: Houthi Red Sea attacks (AAE-1, EIG, Seacom, TGN-Gulf)
        - **Repair fleet scarcity**: ~60 global ships, 2–4 week SLA
        - **Hyperscaler ownership**: Google (Curie, Dunant, Grace Hopper, Topaz), Meta (2Africa, Bifrost)
        - **Latency correlation**: Cloud inter-region anomalies as leading fault indicators
        """
    )


if __name__ == "__main__":
    main()
