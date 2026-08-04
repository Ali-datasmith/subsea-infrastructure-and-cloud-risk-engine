import asyncio

from src.free_feeds import (
    OpenMeteoClient, RssNewsClient, compute_weather_probability,
    make_synthetic_news, make_synthetic_weather, repair_vessel_delayed,
)
from conftest import FakeResponse, fake_client


def test_weather_probability_bounds():
    assert compute_weather_probability(0, 0, 0, 0) == 0.0
    assert compute_weather_probability(60, 80, 4.0, 6.0) == 1.0


def test_repair_delay_rules():
    assert repair_vessel_delayed(2.6, 10) and repair_vessel_delayed(1.0, 61)
    assert not repair_vessel_delayed(1.0, 30)


def test_synthetic_red_sea_is_stormy():
    w = make_synthetic_weather("red_sea_bab_el_mandeb")
    assert w.repair_vessel_delayed and w.weather_fault_probability > 0.5


def test_synthetic_news_links_unique():
    links = [n.link for z in ["red_sea_bab_el_mandeb", "baltic_sea"] for n in make_synthetic_news(z)]
    assert len(links) == len(set(links))


def test_rss_parse_and_severity(settings, monkeypatch):
    xml = """<rss><channel>
      <item><title>Subsea cable cut near Red Sea chokepoint</title>
      <link>https://e.com/1</link><published>Mon, 03 Aug 2026 07:00:00 GMT</published></item>
      </channel></rss>"""
    monkeypatch.setattr("httpx.AsyncClient",
                        fake_client(lambda url, **kw: FakeResponse(xml)))
    # FakeResponse needs .text for feedparser:
    FakeResponse.text = property(lambda self: self._data)
    sig = asyncio.run(RssNewsClient(settings)._fetch_query("q", "red_sea_bab_el_mandeb", "medium"))
    assert len(sig) == 1
    assert sig[0].severity == "critical"       # "cut" escalates
    assert "cable" in sig[0].matched_keywords


def test_open_meteo_mapping(settings, monkeypatch):
    def handler(url, **kw):
        if "marine-api" in url:
            return FakeResponse({"current": {"wave_height": 2.0}})
        return FakeResponse({"current": {"wind_speed_10m": 30, "wind_gusts_10m": 40,
                                          "precipitation": 6}})
    monkeypatch.setattr("httpx.AsyncClient", fake_client(handler))
    sig = asyncio.run(OpenMeteoClient(settings)._fetch_zone("baltic_sea", 58.5, 20.0))
    assert sig.weather_fault_probability == 0.6   # .15+.15+.10+.20
    assert sig.repair_vessel_delayed is False
