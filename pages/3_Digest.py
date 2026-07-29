"""
Page 3 — Digest: Gemini-generated executive risk briefs.
Triggers LLM enrichment and displays structured risk assessments.
"""
from __future__ import annotations

import sys
from pathlib import Path

APP_ROOT = Path(__file__).resolve().parent.parent
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))

import streamlit as st
from loguru import logger

from src.config import get_settings
from src.db_engine import RiskEngineStore
from src.llm_engine import GeminiRiskBriefClient
from src.schemas import RiskLevel


st.set_page_config(page_title="Risk Digest", page_icon="📋", layout="wide")
st.title("📋 Executive Risk Digest — Gemini Briefs")


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
settings = st.session_state.get("settings") or get_settings()

# =============================================================================
# Risk Brief Generation
# =============================================================================

st.header("🤖 Generate New Risk Brief")

st.markdown(
    """
    Generates a structured risk assessment using **Google Gemini** with strict
    JSON schema enforcement. The brief assesses current active incidents and
    their cascading impact on cloud infrastructure.
    """
)

col_gen, col_info = st.columns([2, 1])

with col_gen:
    generate_clicked = st.button(
        "⚡ Generate Risk Brief",
        type="primary",
        use_container_width=True,
        help="Calls Gemini with active incident context. Respects free-tier rate limits.",
    )

with col_info:
    active_count = store.connection.execute(
        "SELECT COUNT(*) FROM cable_incidents WHERE status IN ('cut', 'degraded', 'under_repair')"
    ).fetchone()[0]
    st.metric("Active Incidents (Context)", active_count)
    st.caption(
        f"Model: `{settings.gemini_model}` | "
        f"Temp: `{settings.gemini_temperature}` | "
        f"Retries: `{settings.gemini_max_retries}`"
    )

if generate_clicked:
    if active_count == 0:
        st.warning("⚠️ No active incidents to assess. Inject demo data from the Input page first.")
    else:
        with st.spinner("🧠 Generating risk brief via Gemini..."):
            try:
                incident_context = store.get_incident_context_for_llm(limit=20)
                st.text_area(
                    "Context sent to Gemini (read-only)",
                    value=incident_context,
                    height=150,
                    disabled=True,
                    key="llm_context_preview",
                )

                client = GeminiRiskBriefClient(settings)
                result = client.generate_brief_safe(incident_context)

                if result is not None:
                    brief, raw_response = result
                    store.persist_risk_brief(brief, raw_response)
                    st.success(
                        f"✅ Risk brief generated: **{brief.headline}** "
                        f"(risk={brief.risk_level.value}, confidence={brief.confidence_score:.2f})"
                    )
                    st.session_state.pop("briefs_df", None)
                    st.rerun()
                else:
                    st.error(
                        "❌ Brief generation failed after retries. "
                        "Check GEMINI_API_KEY and network connectivity."
                    )

            except ValueError as ve:
                st.error(f"❌ Configuration error: {ve}")
                logger.error("LLM config error: {}", str(ve))
            except Exception as exc:
                st.error(f"❌ Unexpected error during brief generation: {exc}")
                logger.exception("Brief generation failed")

st.divider()

# =============================================================================
# Historical Risk Briefs
# =============================================================================

st.header("📜 Risk Brief History")

if "briefs_df" not in st.session_state:
    st.session_state["briefs_df"] = store.get_latest_risk_briefs(limit=20)

briefs_df = st.session_state["briefs_df"]

if len(briefs_df) == 0:
    st.info("No risk briefs generated yet. Use the button above to generate one.")
else:
    for idx in range(len(briefs_df)):
        row = briefs_df.row(idx, named=True)

        risk_level = row.get("risk_level", "unknown")
        risk_emoji = {
            "low": "🟢",
            "medium": "🟡",
            "high": "🟠",
            "critical": "🔴",
        }.get(risk_level, "⚪")

        with st.expander(
            f"{risk_emoji} [{risk_level.upper()}] {row.get('headline', 'Untitled Brief')} "
            f"— {row.get('generated_at', 'N/A')}",
            expanded=(idx == 0),
        ):
            col_summary, col_meta = st.columns([3, 1])

            with col_summary:
                st.markdown(f"**Executive Summary:**")
                st.write(row.get("executive_summary", "N/A"))

                st.markdown(f"**Recommended Actions:**")
                actions_raw = store.connection.execute(
                    "SELECT recommended_actions FROM risk_briefs WHERE brief_id = ?::UUID",
                    [row.get("brief_id")],
                ).fetchone()
                if actions_raw and actions_raw[0]:
                    import json
                    try:
                        actions = json.loads(actions_raw[0]) if isinstance(actions_raw[0], str) else actions_raw[0]
                        for action in actions:
                            priority = action.get("priority", "medium")
                            priority_badge = {
                                "low": "🟢",
                                "medium": "🟡",
                                "high": "🟠",
                                "critical": "🔴",
                            }.get(priority, "⚪")
                            st.markdown(
                                f"- {priority_badge} **{action.get('action', 'N/A')}** — "
                                f"{action.get('rationale', '')}"
                            )
                    except (json.JSONDecodeError, TypeError):
                        st.write(str(actions_raw[0]))

            with col_meta:
                st.metric("Risk Level", risk_level.upper())
                st.metric(
                    "Traffic Impact",
                    f"{row.get('estimated_impacted_traffic_pct', 0):.1f}%",
                )
                st.metric(
                    "Confidence",
                    f"{row.get('confidence_score', 0):.2f}",
                )
                st.caption(f"Model: {row.get('model_version', 'N/A')}")

                zones = row.get("affected_zones", [])
                if zones:
                    st.markdown("**Zones:**")
                    for zone in zones:
                        st.caption(f"• {zone}")

                providers = row.get("affected_cloud_providers", [])
                if providers:
                    st.markdown("**Providers:**")
                    for prov in providers:
                        st.caption(f"• {prov}")

st.divider()

# =============================================================================
# Audit Trail
# =============================================================================

st.header("🔍 LLM Audit Trail")

st.markdown(
    "Every Gemini response is persisted in `risk_briefs.raw_llm_response` (VARIANT) "
    "for full auditability and replay capability."
)

audit_count = store.connection.execute("SELECT COUNT(*) FROM risk_briefs").fetchone()[0]
st.metric("Total Audited LLM Calls", audit_count)

if st.button("📋 View Latest Raw Response"):
    raw = store.connection.execute(
        "SELECT raw_llm_response FROM risk_briefs ORDER BY generated_at DESC LIMIT 1"
    ).fetchone()
    if raw and raw[0]:
        st.json(raw[0] if isinstance(raw[0], dict) else str(raw[0]))
    else:
        st.info("No raw responses stored yet.")

logger.info("Digest page rendered with {} historical briefs", len(briefs_df))
