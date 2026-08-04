<img width="1024" height="572" alt="image" src="https://github.com/user-attachments/assets/adfc77f4-bc6c-4d5f-87bc-2051a5090a10" />


# Subsea Infrastructure & Cloud Risk Engine

[![CI](https://github.com/Ali-datasmith/subsea-infrastructure-and-cloud-risk-engine/actions/workflows/ci.yml/badge.svg)](https://github.com/Ali-datasmith/subsea-infrastructure-and-cloud-risk-engine/actions)

**A Streamlit decision-support dashboard that answers one question: given current subsea cable health, which cloud regions/providers are at elevated risk of degraded performance or isolation — and what should you do about it?**

<p align="center">
  <img alt="Python" src="https://img.shields.io/badge/python-3.10%2B-blue?logo=python&logoColor=white">
  <img alt="Streamlit" src="https://img.shields.io/badge/streamlit-multipage-FF4B4B?logo=streamlit&logoColor=white">
  <img alt="Polars" src="https://img.shields.io/badge/polars-LazyFrame-CD792C">
  <img alt="DuckDB" src="https://img.shields.io/badge/duckdb-GEOMETRY%20%2B%20JSON-FFF000?logo=duckdb&logoColor=black">
  <img alt="Pydantic" src="https://img.shields.io/badge/pydantic-v2-E92063">
  <img alt="Gemini" src="https://img.shields.io/badge/gemini-3.5--flash-8E75B2?logo=googlegemini&logoColor=white">
  <img alt="Status" src="https://img.shields.io/badge/status-active-brightgreen">
</p>

---

## 🎬 Demo Video (Loom)
https://github.com/user-attachments/assets/041994cd-3658-4ca6-86b7-540aca5f0137
---

## Overview

Subsea cables carry most intercontinental internet traffic. A small number of geographic chokepoints — the Red Sea/Bab-el-Mandeb, the Baltic, Taiwan/Luzon, and Malacca/Singapore — concentrate the risk. A fault at one of these corridors, whether from anchor drag, gray-zone sabotage, or severe weather, can degrade or isolate the cloud regions that depend on it. The global repair fleet is small (~60 specialized ships), and repair SLAs run 2–4 weeks once a fault is confirmed.

No single free, real-time feed connects "cable X is degraded" to "cloud region Y is at risk." This project fuses cable incident data, marine weather over cable corridors, conflict/sabotage news, and cloud provider status into one composite risk view, then uses an LLM to turn that fused state into a structured risk brief — all wrapped in a glassmorphic "Deep Ocean & Electric Cyan" command-center UI.

---

## Architecture

```text
                        SIGNAL LAYERS
   • Cable incidents (demo injection)
   • Marine weather — Open-Meteo (keyless)
   • Conflict / sabotage news — Google News RSS (keyless)
   • Cloud status probes — AWS / Azure / GCP
   • AIS-style vessel correlation (shadow-fleet flagging)
                                │
                                ▼
┌──────────────┐   ┌──────────────┐   ┌──────────────┐   ┌──────────────┐   ┌──────────────┐   ┌──────────────┐
│  INGESTION   │─▶ │  VALIDATION  │─▶ │  PROCESSING  │─▶ │   STORAGE    │─▶ │  ENRICHMENT  │─▶ │ PRESENTATION │
└──────────────┘   └──────────────┘   └──────────────┘   └──────────────┘   └──────────────┘   └──────────────┘
```

| Stage | What happens |
|---|---|
| 1. Ingestion | `httpx` + `tenacity` async fetch with exponential backoff; `feedparser` for RSS; degrade-by-design |
| 2. Validation | Pydantic v2 edge models; malformed/schema-mismatched records → **quarantine** |
| 3. Processing | Polars (LazyFrame, zero-copy) transforms; Pandera quality gates |
| 4. Storage | DuckDB with native `GEOMETRY`/`JSON`, spatial + h3 extensions; composite cable risk scoring, H3 aggregation |
| 5. Enrichment | Gemini (`google-genai`, `gemini-3.5-flash`) generates a structured risk brief via strict Pydantic JSON schema; full raw-response audit trail |
| 6. Presentation | Streamlit (multipage) + glassmorphic theme; Folium/Leaflet map on Carto dark raster tiles |

---

## Key Features

- **Multi-signal risk fusion** — combines cable incident telemetry, marine weather, conflict/sabotage news, and cloud status into one composite risk view.
- **Marine weather intelligence** — wave, gust, and wind data over cable corridors via Open-Meteo (free, no key) to estimate fault probability and repair-vessel delay.
- **Conflict / anchor / sabotage watch** — Google News RSS keyword monitoring (free, no key), tagged by zone and severity.
- **Cloud status probing** — checks public AWS/Azure/GCP status endpoints; mismatched payloads are quarantined instead of crashing the pipeline.
- **AIS-style vessel correlation** — shadow-fleet flagging built into the incident schema.
- **LLM risk briefs** — Gemini (`gemini-3.5-flash` via `google-genai`) generates structured, schema-validated risk briefs with a full raw-response audit trail.
- **Cable status map** — Folium/Leaflet map with neon status-colored cable arcs, fault markers, a risk heat layer, and cloud-region nodes.
- **Glassmorphic command-center UI** — a "Deep Ocean & Electric Cyan" theme with frosted-glass panels and a living header (pulsing LED strip, scrolling ticker, breathing LIVE badge, scanline sweep); pure CSS, no extra JS dependencies.
- **Resilient ingestion** — async fetch with retry/backoff; malformed data is quarantined, not dropped.

---

## Tech Stack

| Category | Technology | Purpose |
|---|---|---|
| App framework | Streamlit (multipage) | Home / Input / Status / Digest pages |
| Data processing | Polars (LazyFrame, zero-copy) | Transforms ingested signals |
| Storage / query | DuckDB (native `GEOMETRY` + `JSON`, spatial + h3 extensions) | Spatial storage, H3 aggregation, composite risk scoring |
| Validation | Pydantic v2 + pydantic-settings | Edge model validation, typed settings |
| Quality gates | Pandera (Polars) | Schema/quality enforcement on processed frames |
| LLM | google-genai (`gemini-3.5-flash`, free tier) | Structured JSON risk brief generation |
| Mapping | Folium + Leaflet, Carto dark raster tiles | Token-free interactive map |
| Networking | httpx + tenacity | Async ingestion with exponential backoff |
| Feeds | feedparser | Google News RSS parsing |
| UI theme | Pure CSS (`src/theme.py`) | Glassmorphic styling + living effects |
| Logging | loguru | Structured JSON logging |
| Language | Python 3.10+ | Core runtime |

---

## Repository Layout

```text
subsea-infrastructure-and-cloud-risk-engine/
├── app.py                 # Home — system status + intelligence basis (glass shell)
├── pages/
│   ├── 1_Input.py         # Feed config, live feeds, demo injection, quarantine viewer
│   ├── 2_Status.py        # Folium dark map, risk metrics, external-signals panel
│   └── 3_Digest.py        # Gemini risk brief generation + audit trail
├── src/
│   ├── __init__.py        # Package marker
│   ├── config.py          # App configuration / settings
│   ├── schemas.py         # Pydantic edge models
│   ├── data_engine.py     # Polars processing + Pandera quality gates
│   ├── db_engine.py       # DuckDB storage / spatial + H3 logic
│   ├── ingestion.py       # Async resilient ingestion (httpx + tenacity)
│   ├── free_feeds.py      # Open-Meteo + Google News RSS integrations
│   ├── llm_engine.py      # Gemini structured risk brief generation
│   ├── theme.py           # "Deep Ocean & Electric Cyan" glass theme + living UI
│   └── viz_layers.py      # Folium/Leaflet neon map layer construction
├── ddl.sql                # DuckDB schema definitions
├── requirements.txt       # Python dependencies
├── pyproject.toml         # Project metadata / build config
└── README.md
```

---

## Quick Start

### Local

```bash
git clone https://github.com/Ali-datasmith/subsea-infrastructure-and-cloud-risk-engine.git
cd subsea-infrastructure-and-cloud-risk-engine

pip install -r requirements.txt

# required
export GOOGLE_API_KEY="your-api-key-here"
# optional (default shown)
export GEMINI_MODEL="gemini-3.5-flash"

streamlit run app.py
```

### Deploy on Streamlit Community Cloud

1. Push the repo to GitHub and connect it in Streamlit Community Cloud.
2. Set **Main file path** to `app.py`.
3. Set **Python version** to `3.12`.
4. In **Advanced Settings → Secrets**, add:

```toml
GOOGLE_API_KEY = "your-api-key-here"
GEMINI_MODEL = "gemini-3.5-flash"
```

---

## Configuration & Secrets

| Variable | Required | Default | Description |
|---|---|---|---|
| `GOOGLE_API_KEY` | Yes | — | API key for the `google-genai` SDK, used for Gemini risk brief generation |
| `GEMINI_MODEL` | No | `gemini-3.5-flash` | Gemini model identifier used for structured-output generation |

No other API keys are required. The weather and news signal layers use free, keyless public endpoints.

---

## Pages Walkthrough

| Page | File | Description |
|---|---|---|
| Home | `app.py` | System status metrics, the current intelligence basis, and the glass command-center shell |
| Input | `pages/1_Input.py` | Feed configuration, live keyless feeds (Open-Meteo weather + Google News RSS), demo incident injection, quarantine viewer, pipeline observability |
| Status | `pages/2_Status.py` | Folium dark map with neon status-colored cable arcs, fault markers, risk heat layer, cloud-region nodes; risk summary metrics; external-signals (weather / news / composite score) panel |
| Digest | `pages/3_Digest.py` | Gemini risk brief generation, risk brief history, LLM audit trail |

---

## Data & Signal Model

The engine fuses the following signal layers into a composite cable/region risk score:

1. **Cable fault/incident telemetry** — structured incident records. No free real-time subsea fault API exists, so this layer runs on demo injection.
2. **Marine weather over cable corridors** — Open-Meteo wave, gust, and wind data, used as a proxy for fault probability and repair-vessel delay.
3. **Conflict / anchor / sabotage news** — Google News RSS keyword watch, tagged by zone and severity.
4. **Cloud provider status/latency probes** — public AWS/Azure/GCP status endpoints; mismatched payload shapes are quarantined rather than misinterpreted.
5. **AIS-style vessel correlation** — a shadow-fleet flagging model embedded in the incident schema, supporting anchor-drag/sabotage correlation.
6. **LLM enrichment** — Gemini turns the fused, stored state into a structured risk brief via a strict Pydantic schema.

All signals are stored in DuckDB with native `GEOMETRY`/`JSON` support and H3-based spatial aggregation, producing a composite cable risk score per corridor.

---

## Free-Tier Data Sources

| Source | Signal | Auth |
|---|---|---|
| Open-Meteo | Marine/weather data over cable corridors | None (keyless) |
| Google News RSS | Conflict/anchor/sabotage keyword monitoring | None (keyless) |
| AWS / Azure / GCP public status endpoints | Cloud provider status probes | None (public) |
| Gemini (`google-genai`) | Structured risk brief generation | `GOOGLE_API_KEY` (free tier) |

---

## Resilience & Quality Gates

- **Async, resilient ingestion** — `httpx` + `tenacity` with exponential backoff for all external calls.
- **Degrade-by-design** — individual feed failures don't take down the pipeline.
- **Quarantine, not crash** — malformed or schema-mismatched payloads (e.g., cloud status responses that don't match the expected shape) are routed to a quarantine path, surfaced in the Input page's quarantine viewer, instead of causing failures.
- **Edge validation** — Pydantic v2 models validate every incoming record at the ingestion boundary.
- **Processing-layer gates** — Pandera enforces data quality constraints on Polars frames before they reach storage.
- **Structured LLM output** — Gemini calls use a strict Pydantic JSON schema (`response_mime_type="application/json"`) instead of freeform text parsing.

---

## Observability

- **Structured JSON logging** via `loguru` throughout ingestion and processing.
- **Pipeline observability panel** on the Input page, surfacing feed health and quarantine activity.
- **LLM audit trail** on the Digest page — every Gemini request/response is retained for review, alongside risk brief history.

---

## Limitations

This is a decision-support prototype built entirely on free-tier and public data.

- **No free real-time subsea cable fault API exists.** The structured cable-fault feed is demo/synthetic (via demo incident injection), not a live production feed.
- **Cloud status probes are not latency feeds.** AWS/Azure/GCP public status endpoints return incident-shaped data; payloads that don't match the expected shape are quarantined rather than used as latency signal.
- **The map basemap is a reliability trade-off.** Carto dark raster tiles are used specifically for reliable rendering inside Streamlit Community Cloud's iframe.

---

## License / Author

**Author:** [Ali-datasmith](https://github.com/Ali-datasmith)

See the repository for license details.
