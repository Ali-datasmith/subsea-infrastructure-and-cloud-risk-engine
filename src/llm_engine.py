"""
Gemini structured-output LLM client for risk brief generation.

Pattern deliberately mirrors the proven `multi-ai-research-digest` engine:
  * genai.Client() is built so the SDK auto-reads the API key from the
    environment / Streamlit Secrets (GOOGLE_API_KEY or GEMINI_API_KEY); we only
    pass an explicit key if we actually found one, never an empty string.
  * The model id is resolved from st.secrets / env, defaulting to gemini-3.5-flash.
  * The validated object is read from response.parsed (native SDK parsing),
    with a model_validate_json(response.text) fallback for robustness.
  * response_mime_type="application/json" + response_schema=GeminiRiskBrief
    enforce the contract; the schema uses extra="ignore" so no
    "additionalProperties" key is emitted (Gemini rejects that with 400).
"""
from __future__ import annotations

import os
from typing import Optional

from google import genai
from google.genai import types
from loguru import logger
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from src.config import EngineSettings
from src.schemas import GeminiRiskBrief


# =============================================================================
# Prompt templates
# =============================================================================

SYSTEM_CONTEXT = """You are a senior subsea infrastructure risk analyst embedded in a
real-time monitoring system. You assess subsea cable incidents — together with live
marine weather and conflict/anchor/sabotage news — and their cascading impact on
cloud provider infrastructure.

Key risk domains to consider:
- Chokepoint concentration (Red Sea, Baltic Sea, Taiwan/Luzon Strait, Malacca/Singapore)
- State-linked / gray-zone sabotage (anchor-dragging shadow fleet vessels)
- Conflict-zone severance (Houthi Red Sea attacks, Taiwan Strait tensions)
- Repair fleet scarcity (~60 global ships, 2-4 week SLA); heavy weather delays ships
- Hyperscaler cable ownership concentration (Google, Meta, Microsoft)
- Latency as a leading indicator of cable fault confirmation
- Marine weather: high waves / gusts raise shallow-water fault probability and ground
  repair vessels; storm/quake-triggered slides can sever cables
- News: a conflict / anchor / sabotage headline near a chokepoint is an early-warning
  signal that latency alone cannot provide

Your output MUST conform exactly to the provided JSON schema. No free-text.
Assess risk conservatively — when uncertain, round UP the risk level."""

BRIEF_PROMPT = """Given the following active incident + external-signal data, generate a
structured risk brief:

{incident_context}

Requirements:
- headline: max 140 chars, actionable
- executive_summary: max 1200 chars; cover affected zones, providers, traffic impact,
  and explicitly factor in WEATHER (storm-induced faults / repair-ship delay) and NEWS
  (conflict / anchor / sabotage near chokepoints)
- risk_level: one of low/medium/high/critical
- affected_zones: list of geopolitical zones impacted
- affected_cloud_providers: list of providers at risk
- estimated_impacted_traffic_pct: 0-100, conservative estimate
- confidence_score: 0-1, based on data completeness
- recommended_actions: 1-6 prioritized actions with rationale
"""


# =============================================================================
# Helpers
# =============================================================================

def _resolve_model(settings: EngineSettings) -> str:
    """Resolve the Gemini model id exactly like the reference project:
    st.secrets -> env -> settings -> hard default gemini-3.5-flash."""
    model: Optional[str] = None
    try:
        import streamlit as st  # local import: engine is usable outside Streamlit too
        secrets = getattr(st, "secrets", None)
        if secrets is not None:
            try:
                model = secrets.get("GEMINI_MODEL")
            except Exception:
                model = None
    except Exception:
        model = None

    if not model:
        model = os.environ.get("GEMINI_MODEL")
    if not model:
        model = settings.gemini_model
    return model or "gemini-3.5-flash"


def _resolve_api_key(settings: EngineSettings) -> Optional[str]:
    """Prefer the env/Secret name used by the proven project (GOOGLE_API_KEY),
    then our GEMINI_API_KEY, then the settings value. Return None if empty so the
    SDK can auto-detect instead of receiving an empty string."""
    key = (
        os.environ.get("GOOGLE_API_KEY")
        or os.environ.get("GEMINI_API_KEY")
        or settings.gemini_api_key
        or None
    )
    if isinstance(key, str):
        key = key.strip() or None
    return key


# =============================================================================
# Gemini Client
# =============================================================================

class GeminiRiskBriefClient:
    """Structured-output Gemini client, mirroring the proven reference pattern."""

    def __init__(self, settings: EngineSettings) -> None:
        api_key = _resolve_api_key(settings)
        # Build exactly like the working project when no explicit key is found,
        # so the SDK reads the credential from the environment / Secrets itself.
        self._client = genai.Client(api_key=api_key) if api_key else genai.Client()
        self._model = _resolve_model(settings)
        self._temperature = settings.gemini_temperature
        self._max_retries = settings.gemini_max_retries
        logger.info(
            "GeminiRiskBriefClient initialized: model={}, temp={}, retries={}, explicit_key={}",
            self._model,
            self._temperature,
            self._max_retries,
            bool(api_key),
        )

    @retry(
        stop=stop_after_attempt(4),
        wait=wait_exponential(multiplier=1, min=2, max=20),
        retry=retry_if_exception_type(Exception),
        reraise=True,
    )
    def generate_brief(self, incident_context: str) -> tuple[GeminiRiskBrief, str]:
        """
        Generate a structured risk brief from incident + signal context.
        Returns (validated_brief, raw_response_text) for audit persistence.
        """
        prompt = BRIEF_PROMPT.format(incident_context=incident_context)
        brief.model_version = self._model  # stamp the real id; don't trust the model's self-report
        logger.info("Sending risk brief generation request to Gemini ({})", self._model)

        response = self._client.models.generate_content(
            model=self._model,
            contents=prompt,
            config=types.GenerateContentConfig(
                system_instruction=SYSTEM_CONTEXT,
                response_mime_type="application/json",
                response_schema=GeminiRiskBrief,
                temperature=self._temperature,
            ),
        )

        raw_text = response.text or ""

        # Native SDK parsing (the smoother path from the reference project).
        brief = getattr(response, "parsed", None)
        if brief is None:
            if not raw_text:
                logger.error("Gemini returned empty response text")
                raise ValueError("Gemini returned empty response")
            try:
                brief = GeminiRiskBrief.model_validate_json(raw_text)
            except Exception as validation_exc:
                logger.error(
                    "Gemini response failed Pydantic validation: {} | raw={}",
                    str(validation_exc),
                    raw_text[:500],
                )
                raise ValueError(f"Schema validation failed: {validation_exc}") from validation_exc
        elif not isinstance(brief, GeminiRiskBrief):
            # parsed came back as a dict-like in some SDK versions
            brief = GeminiRiskBrief.model_validate(brief)

        logger.info(
            "Generated risk brief {} | risk={} | confidence={:.2f} | actions={}",
            brief.brief_id,
            brief.risk_level.value,
            brief.confidence_score,
            len(brief.recommended_actions),
        )
        return brief, raw_text

    def generate_brief_safe(
        self, incident_context: str
    ) -> Optional[tuple[GeminiRiskBrief, str]]:
        """Non-raising wrapper: returns None on failure instead of propagating."""
        try:
            return self.generate_brief(incident_context)
        except Exception as exc:
            logger.error("Risk brief generation failed after retries: {}", str(exc))
            return None
