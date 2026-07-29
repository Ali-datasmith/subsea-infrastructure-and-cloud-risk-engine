# 🌊 Subsea Infrastructure & Cloud Risk Engine

Production decision-support engine that fuses subsea cable fault telemetry,
AIS vessel correlations, and cloud latency anomalies into a unified 3D
geospatial risk dashboard enriched by Gemini structured-output risk briefs.

## Quick Start

```bash
cd app
cp .env.example .env   # fill in GEMINI_API_KEY + feed URLs
pip install -e ".[dev]"
streamlit run app.py
