"""
Gemini structured-output LLM client for risk brief generation.
Enforces Pydantic v2 schema via response_mime_type="application/json".
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
real-time monitoring system. You assess subsea cable incidents and their cascading
impact on cloud provider infrastructure.

Key risk domains to consider:
- Chokepoint concentration (Red Sea, Baltic Sea, Taiwan/Luzon Strait, Malacca/Singapore)
- State-linked / gray-zone sabotage (anchor-dragging shadow fleet vessels)
- Conflict-zone severance (Houthi Red Sea attacks, Taiwan Strait tensions)
- Repair fleet scarcity (~60 global ships, 2-4 week SLA)
- Hyperscaler cable ownership concentration (Google, Meta, Microsoft)
- Latency as a leading indicator of cable fault confirmation

Your output MUST conform exactly to the provided JSON schema. No free-text.
Assess risk conservatively — when uncertain, round UP risk level."""

BRIEF_GENERATION_PROMPT = """{system_context}

Given the following active incident data, generate a structured risk brief:

{incident_context}

Requirements:
- headline: max 140 chars, actionable
- executive_summary: max 1200 chars, covers affected zones, providers, traffic impact
- risk_level: one of low/medium/high/critical
- affected_zones: list of geopolitical zones impacted
- affected_cloud_providers: list of providers at risk
- estimated_impacted_traffic_pct: 0-100, conservative estimate
- confidence_score: 0-1, based on data completeness
- recommended_actions: 1-6 prioritized actions with rationale
"""


# =============================================================================
# Gemini Client
# =============================================================================


class GeminiRiskBriefClient:
    """
    Structured-output Gemini client that enforces GeminiRiskBrief schema
    on every response. Wrapped with tenacity exponential backoff.
    """

    def __init__(self, settings: EngineSettings) -> None:
        api_key = settings.gemini_api_key
        if not api_key:
            api_key = os.environ.get("GEMINI_API_KEY", "")
        if not api_key:
            logger.error("GEMINI_API_KEY not configured — LLM enrichment disabled")
            raise ValueError("GEMINI_API_KEY must be set in .env or environment")

        self._client = genai.Client(api_key=api_key)
        self._model = settings.gemini_model
        self._temperature = settings.gemini_temperature
        self._max_retries = settings.gemini_max_retries
        logger.info(
            "GeminiRiskBriefClient initialized: model={}, temp={}, retries={}",
            self._model,
            self._temperature,
            self._max_retries,
        )

    @retry(
        stop=stop_after_attempt(4),
        wait=wait_exponential(multiplier=1, min=2, max=20),
        retry=retry_if_exception_type(Exception),
        reraise=True,
    )
    def generate_brief(self, incident_context: str) -> tuple[GeminiRiskBrief, str]:
        """
        Generate a structured risk brief from incident context.
        Returns (validated_brief, raw_response_text) for audit persistence.

        Raises:
            ValueError: If Gemini response fails Pydantic schema validation.
            Exception: On API errors (retried via tenacity).
        """
        prompt = BRIEF_GENERATION_PROMPT.format(
            system_context=SYSTEM_CONTEXT,
            incident_context=incident_context,
        )

        logger.info("Sending risk brief generation request to Gemini ({})", self._model)

        response = self._client.models.generate_content(
            model=self._model,
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=GeminiRiskBrief,
                temperature=self._temperature,
            ),
        )

        raw_text = response.text
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
            raise ValueError(
                f"Schema validation failed: {validation_exc}"
            ) from validation_exc

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
        """
        Non-raising wrapper: returns None on failure instead of propagating.
        Useful for UI contexts where we want graceful degradation.
        """
        try:
            return self.generate_brief(incident_context)
        except Exception as exc:
            logger.error("Risk brief generation failed after retries: {}", str(exc))
            return None
