import os
from types import SimpleNamespace

import pytest

from src.llm_engine import GeminiRiskBriefClient, _resolve_api_key, _resolve_model
from src.config import EngineSettings
from conftest import make_brief


class StubModels:
    def __init__(self, resp): self._resp = resp
    def generate_content(self, **kw):
        assert kw["config"].response_mime_type == "application/json"
        assert kw["config"].response_schema is not None
        return self._resp


def test_resolve_api_key_prefers_env_and_none_when_empty(monkeypatch):
    monkeypatch.setenv("GOOGLE_API_KEY", "env-key")
    assert _resolve_api_key(EngineSettings()) == "env-key"
    monkeypatch.delenv("GOOGLE_API_KEY")
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    assert _resolve_api_key(EngineSettings(gemini_api_key="")) is None


def test_resolve_model_env_override(monkeypatch):
    monkeypatch.setenv("GEMINI_MODEL", "custom-model")
    assert _resolve_model(EngineSettings()) == "custom-model"


def test_generate_brief_parsed_path(settings, monkeypatch):
    monkeypatch.setenv("GOOGLE_API_KEY", "test-key")
    expected = make_brief()
    client = GeminiRiskBriefClient(settings)
    client._client = SimpleNamespace(models=StubModels(
        SimpleNamespace(parsed=expected, text="{}")))
    brief, raw = client.generate_brief("context")
    assert brief.headline == expected.headline
    assert brief.model_version == client._model   # stamped, not self-reported


def test_generate_brief_json_fallback_path(settings, monkeypatch):
    monkeypatch.setenv("GOOGLE_API_KEY", "test-key")
    expected = make_brief()
    client = GeminiRiskBriefClient(settings)
    client._client = SimpleNamespace(models=StubModels(
        SimpleNamespace(parsed=None, text=expected.model_dump_json())))
    brief, raw = client.generate_brief("context")
    assert brief.confidence_score == expected.confidence_score
