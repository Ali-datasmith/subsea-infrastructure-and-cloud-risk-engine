"""
Pass B — keyless, free-tier external signal clients.

- OpenMeteoClient : marine + forecast weather over cable corridors (NO API key).
- RssNewsClient   : Google News RSS keyword watch for conflict / anchor /
                    sabotage signals near chokepoints (NO API key).

Both are server-side (httpx async + tenacity). They NEVER raise into the UI:
every network failure degrades to an empty list with a loguru warning, so a
flaky free feed can never blank a page. Synthetic builders at the bottom let
the demo loop show a full picture with zero network.
"""
from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Optional
from urllib.parse import quote
from uuid import uuid4

import feedparser
import httpx
from loguru import logger
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from src.config import EngineSettings
from src.schemas import NewsRiskSignal, WeatherRiskSignal


# =============================================================================
# Representative sample point per geopolitical zone (lat, lon).
# Weather is fetched here and joined to cables by zone in the scorer.
# =============================================================================
ZONE_SAMPLE_POINTS: dict[str, tuple[float, float]] = {
    "red_sea_bab_el_mandeb": (12.6, 43.5),
    "baltic_sea": (58.5, 20.0),
    "taiwan_luzon_strait": (22.0, 121.5),
    "malacca_singapore_strait": (2.5, 101.5),
    "west_africa_coast": (6.5, 3.4),
    "egypt_land_bridge": (30.0, 32.5),
}

# Keyword watch → (rss query, zone, baseline severity).
KEYWORD_ZONE_QUERIES: list[tuple[str, str, str]] = [
    ("submarine cable cut Red Sea", "red_sea_bab_el_mandeb", "high"),
    ("Baltic Sea cable anchor damage", "baltic_sea", "high"),
    ("Taiwan strait undersea cable", "taiwan_luzon_strait", "medium"),
    ("Malacca strait submarine cable", "malacca_singapore_strait", "medium"),
    ("West Africa submarine cable fault", "west_africa_coast", "medium"),
    ("subsea cable sabotage gray zone", "red_sea_bab_el_mandeb", "medium"),
]

# Tokens used to (a) record matches and (b) bump severity from a headline.
MATCH_KEYWORDS: list[str] = [
    "cut", "severed", "severance", "sabotage", "anchor", "trawler",
    "seismic", "outage", "houthi", "red sea", "baltic", "taiwan",
    "malacca", "cable", "drone", "mine",
]
_CRITICAL_TOKENS = ("cut", "severed", "severance", "sabotage", "sever")
_HIGH_TOKENS = ("anchor", "trawler", "damage", "fault", "outage", "drone", "mine")
_MEDIUM_TOKENS = ("tension", "military", "exercise", "drill", "monitor", "degrad")

_SEV_RANK = {"low": 1, "medium": 2, "high": 3, "critical": 4}
_RANK_SEV = {1: "low", 2: "medium", 3: "high", 4: "critical"}


# =============================================================================
# Weather scoring helpers
# =============================================================================


def _clip01(value: float, lo: float, hi: float) -> float:
    if hi <= lo:
        return 0.0
    return max(0.0, min(1.0, (value - lo) / (hi - lo)))


def compute_weather_probability(
    wind_kmh: float, gust_kmh: float, wave_m: float, precip_mm: float
) -> float:
    """
    Map marine conditions to a 0..1 fault-probability signal.
    Weights: wave 0.30, gust 0.30, wind 0.20, heavy-rain 0.20.
    """
    p = (
        0.30 * _clip01(wave_m, 0.0, 4.0)
        + 0.30 * _clip01(gust_kmh, 0.0, 80.0)
        + 0.20 * _clip01(wind_kmh, 0.0, 60.0)
        + 0.20 * (1.0 if precip_mm > 5.0 else 0.0)
    )
    return round(min(1.0, p), 3)


def repair_vessel_delayed(wave_m: float, gust_kmh: float) -> bool:
    """Cable ships typically cannot operate in heavy sea / high gusts."""
    return wave_m > 2.5 or gust_kmh > 60.0


def _severity_from_title(title: str, baseline: str) -> str:
    low = title.lower()
    rank = _SEV_RANK.get(baseline, 2)
    if any(tok in low for tok in _CRITICAL_TOKENS):
        rank = max(rank, 4)
    elif any(tok in low for tok in _HIGH_TOKENS):
        rank = max(rank, 3)
    elif any(tok in low for tok in _MEDIUM_TOKENS):
        rank = max(rank, 2)
    return _RANK_SEV[rank]


def _parse_entry_time(entry) -> datetime:
    tp = getattr(entry, "published_parsed", None) or getattr(entry, "updated_parsed", None)
    if tp:
        try:
            return datetime.fromtimestamp(time.mktime(tp), tz=timezone.utc)
        except Exception:
            pass
    return datetime.now(timezone.utc)


# =============================================================================
# Open-Meteo client (free, no key)
# =============================================================================


class OpenMeteoClient:
    """Fetch marine + forecast weather for each cable corridor zone."""

    def __init__(self, settings: EngineSettings) -> None:
        self._settings = settings
        self._timeout = httpx.Timeout(12.0, connect=5.0)

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=8),
        retry=retry_if_exception_type(
            (httpx.HTTPStatusError, httpx.ConnectError, httpx.TimeoutException)
        ),
        reraise=True,
    )
    async def _fetch_zone(self, zone: str, lat: float, lon: float) -> Optional[WeatherRiskSignal]:
        forecast_url = (
            "https://api.open-meteo.com/v1/forecast"
            f"?latitude={lat}&longitude={lon}"
            "&current=wind_speed_10m,wind_gusts_10m,precipitation"
            "&wind_speed_unit=kmh"
        )
        marine_url = (
            "https://marine-api.open-meteo.com/v1/marine"
            f"?latitude={lat}&longitude={lon}&current=wave_height&timezone=auto"
        )
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            f_resp = await client.get(forecast_url)
            f_resp.raise_for_status()
            m_resp = await client.get(marine_url)
            m_resp.raise_for_status()

        f_cur = f_resp.json().get("current", {}) or {}
        m_cur = m_resp.json().get("current", {}) or {}

        wind = float(f_cur.get("wind_speed_10m") or 0.0)
        gust = float(f_cur.get("wind_gusts_10m") or 0.0)
        precip = float(f_cur.get("precipitation") or 0.0)
        wave = float(m_cur.get("wave_height") or 0.0)

        prob = compute_weather_probability(wind, gust, wave, precip)
        delayed = repair_vessel_delayed(wave, gust)

        signal = WeatherRiskSignal(
            sample_id=uuid4(),
            cable_id=None,
            zone=zone,
            sample_lat=lat,
            sample_lon=lon,
            sampled_at=datetime.now(timezone.utc),
            wind_speed_kmh=wind,
            wind_gust_kmh=gust,
            wave_height_m=wave,
            precipitation_mm=precip,
            weather_fault_probability=prob,
            repair_vessel_delayed=delayed,
            raw_payload={"source": "open-meteo", "forecast": f_cur, "marine": m_cur},
        )
        logger.info(
            "Weather[{}] wave={:.1f}m gust={:.0f}km/h prob={:.2f} delayed={}",
            zone, wave, gust, prob, delayed,
        )
        return signal

    async def fetch_all_zones(self) -> list[WeatherRiskSignal]:
        """Concurrent fetch over all corridor zones; failures degrade to skip."""
        import asyncio

        async def _safe(zone: str, lat: float, lon: float):
            try:
                return await self._fetch_zone(zone, lat, lon)
            except Exception as exc:
                logger.warning("Weather fetch failed for {} (skipped): {}", zone, exc)
                return None

        tasks = [
            _safe(zone, lat, lon)
            for zone, (lat, lon) in ZONE_SAMPLE_POINTS.items()
        ]
        results = await asyncio.gather(*tasks)
        signals = [s for s in results if s is not None]
        logger.info("Open-Meteo returned {} zone weather samples", len(signals))
        return signals


# =============================================================================
# Google News RSS client (free, no key)
# =============================================================================


class RssNewsClient:
    """Keyword-watch over Google News RSS, tagged by zone + severity."""

    def __init__(self, settings: EngineSettings) -> None:
        self._settings = settings
        self._timeout = httpx.Timeout(12.0, connect=5.0)

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=8),
        retry=retry_if_exception_type(
            (httpx.HTTPStatusError, httpx.ConnectError, httpx.TimeoutException)
        ),
        reraise=True,
    )
    async def _fetch_query(
        self, query: str, zone: str, baseline: str, per_query: int = 5
    ) -> list[NewsRiskSignal]:
        url = (
            "https://news.google.com/rss/search?q="
            f"{quote(query)}&hl=en-US&gl=US&ceid=US:en"
        )
        async with httpx.AsyncClient(timeout=self._timeout, follow_redirects=True) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            feed = feedparser.parse(resp.text)

        signals: list[NewsRiskSignal] = []
        for entry in feed.entries[:per_query]:
            title = (getattr(entry, "title", "") or "").strip()
            link = (getattr(entry, "link", "") or "").strip()
            if not title or not link:
                continue
            matched = [k for k in MATCH_KEYWORDS if k in title.lower()]
            severity = _severity_from_title(title, baseline)
            signals.append(
                NewsRiskSignal(
                    news_id=uuid4(),
                    source="google-news-rss",
                    title=title[:280],
                    link=link,
                    published_at=_parse_entry_time(entry),
                    zone=zone,
                    severity=severity,
                    matched_keywords=matched,
                    raw_payload={"query": query, "summary": (getattr(entry, "summary", "") or "")[:500]},
                )
            )
        logger.info("News[{}]: {} hits for query {!r}", zone, len(signals), query)
        return signals

    async def fetch_all(self) -> list[NewsRiskSignal]:
        """Concurrent fetch over all keyword/zone queries; failures degrade."""
        import asyncio

        async def _safe(query: str, zone: str, baseline: str):
            try:
                return await self._fetch_query(query, zone, baseline)
            except Exception as exc:
                logger.warning("News fetch failed for {!r} (skipped): {}", query, exc)
                return []

        tasks = [_safe(q, z, b) for (q, z, b) in KEYWORD_ZONE_QUERIES]
        results = await asyncio.gather(*tasks)
        flat: list[NewsRiskSignal] = [s for batch in results for s in batch]

        # De-duplicate by link across overlapping queries.
        seen: set[str] = set()
        deduped: list[NewsRiskSignal] = []
        for s in flat:
            if s.link in seen:
                continue
            seen.add(s.link)
            deduped.append(s)
        logger.info("RSS news total {} (deduped from {})", len(deduped), len(flat))
        return deduped


# =============================================================================
# Synthetic builders — deterministic, network-free demo signals
# =============================================================================

_SYNTH_WEATHER: dict[str, tuple[float, float, float, float]] = {
    "red_sea_bab_el_mandeb": (38.0, 72.0, 3.4, 2.0),
    "baltic_sea": (25.0, 55.0, 2.8, 1.0),
    "taiwan_luzon_strait": (20.0, 40.0, 1.6, 0.5),
    "west_africa_coast": (15.0, 30.0, 1.2, 8.0),
    "malacca_singapore_strait": (10.0, 20.0, 0.8, 0.0),
    "egypt_land_bridge": (12.0, 25.0, 0.5, 0.0),
}
_SYNTH_NEWS: dict[str, list[tuple[str, str]]] = {
    "red_sea_bab_el_mandeb": [
        ("Houthi activity raises risk to Red Sea submarine cables", "high"),
        ("Subsea cable cut reported near Bab-el-Mandeb chokepoint", "critical"),
    ],
    "baltic_sea": [("Anchor drag suspected on Baltic Sea cable route", "high")],
    "taiwan_luzon_strait": [("Taiwan Strait cable degradation under monitoring", "medium")],
    "west_africa_coast": [("West Africa landing station fault under repair", "medium")],
    "malacca_singapore_strait": [("Shipping density watch near Malacca cable crossing", "low")],
    "egypt_land_bridge": [("Egypt land-bridge crossing capacity review", "low")],
}


def make_synthetic_weather(zone: str) -> WeatherRiskSignal:
    wind, gust, wave, precip = _SYNTH_WEATHER.get(zone, (8.0, 15.0, 0.6, 0.0))
    lat, lon = ZONE_SAMPLE_POINTS.get(zone, (0.0, 0.0))
    return WeatherRiskSignal(
        sample_id=uuid4(),
        cable_id=None,
        zone=zone,
        sample_lat=lat,
        sample_lon=lon,
        sampled_at=datetime.now(timezone.utc),
        wind_speed_kmh=wind,
        wind_gust_kmh=gust,
        wave_height_m=wave,
        precipitation_mm=precip,
        weather_fault_probability=compute_weather_probability(wind, gust, wave, precip),
        repair_vessel_delayed=repair_vessel_delayed(wave, gust),
        raw_payload={"source": "demo_synthetic"},
    )


def make_synthetic_news(zone: str) -> list[NewsRiskSignal]:
    items = _SYNTH_NEWS.get(zone, [("Maritime infrastructure watch issued", "low")])
    out: list[NewsRiskSignal] = []
    for idx, (title, severity) in enumerate(items):
        out.append(
            NewsRiskSignal(
                news_id=uuid4(),
                source="demo_synthetic",
                title=title,
                link=f"https://demo.local/news/{zone}/{idx}",
                published_at=datetime.now(timezone.utc),
                zone=zone,
                severity=severity,
                matched_keywords=[k for k in MATCH_KEYWORDS if k in title.lower()],
                raw_payload={"source": "demo_synthetic"},
            )
        )
    return out
