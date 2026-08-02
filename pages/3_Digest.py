"""
Page 3 — Digest: Gemini-generated executive risk briefs.
Pass C: glassmorphic theme + living header; LLM logic untouched.

Audit-viewer note: the raw_llm_response column stores the VERBATIM model output
(a faithful audit trail). The model cannot know its own version and hallucinates
a value (e.g. "1.0.0") for the model_version field inside that JSON. The stored
model_version COLUMN is the authoritative id (stamped in llm_engine), so the
"View Latest Raw Response" viewer overrides that one field with the column value
before rendering — the model's real words stay verbatim; only the unknowable id
is corrected. This self-heals already-stored briefs without regeneration.
"""
from __future__ import annotations

import json
import os
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
from src.theme import hero_html, inject_theme, led_strip_html, render_alert_chime_control, ticker_html

st.set_page_config(page_title="Risk Digest", page_icon="📋", layout="wide")
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
settings = st.session_state.get("settings") or get_settings()

if "briefs_df" not in st.session_state:
    st.session_state["briefs_df"] = store.get_latest_risk_briefs(limit=20)
briefs_df = st.session_state["briefs_df"]
headlines = [r.get("headline", "") for r in briefs_df.to_dicts()] if len(briefs_df) > 0 else []

st.markdown(ticker_html(headlines), unsafe_allow_html=True)
st.markdown(hero_html("📋 Executive Risk Digest — Gemini Briefs", "Structured JSON contract · strict schema · full audit trail"), unsafe_allow_html=True)
st.markdown(led_strip_html([
    ("Gemini", "ok" if (os.environ.get("GOOGLE_API_KEY") or os.environ.get("GEMINI_API_KEY") or settings.gemini_api_key) else "warn"),
    ("Schema", "ok"),
    ("Audit", "ok"),
    ("Briefs", "ok" if len(briefs_df) > 0 else "off"),
]), unsafe_allow_html=True)

# =============================================================================
# Risk Brief Generation
# =============================================================================
st.header("🤖 Generate New Risk Brief")
st.markdown("Generates a structured risk assessment using **Google Gemini** with strict JSON schema enforcement, fusing incidents + weather + news.")
col_gen, col_info = st.columns([2, 1])
with col_gen:
    generate_clicked = st.button("⚡ Generate Risk Brief", type="primary", use_container_width=True,
                                 help="Calls Gemini with active incident + signal context. Respects free-tier limits.")
with col_info:
    active_count = store.connection.execute("SELECT COUNT(*) FROM cable_incidents WHERE status IN ('cut','degraded','under_repair')").fetchone()[0]
    st.metric("Active Incidents (Context)", active_count)
    st.caption(f"Model: `{settings.gemini_model}` | Temp: `{settings.gemini_temperature}` | Retries: `{settings.gemini_max_retries}`")

if generate_clicked:
    if active_count == 0:
        st.warning("⚠️ No active incidents to assess. Inject demo data from the Input page first.")
    else:
        with st.spinner("🧠 Generating risk brief via Gemini..."):
            try:
                incident_context = store.get_signal_context_for_llm(limit=20)
                st.text_area("Context sent to Gemini (read-only)", value=incident_context, height=150, disabled=True, key="llm_context_preview")
                client = GeminiRiskBriefClient(settings)
                result = client.generate_brief_safe(incident_context)
                if result is not None:
                    brief, raw_response = result
                    store.persist_risk_brief(brief, raw_response)
                    st.success(f"✅ Risk brief generated: **{brief.headline}** (risk={brief.risk_level.value}, confidence={brief.confidence_score:.2f})")
                    st.session_state.pop("briefs_df", None)
                    st.rerun()
                else:
                    st.error("❌ Brief generation failed after retries. Check GOOGLE_API_KEY / GEMINI_API_KEY and connectivity.")
            except ValueError as ve:
                st.error(f"❌ Configuration error: {ve}"); logger.error("LLM config error: {}", str(ve))
            except Exception as exc:
                st.error(f"❌ Unexpected error during brief generation: {exc}"); logger.exception("Brief generation failed")

st.divider()

# =============================================================================
# Historical Risk Briefs
# =============================================================================
st.header("📜 Risk Brief History")
if len(briefs_df) == 0:
    st.info("No risk briefs generated yet. Use the button above to generate one.")
else:
    for idx in range(len(briefs_df)):
        row = briefs_df.row(idx, named=True)
        risk_level = row.get("risk_level", "unknown")
        risk_emoji = {"low": "🟢", "medium": "🟡", "high": "🟠", "critical": "🔴"}.get(risk_level, "⚪")
        with st.expander(f"{risk_emoji} [{risk_level.upper()}] {row.get('headline', 'Untitled Brief')} — {row.get('generated_at', 'N/A')}", expanded=(idx == 0)):
            col_summary, col_meta = st.columns([3, 1])
            with col_summary:
                st.markdown("**Executive Summary:**")
                st.write(row.get("executive_summary", "N/A"))
                st.markdown("**Recommended Actions:**")
                actions_raw = store.connection.execute("SELECT recommended_actions FROM risk_briefs WHERE brief_id = ?::UUID", [row.get("brief_id")]).fetchone()
                if actions_raw and actions_raw[0]:
                    try:
                        actions = json.loads(actions_raw[0]) if isinstance(actions_raw[0], str) else actions_raw[0]
                        for action in actions:
                            priority = action.get("priority", "medium")
                            badge = {"low": "🟢", "medium": "🟡", "high": "🟠", "critical": "🔴"}.get(priority, "⚪")
                            st.markdown(f"- {badge} **{action.get('action', 'N/A')}** — {action.get('rationale', '')}")
                    except (json.JSONDecodeError, TypeError):
                        st.write(str(actions_raw[0]))
            with col_meta:
                st.metric("Risk Level", risk_level.upper())
                st.metric("Traffic Impact", f"{row.get('estimated_impacted_traffic_pct', 0):.1f}%")
                st.metric("Confidence", f"{row.get('confidence_score', 0):.2f}")
                st.caption(f"Model: {row.get('model_version', 'N/A')}")
                for zone in (row.get("affected_zones", []) or []):
                    st.caption(f"• {zone}")
                for prov in (row.get("affected_cloud_providers", []) or []):
                    st.caption(f"• {prov}")

st.divider()

# =============================================================================
# Audit Trail
# =============================================================================
st.header("🔍 LLM Audit Trail")
st.markdown("Every Gemini response is persisted in `risk_briefs.raw_llm_response` (JSON) for full auditability and replay.")
st.metric("Total Audited LLM Calls", store.connection.execute("SELECT COUNT(*) FROM risk_briefs").fetchone()[0])
if st.button("📋 View Latest Raw Response"):
    # Fetch BOTH the verbatim raw blob AND the authoritative model_version column.
    row = store.connection.execute(
        "SELECT raw_llm_response, model_version FROM risk_briefs ORDER BY generated_at DESC LIMIT 1"
    ).fetchone()
    if row and row[0] is not None:
        raw_val, true_model = row[0], row[1]
        try:
            parsed = json.loads(raw_val) if isinstance(raw_val, str) else dict(raw_val)
            if isinstance(parsed, dict) and true_model:
                # The model hallucinates its own version (e.g. "1.0.0"); show the
                # real id from the stored column. Every other field stays verbatim.
                parsed["model_version"] = true_model
            st.json(parsed)
        except Exception:
            # If the blob is unexpectedly shaped, fall back to a verbatim display.
            st.json(raw_val if isinstance(raw_val, (dict, list)) else str(raw_val))
    else:
        st.info("No raw responses stored yet.")

logger.info("Digest page rendered with {} historical briefs", len(briefs_df))
