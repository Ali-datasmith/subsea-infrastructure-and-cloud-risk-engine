"""
Centralized configuration via pydantic-settings BaseSettings.
All secrets and environment-driven parameters are loaded from .env / Cloud Secrets.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Optional

from loguru import logger
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class EngineSettings(BaseSettings):
    """Application-wide settings sourced from environment / .env file."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ─── Secrets ───────────────────────────────────────────────────────────
    gemini_api_key: str = Field(default="", description="Google Gemini API key")

    # ─── Feed Endpoints ────────────────────────────────────────────────────
    cable_fault_feed_url: str = Field(
        default="https://api.example-cable-tracker.io/v1",
        description="Base URL for cable fault feed API",
    )
    ais_feed_url: str = Field(
        default="https://api.example-ais-provider.io/v2",
        description="Base URL for AIS vessel tracking API",
    )
    cloud_status_aws_url: str = Field(
        default="https://health.aws.amazon.com/public/currentevents",
        description="AWS Health Dashboard endpoint",
    )
    cloud_status_azure_url: str = Field(
        default="https://status.azure.com/api/v2/status",
        description="Azure Status API endpoint",
    )
    cloud_status_gcp_url: str = Field(
        default="https://status.cloud.google.com/incidents.json",
        description="GCP Incident feed endpoint",
    )

    # ─── DuckDB ────────────────────────────────────────────────────────────
    duckdb_path: str = Field(
        default="data/risk_engine.duckdb",
        description="Path to persistent DuckDB database file",
    )
    ddl_path: str = Field(
        default="ddl.sql",
        description="Path to DDL bootstrap SQL script",
    )

    # ─── Logging ───────────────────────────────────────────────────────────
    log_level: str = Field(default="INFO", description="loguru log level")
    log_file: str = Field(
        default="logs/risk_engine.jsonl",
        description="Path to structured JSON log sink",
    )

    # ─── Spatial ───────────────────────────────────────────────────────────
    spatial_join_radius_km: float = Field(
        default=2000.0,
        description="Radius (km) for incident-to-cloud-region spatial join",
    )
    h3_resolution: int = Field(
        default=3,
        description="H3 hexagonal resolution for risk zone aggregation",
    )

    # ─── LLM ───────────────────────────────────────────────────────────────
    # Hard-wired to the model proven in the working reference project.
    gemini_model: str = Field(default="gemini-3.5-flash", description="Gemini model ID")
    gemini_temperature: float = Field(default=0.2, ge=0.0, le=2.0)
    gemini_max_retries: int = Field(default=4, ge=1, le=10)

    # ─── Derived Paths ─────────────────────────────────────────────────────
    @property
    def quarantine_dir(self) -> Path:
        return Path("data/quarantine")

    @property
    def log_dir(self) -> Path:
        return Path(self.log_file).parent


def configure_logging(settings: EngineSettings) -> None:
    """Configure loguru with structured JSON sink and stderr output."""
    logger.remove()
    settings.log_dir.mkdir(parents=True, exist_ok=True)

    logger.add(
        sys.stderr,
        level=settings.log_level,
        format=(
            "<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | "
            "<level>{level: <8}</level> | "
            "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> | "
            "<level>{message}</level>"
        ),
        colorize=True,
    )
    logger.add(
        str(settings.log_file),
        level=settings.log_level,
        format="{message}",
        serialize=True,
        rotation="50 MB",
        retention="30 days",
        compression="gz",
    )
    logger.info("Logging configured: level={}, sink={}", settings.log_level, settings.log_file)


def get_settings() -> EngineSettings:
    """Factory for EngineSettings with logging bootstrap."""
    settings = EngineSettings()
    configure_logging(settings)
    settings.quarantine_dir.mkdir(parents=True, exist_ok=True)
    return settings
