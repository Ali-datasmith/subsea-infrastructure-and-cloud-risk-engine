"""
Pass C — "Deep Ocean & Electric Cyan" glassmorphic command-center theme.

PURE visual layer. No data, no DB, no LLM logic lives here, so it cannot
regress the working engine.
- THEME_CSS is injected via st.markdown(unsafe_allow_html=True). Streamlit KEEPS
  <style> (it strips <script>), so all glass + keyframe effects render on Cloud.
  backdrop-filter / Google Fonts degrade gracefully (tinted cards + system fonts)
  if a sandbox blocks them — never a crash.
- The "alive" feel (pulsing LEDs, breathing LIVE badge, scan sweep, marquee
  ticker) is 100% CSS keyframes -> reliable.
- The audio chime is a self-contained Web-Audio component (components.v1.html),
  gated behind a sidebar toggle and played on a real click gesture -> guaranteed
  to sound (auto server-pushed beeps are not reliable in Streamlit's model).

All HTML builders emit only classed tags + html.escape()d text (no inline CSS
braces), so there are no f-string / CSS-brace collisions.
"""
from __future__ import annotations

import html
from typing import Iterable

import streamlit as st
import streamlit.components.v1 as components

# =============================================================================
# Design tokens — Deep Ocean & Electric Cyan
# =============================================================================
THEME_CSS = """
@import url('https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@500;600;700&family=JetBrains+Mono:wght@400;500;700&family=Sora:wght@300;400;600&display=swap');

:root{
  --bg:#050c1a; --bg2:#0a192f;
  --glass:rgba(16,28,48,0.55); --glass-2:rgba(10,25,47,0.66);
  --glass-border:rgba(0,242,254,0.18); --glass-border-soft:rgba(255,255,255,0.08);
  --cyan:#00f2fe; --blue:#4facfe; --purple:#bd00ff;
  --amber:#ffbe0b; --red:#ff2e63;
  --text:#e6f1ff; --muted:#8aa0b8;
  --glow:0 8px 32px 0 rgba(0,242,254,0.15);
  --fh:'Space Grotesk',system-ui,sans-serif;
  --fm:'JetBrains Mono',ui-monospace,monospace;
  --fb:'Sora',system-ui,sans-serif;
}

/* deep-navy field with soft neon blooms (matches the reference image) */
html,body,.stApp{background:var(--bg)!important;color:var(--text);}
[data-testid="stAppViewContainer"]{
  background:
    radial-gradient(60% 50% at 18% 12%, rgba(0,242,254,0.12), transparent 60%),
    radial-gradient(52% 46% at 86% 22%, rgba(189,0,255,0.12), transparent 62%),
    radial-gradient(58% 52% at 62% 92%, rgba(79,172,254,0.12), transparent 60%),
    var(--bg) !important;
  background-attachment:fixed;
}
section.main,.block-container,[data-testid="stMainBlockContainer"],
[data-testid="stAppViewBlockContainer"]{background:transparent!important;}
.block-container{padding-top:2.2rem!important;}

p,li,span,label,.stMarkdown{color:var(--text);}
.stCaption,[data-testid="stCaptionContainer"]{color:var(--muted)!important;}
a{color:var(--cyan)!important;}

/* typography */
h1,h2,h3,.hero-title,.stMarkdown h1,.stMarkdown h2,.stMarkdown h3{
  font-family:var(--fh)!important;letter-spacing:.2px;
  color:#eaf6ff!important;text-shadow:0 0 18px rgba(0,242,254,0.35);
}
.stMarkdown p,.stMarkdown li{font-family:var(--fb)!important;line-height:1.6;}

/* glass primitive */
.glass,[data-testid="stMetric"],[data-testid="stExpander"] details,
[data-testid="stSidebar"]>div{
  background:var(--glass)!important;
  border:1px solid var(--glass-border)!important;
  border-radius:16px!important;
  backdrop-filter:blur(12px) saturate(160%)!important;
  -webkit-backdrop-filter:blur(12px) saturate(160%)!important;
  box-shadow:var(--glow)!important;
}
[data-testid="stMetric"]{padding:16px 18px!important;}
[data-testid="stMetric"] [data-testid="stMetricValue"]{
  font-family:var(--fm)!important;color:var(--cyan)!important;
  text-shadow:0 0 14px rgba(0,242,254,0.5);
}
[data-testid="stMetric"] [data-testid="stMetricLabel"]{
  font-family:var(--fh)!important;text-transform:uppercase;
  letter-spacing:1.4px;font-size:.68rem;color:var(--muted)!important;
}

/* sidebar */
[data-testid="stSidebar"]{
  background:linear-gradient(180deg,rgba(10,25,47,0.82),rgba(5,12,26,0.92))!important;
  border-right:1px solid var(--glass-border)!important;
  backdrop-filter:blur(14px) saturate(160%)!important;
}
[data-testid="stSidebar"] [data-testid="stMarkdownContainer"] p,
[data-testid="stSidebar"] span{font-family:var(--fb)!important;}
[data-testid="stSidebarNav"] a{font-family:var(--fh)!important;border-radius:10px;}
[data-testid="stSidebarNav"] a[aria-current="page"]{
  background:rgba(0,242,254,0.10)!important;color:var(--cyan)!important;
  box-shadow:inset 2px 0 0 var(--cyan);
}

/* buttons */
.stButton>button,[data-testid^="stBaseButton"]{
  font-family:var(--fh)!important;border-radius:12px!important;
  background:var(--glass-2)!important;color:var(--text)!important;
  border:1px solid var(--glass-border)!important;
  transition:transform .15s ease, box-shadow .2s ease, border-color .2s ease;
}
.stButton>button:hover,[data-testid^="stBaseButton"]:hover{
  transform:translateY(-1px);border-color:var(--cyan)!important;
  box-shadow:0 0 18px rgba(0,242,254,0.35)!important;
}
[data-testid="stBaseButton-primary"],.stButton>button[kind="primary"]{
  background:linear-gradient(120deg,rgba(0,242,254,0.22),rgba(79,172,254,0.22))!important;
  border-color:rgba(0,242,254,0.55)!important;color:#eafcff!important;
  box-shadow:0 0 22px rgba(0,242,254,0.30)!important;
}

/* inputs / sliders / checkboxes */
[data-testid="stTextInput"] input,[data-testid="stTextArea"] textarea,
[data-testid="stNumberInput"] input{
  background:rgba(8,18,38,0.7)!important;color:var(--text)!important;
  border:1px solid var(--glass-border-soft)!important;border-radius:10px!important;
}
[data-testid="stTextInput"] input:focus,[data-testid="stTextArea"] textarea:focus{
  border-color:var(--cyan)!important;box-shadow:0 0 0 2px rgba(0,242,254,0.18)!important;
}
input[type="range"],input[type="checkbox"]{accent-color:var(--cyan)!important;}

/* alerts / tables / code */
[data-testid="stAlert"]{
  background:var(--glass)!important;border:1px solid var(--glass-border)!important;
  border-left:3px solid var(--cyan)!important;border-radius:12px!important;
  backdrop-filter:blur(10px)!important;
}
[data-testid="stDataFrame"],[data-testid="stTable"]{
  border:1px solid var(--glass-border)!important;border-radius:14px!important;
  box-shadow:var(--glow)!important;overflow:hidden;
}
.stTabs [data-testid="stTab"]{font-family:var(--fh)!important;color:var(--muted)!important;}
.stTabs [aria-selected="true"]{color:var(--cyan)!important;text-shadow:0 0 10px rgba(0,242,254,.5);}
pre,.stCodeBlock,[data-testid="stCode"]{
  background:rgba(5,12,26,0.85)!important;border:1px solid var(--glass-border-soft)!important;
  border-radius:12px!important;
}

/* map + audio iframes get a glowing cyan bezel that blends into the field */
section.main iframe{
  border:1px solid rgba(0,242,254,0.28)!important;border-radius:16px!important;
  box-shadow:0 8px 32px rgba(0,242,254,0.18)!important;background:#050c1a!important;
}

/* ===================== living layer (pure CSS) ===================== */
.hero{position:relative;overflow:hidden;padding:26px 30px;margin:6px 0 18px;
  background:var(--glass);border:1px solid var(--glass-border);border-radius:20px;
  backdrop-filter:blur(14px) saturate(160%);-webkit-backdrop-filter:blur(14px) saturate(160%);
  box-shadow:var(--glow);}
.hero-row{display:flex;align-items:center;justify-content:space-between;gap:16px;flex-wrap:wrap;}
.hero-title{margin:0!important;font-size:clamp(26px,3.6vw,44px)!important;}
.hero-sub{margin:10px 0 0!important;color:var(--muted)!important;font-family:var(--fb)!important;}
.scanline{position:absolute;left:0;right:0;height:2px;top:0;opacity:.5;pointer-events:none;
  background:linear-gradient(90deg,transparent,var(--cyan),transparent);animation:scan 3.4s linear infinite;}
@keyframes scan{0%{top:0}100%{top:100%}}

.live-badge{display:inline-flex;align-items:center;gap:8px;padding:6px 14px;border-radius:999px;
  font-family:var(--fm)!important;font-size:.72rem;letter-spacing:2px;color:var(--cyan);
  border:1px solid rgba(0,242,254,0.4);background:rgba(0,242,254,0.08);animation:breathe 2.4s ease-in-out infinite;}
.live-dot{width:8px;height:8px;border-radius:50%;background:var(--cyan);box-shadow:0 0 10px var(--cyan);
  animation:ledpulse 1.4s infinite;}
@keyframes breathe{0%,100%{box-shadow:0 0 8px rgba(0,242,254,.4)}50%{box-shadow:0 0 22px rgba(0,242,254,.9)}}

.led-strip{display:flex;flex-wrap:wrap;gap:18px;margin:4px 0 16px;padding:10px 16px;
  background:var(--glass);border:1px solid var(--glass-border-soft);border-radius:14px;
  backdrop-filter:blur(10px);font-family:var(--fm)!important;font-size:.72rem;color:var(--muted);}
.led-item{display:inline-flex;align-items:center;gap:7px;text-transform:uppercase;letter-spacing:1px;}
.led{width:9px;height:9px;border-radius:50%;display:inline-block;}
.led.ok{background:var(--cyan);box-shadow:0 0 8px var(--cyan);animation:ledpulse 1.8s infinite;}
.led.warn{background:var(--amber);box-shadow:0 0 8px var(--amber);animation:ledblink 1.1s steps(2,start) infinite;}
.led.crit{background:var(--red);box-shadow:0 0 10px var(--red);animation:ledblink .5s steps(2,start) infinite;}
.led.off{background:#33445e;box-shadow:none;}
@keyframes ledpulse{0%,100%{opacity:1}50%{opacity:.45}}
@keyframes ledblink{0%,100%{opacity:1}50%{opacity:.2}}

.ticker{overflow:hidden;white-space:nowrap;margin:0 0 14px;padding:8px 0;
  border-top:1px solid var(--glass-border-soft);border-bottom:1px solid var(--glass-border-soft);
  background:rgba(5,12,26,0.4);border-radius:10px;font-family:var(--fm)!important;
  font-size:.74rem;color:var(--cyan);letter-spacing:.5px;}
.ticker-track{display:inline-block;padding-left:100%;animation:marquee 26s linear infinite;}
.ticker-track:hover{animation-play-state:paused;}
@keyframes marquee{0%{transform:translateX(0)}100%{transform:translateX(-100%)}}
"""

# =============================================================================
# HTML builders (classed tags + escaped text only — no inline CSS braces)
# =============================================================================

def live_badge_html() -> str:
    return '<span class="live-badge"><span class="live-dot"></span>LIVE</span>'


def hero_html(title: str, subtitle: str = "") -> str:
    t = html.escape(title)
    s = html.escape(subtitle)
    sub = f'<p class="hero-sub">{s}</p>' if s else ""
    return (
        '<div class="hero"><div class="scanline"></div>'
        f'<div class="hero-row"><h1 class="hero-title">{t}</h1>{live_badge_html()}</div>'
        f'{sub}</div>'
    )


def led_strip_html(items: Iterable[tuple[str, str]]) -> str:
    """items: iterable of (label, state) where state in {ok, warn, crit, off}."""
    cells = []
    for label, state in items:
        st_safe = state if state in ("ok", "warn", "crit", "off") else "off"
        cells.append(
            f'<span class="led-item"><span class="led {st_safe}"></span>{html.escape(label)}</span>'
        )
    return '<div class="led-strip">' + "".join(cells) + "</div>"


def ticker_html(items: Iterable[str]) -> str:
    seq = [html.escape(x) for x in items if x]
    if not seq:
        seq = ["ALL CHANNELS NOMINAL", "ENGINE ONLINE", "AWAITING TELEMETRY"]
    track = "&nbsp;&nbsp;•&nbsp;&nbsp;".join(seq)
    return f'<div class="ticker"><div class="ticker-track">{track}</div></div>'


# =============================================================================
# Audio chime — self-contained Web Audio component (plays on a real click)
# =============================================================================
_AUDIO_HTML = """
<div style="font-family:'JetBrains Mono',monospace;display:flex;align-items:center;gap:12px;
 background:rgba(16,28,48,0.6);border:1px solid rgba(0,242,254,0.25);border-radius:12px;
 padding:8px 14px;color:#9fb3c8;font-size:12px;backdrop-filter:blur(8px)">
  <span style="color:#00f2fe;font-size:15px">&#128276;</span>
  <span>Alert chime</span>
  <button id="chime" style="margin-left:auto;cursor:pointer;border:1px solid rgba(0,242,254,0.45);
   background:rgba(0,242,254,0.10);color:#00f2fe;border-radius:8px;padding:5px 14px;
   font-family:inherit;font-size:12px;letter-spacing:1px">&#9654; TEST</button>
  <span id="chst" style="opacity:.6">click to arm &amp; play</span>
</div>
<script>
(function(){
  var ctx=null;
  function blip(freq,start,dur,peak){
    var o=ctx.createOscillator(), g=ctx.createGain();
    o.type='sine'; o.frequency.value=freq; o.connect(g); g.connect(ctx.destination);
    var t=ctx.currentTime+start;
    g.gain.setValueAtTime(0.0001,t);
    g.gain.exponentialRampToValueAtTime(peak,t+0.02);
    g.gain.exponentialRampToValueAtTime(0.0001,t+dur);
    o.start(t); o.stop(t+dur+0.02);
  }
  function chime(){
    try{
      ctx = ctx || new (window.AudioContext||window.webkitAudioContext)();
      if(ctx.state==='suspended'){ctx.resume();}
      blip(880,0.0,0.45,0.25); blip(1320,0.12,0.4,0.20);
      var s=document.getElementById('chst'); if(s){s.textContent='chime ✓ armed';}
    }catch(e){var s2=document.getElementById('chst'); if(s2){s2.textContent='audio blocked';}}
  }
  var b=document.getElementById('chime');
  if(b){b.addEventListener('click',chime);}
})();
</script>
"""


def render_alert_chime_control() -> None:
    """Sidebar toggle (default OFF); when ON, render the click-to-play chime."""
    armed = st.sidebar.toggle("🔔 Alert chime", value=False, key="alert_chime_toggle")
    if armed:
        components.html(_AUDIO_HTML, height=58, scrolling=False)


# =============================================================================
# One-call injector
# =============================================================================
def inject_theme() -> None:
    """Inject the glass CSS. Call once per page, right after set_page_config."""
    st.markdown(THEME_CSS, unsafe_allow_html=True)
