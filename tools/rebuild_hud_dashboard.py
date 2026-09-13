"""Rebuild index.html dashboard shell while preserving the existing JS block."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INDEX = ROOT / "jarvis" / "static" / "index.html"

HEAD = r'''<!DOCTYPE html>
<html lang="es">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>ILARIA</title>
  <link rel="icon" href="/favicon.svg" />
  <style>
    :root {
      --bg-dark-absolute: #070709;
      --bg-panel: #121216;
      --bg-input: #1a1a22;
      --accent-friday: #ff2a54;
      --accent-stark: #00f0ff;
      --text-main: #ffffff;
      --text-muted: #8e8e9f;
      --border-color: rgba(255, 255, 255, 0.06);
      --pink: #ff2a54;
      --blush: #ffe4ef;
      --ok: #00ff66;
      --danger: #ff2a54;
    }
    * { box-sizing: border-box; }
    html, body {
      margin: 0; height: 100%;
      background: var(--bg-dark-absolute);
      color: var(--text-main);
      font-family: "Segoe UI", system-ui, sans-serif;
      overflow: hidden;
    }
    body {
      display: flex;
      justify-content: center;
      align-items: stretch;
      padding: 14px;
      background:
        radial-gradient(ellipse at 70% 30%, rgba(255, 42, 84, 0.08), transparent 45%),
        radial-gradient(circle at 15% 80%, rgba(0, 240, 255, 0.05), transparent 40%),
        var(--bg-dark-absolute);
    }
    .dashboard-container {
      display: grid;
      grid-template-columns: minmax(220px, 280px) minmax(0, 1fr) minmax(220px, 300px);
      gap: 16px;
      width: min(1280px, 100%);
      height: 100%;
      min-height: 0;
    }
    .sidebar-left, .sidebar-right, .main-core {
      background: var(--bg-panel);
      border: 1px solid var(--border-color);
      border-radius: 22px;
      min-height: 0;
      display: flex;
      flex-direction: column;
    }
    .sidebar-left, .sidebar-right { padding: 20px; }
    .brand-header {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 10px;
      margin-bottom: 18px;
    }
    #brand {
      margin: 0;
      font-size: 18px;
      letter-spacing: 0.28em;
      color: var(--accent-friday);
      font-weight: 700;
      text-shadow: 0 0 16px rgba(255, 42, 84, 0.35);
    }
    #live, .status-badge {
      font-size: 10px;
      letter-spacing: 0.14em;
      text-transform: uppercase;
      color: var(--ok);
      background: rgba(0, 255, 102, 0.08);
      border: 1px solid rgba(0, 255, 102, 0.25);
      border-radius: 999px;
      padding: 5px 10px;
      white-space: nowrap;
    }
    #live.busy {
      color: var(--accent-stark);
      background: rgba(0, 240, 255, 0.08);
      border-color: rgba(0, 240, 255, 0.3);
    }
    .nav {
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      margin-bottom: 18px;
    }
    .nav a, .nav button, #histBtn, #histClose, .drawer-bar button {
      background: rgba(255, 255, 255, 0.03);
      color: var(--text-muted);
      border: 1px solid var(--border-color);
      border-radius: 16px;
      padding: 7px 12px;
      font-size: 11px;
      letter-spacing: 0.08em;
      text-transform: uppercase;
      text-decoration: none;
      cursor: pointer;
      transition: 0.2s ease;
    }
    .nav a:hover, .nav button:hover, #histBtn:hover, #histClose:hover {
      color: #fff;
      border-color: rgba(255, 42, 84, 0.4);
      background: rgba(255, 42, 84, 0.12);
    }
    .history-section h3, .widget-box h3 {
      margin: 0 0 12px;
      font-size: 12px;
      color: var(--text-muted);
      text-transform: uppercase;
      letter-spacing: 0.12em;
      font-weight: 600;
    }
    #history {
      flex: 1;
      min-height: 0;
      display: flex;
      flex-direction: column;
      opacity: 1;
      visibility: visible;
      pointer-events: auto;
      transform: none;
      position: static;
      width: auto;
      height: auto;
      background: transparent;
      border: none;
      border-radius: 0;
      box-shadow: none;
    }
    .drawer-bar {
      display: none;
    }
    #log {
      flex: 1;
      overflow-y: auto;
      display: flex;
      flex-direction: column;
      gap: 10px;
      padding-right: 4px;
      min-height: 0;
    }
    .msg {
      max-width: 100%;
      padding: 12px 14px;
      border-radius: 16px;
      font-size: 13px;
      line-height: 1.45;
      white-space: pre-wrap;
    }
    .msg.user {
      align-self: flex-end;
      background: rgba(255, 42, 84, 0.12);
      border: 1px solid rgba(255, 42, 84, 0.22);
      color: #f7e6ec;
      border-bottom-right-radius: 4px;
    }
    .msg.jarvis {
      align-self: flex-start;
      background: rgba(255, 255, 255, 0.03);
      border: 1px solid var(--border-color);
      border-bottom-left-radius: 4px;
    }
    .main-core {
      padding: 28px 28px 22px;
      position: relative;
      overflow: hidden;
      justify-content: space-between;
    }
    .main-core::before {
      content: "";
      position: absolute;
      inset: -40% auto auto 30%;
      width: 420px;
      height: 420px;
      background: radial-gradient(circle, rgba(255, 42, 84, 0.12), transparent 70%);
      pointer-events: none;
    }
    .voice-module {
      flex: 1;
      display: flex;
      flex-direction: column;
      align-items: center;
      justify-content: center;
      gap: 18px;
      position: relative;
      z-index: 1;
      min-height: 0;
    }
    .orb-wrap {
      --voice: 0;
      width: 180px;
      height: 180px;
      position: relative;
      display: grid;
      place-items: center;
      pointer-events: auto;
    }
    .orb-wrap .ring, .orb-wrap .bubble { position: absolute; border-radius: 50%; pointer-events: none; }
    .orb-wrap .ring {
      inset: -4px;
      border: 1px dashed rgba(0, 240, 255, 0.35);
      opacity: 0.5;
      animation: FridaySpin 12s linear infinite;
    }
    .orb-wrap .ring:nth-of-type(2) {
      inset: 14px;
      border-style: solid;
      border-color: rgba(255, 42, 84, 0.22);
      animation-duration: 18s;
      animation-direction: reverse;
    }
    .orb-wrap.thinking .ring, .orb-wrap.speaking .ring, .orb-wrap.listening .ring { opacity: 1; }
    .orb-wrap.thinking .ring:nth-of-type(1) {
      border-color: rgba(0, 240, 255, 0.55);
      animation: FridaySpin 4.2s linear infinite;
    }
    .orb-wrap.thinking .ring:nth-of-type(2) {
      inset: 22px;
      border-color: rgba(255, 42, 84, 0.5);
      animation: FridaySpin 2.8s linear infinite reverse;
    }
    .orb-wrap.speaking .ring {
      inset: 0;
      border-style: solid;
      border-color: rgba(255, 42, 84, 0.55);
      animation: ripple 1.1s ease-out infinite;
    }
    .orb-wrap.speaking .ring:nth-of-type(2) { animation-delay: 0.35s; }
    .orb-wrap .bubble {
      width: 7px; height: 7px;
      background: rgba(0, 240, 255, 0.85);
      opacity: 0;
      box-shadow: 0 0 10px rgba(0, 240, 255, 0.7);
    }
    .orb-wrap.thinking .bubble { opacity: 0.9; }
    .orb-wrap.thinking .b1 { animation: float-bit 3.2s ease-in-out infinite; left: 18px; top: 40px; }
    .orb-wrap.thinking .b2 { animation: float-bit 2.6s ease-in-out 0.4s infinite; right: 22px; top: 28px; width: 5px; height: 5px; background: #ff2a54; }
    .orb-wrap.thinking .b3 { animation: float-bit 3.8s ease-in-out 0.8s infinite; left: 56px; bottom: 18px; background: #ffe4ef; }
    .orb {
      width: 110px; height: 110px; border-radius: 50%; position: relative; z-index: 1;
      background: radial-gradient(circle at 35% 30%, #fff 0%, rgba(255,42,84,0.9) 55%, rgba(255,42,84,0.15) 100%);
      box-shadow: 0 0 30px rgba(255,42,84,0.65), 0 0 70px rgba(255,42,84,0.3), inset 0 0 18px rgba(255,255,255,0.35);
      animation: FridayPulse 2.5s infinite ease-in-out;
      transition: transform 0.28s ease, box-shadow 0.35s ease, filter 0.35s ease;
    }
    .orb::before {
      content: "";
      position: absolute;
      inset: -18px;
      border: 1px dashed rgba(0, 240, 255, 0.4);
      border-radius: 50%;
      animation: FridaySpin 12s linear infinite;
      pointer-events: none;
    }
    .orb::after {
      content: "";
      position: absolute;
      inset: 28px;
      border-radius: 50%;
      border: 1px solid rgba(255,255,255,0.35);
      background: radial-gradient(circle at 40% 35%, rgba(255,255,255,0.55), transparent 70%);
      pointer-events: none;
    }
    .orb-wrap.shy .orb { animation: none; transform: scale(0.86); opacity: 0.75; }
    .orb-wrap.listening .orb {
      animation: none;
      transform: scale(calc(0.92 + var(--voice, 0) * 0.28));
      box-shadow: 0 0 34px rgba(0,240,255,0.4), 0 0 60px rgba(255,42,84,0.5), inset 0 0 18px rgba(255,255,255,0.4);
    }
    .orb-wrap.thinking .orb { animation: FridayPulse 1.4s infinite ease-in-out; }
    .orb-wrap.speaking .orb {
      animation: speak-joy 0.85s ease-in-out infinite;
      box-shadow: 0 0 40px rgba(255,42,84,0.85), 0 0 80px rgba(255,42,84,0.4);
    }
    .orb-wrap.mood-sad .orb { transform: translateY(8px) scale(0.96); animation: sad-pulse 3.2s ease-in-out infinite; }
    .orb-wrap.mood-scare .orb { animation: shiver 0.28s linear 4; }
    .orb-wrap.tickle .orb { animation: tickle 0.45s ease; }
    .orb-wrap.mood-happy:not(.listening):not(.thinking):not(.speaking) .orb {
      animation: hop-in 0.7s ease, FridayPulse 2.5s ease-in-out 0.7s infinite;
    }
    #waveform {
      display: flex;
      align-items: flex-end;
      justify-content: center;
      gap: 6px;
      height: 48px;
      opacity: 0.35;
      transition: opacity 0.25s ease;
    }
    #waveform.active { opacity: 1; }
    #waveform.hot .wave-bar { background: var(--accent-friday); }
    .wave-bar {
      width: 4px;
      height: 14px;
      background: var(--accent-stark);
      border-radius: 2px;
      animation: soundWavePulse 1.2s infinite ease-in-out;
      transform-origin: center bottom;
    }
    .wave-bar:nth-child(2) { animation-delay: 0.15s; }
    .wave-bar:nth-child(3) { animation-delay: 0.3s; }
    .wave-bar:nth-child(4) { animation-delay: 0.1s; }
    .wave-bar:nth-child(5) { animation-delay: 0.25s; }
    .wave-bar:nth-child(6) { animation-delay: 0.35s; }
    .wave-bar:nth-child(7) { animation-delay: 0.05s; }
    #caption {
      max-width: min(520px, 92%);
      text-align: center;
      padding: 12px 18px;
      border-radius: 16px;
      background: rgba(255,255,255,0.03);
      border: 1px solid var(--border-color);
      color: var(--blush);
      font-size: 15px;
      line-height: 1.4;
      white-space: pre-wrap;
      opacity: 0;
      transform: translateY(8px);
      transition: opacity 0.35s ease, transform 0.35s ease;
      pointer-events: none;
    }
    #caption.show { opacity: 1; transform: none; }
    #caption.user-line { color: #f7e6ec; }
    form#form {
      position: relative;
      left: auto; right: auto; bottom: auto;
      z-index: 2;
      display: flex;
      align-items: center;
      gap: 10px;
      background: var(--bg-input);
      border: 1px solid rgba(255,255,255,0.04);
      border-radius: 28px;
      padding: 8px 12px;
      margin-top: 12px;
    }
    form#form input[type=text] {
      flex: 1;
      background: transparent;
      border: none;
      color: var(--text-main);
      outline: none;
      font-size: 15px;
      padding: 10px 6px;
    }
    form#form input[type=text]::placeholder { color: var(--text-muted); }
    form#form > button[type=submit] {
      background: var(--accent-friday);
      color: #fff;
      border: none;
      border-radius: 20px;
      padding: 8px 18px;
      font-weight: 700;
      cursor: pointer;
    }
    form#form > button[type=submit]:hover {
      box-shadow: 0 0 16px rgba(255, 42, 84, 0.45);
    }
    button.mic {
      background: transparent;
      color: var(--text-muted);
      border: 1px solid var(--border-color);
      border-radius: 18px;
      min-width: 52px;
      padding: 8px 12px;
      font-weight: 600;
      cursor: pointer;
    }
    button.mic:hover { color: var(--accent-stark); border-color: rgba(0,240,255,0.35); }
    button.mic.hot {
      color: #fff;
      background: rgba(255, 42, 84, 0.35);
      border-color: rgba(255, 42, 84, 0.7);
      box-shadow: 0 0 14px rgba(255, 42, 84, 0.45);
      animation: pulse 1.5s infinite;
    }
    .widget-box {
      background: rgba(255,255,255,0.02);
      border: 1px solid var(--border-color);
      border-radius: 18px;
      padding: 16px;
      margin-bottom: 14px;
    }
    .metric-row {
      display: flex;
      justify-content: space-between;
      gap: 12px;
      padding: 10px 0;
      border-bottom: 1px solid rgba(255,255,255,0.03);
      font-size: 13px;
      color: var(--text-muted);
    }
    .metric-row:last-child { border-bottom: none; }
    .metric-row strong { color: var(--text-main); font-weight: 600; }
    .text-green { color: var(--ok) !important; }
    .text-warn { color: #ffb020 !important; }
    #histBtn {
      display: none;
      position: fixed;
      right: 18px;
      bottom: 18px;
      z-index: 20;
    }
    @keyframes FridayPulse {
      0% { transform: scale(0.96); opacity: 0.88; }
      50% { transform: scale(1.03); opacity: 1; box-shadow: 0 0 40px rgba(255,42,84,0.8), 0 0 80px rgba(255,42,84,0.4); }
      100% { transform: scale(0.96); opacity: 0.88; }
    }
    @keyframes FridaySpin { to { transform: rotate(360deg); } }
    @keyframes ripple {
      0% { transform: scale(0.92); opacity: 0.7; }
      100% { transform: scale(1.28); opacity: 0; }
    }
    @keyframes float-bit {
      0%, 100% { transform: translateY(0); }
      50% { transform: translateY(-14px); }
    }
    @keyframes speak-joy {
      0%, 100% { transform: scale(1.04); }
      50% { transform: scale(1.12); }
    }
    @keyframes sad-pulse {
      0%, 100% { transform: translateY(8px) scale(0.96); filter: brightness(0.9); }
      50% { transform: translateY(10px) scale(0.94); filter: brightness(0.82); }
    }
    @keyframes shiver {
      0%, 100% { transform: translateX(0); }
      25% { transform: translateX(-4px); }
      75% { transform: translateX(4px); }
    }
    @keyframes tickle {
      0% { transform: scale(1); }
      40% { transform: scale(1.16); }
      100% { transform: scale(1); }
    }
    @keyframes hop-in {
      0% { transform: translateY(12px) scale(0.9); }
      60% { transform: translateY(-14px) scale(1.06); }
      100% { transform: translateY(0) scale(1); }
    }
    @keyframes soundWavePulse {
      0%, 100% { transform: scaleY(0.45); }
      50% { transform: scaleY(1.15); }
    }
    @keyframes pulse {
      0%, 100% { opacity: 1; }
      50% { opacity: 0.55; }
    }
    @media (max-width: 980px) {
      body { padding: 8px; }
      .dashboard-container {
        grid-template-columns: 1fr;
        grid-template-rows: auto 1fr auto;
        overflow: auto;
        height: auto;
        min-height: 100%;
      }
      .sidebar-right { order: 3; }
      .main-core { order: 1; min-height: 62vh; }
      .sidebar-left { order: 2; max-height: 40vh; }
      #histBtn { display: inline-flex; align-items: center; justify-content: center; }
      #history:not(.open) #log { display: none; }
    }
  </style>
</head>
<body>
  <div class="dashboard-container">
    <aside class="sidebar-left">
      <div class="brand-header">
        <h2 id="brand">ILARIA</h2>
        <div id="live" class="status-badge">En línea</div>
      </div>
      <div class="nav">
        <a href="/admin" id="adminLink" hidden>Dueño</a>
        <a href="/settings">Perfil</a>
        <button type="button" id="out">Salir</button>
        <button type="button" id="histClose" title="Colapsar historial">Hist</button>
      </div>
      <div class="history-section" style="flex:1;min-height:0;display:flex;flex-direction:column;">
        <h3>Historial táctico</h3>
        <aside id="history" class="open" aria-hidden="false">
          <div class="drawer-bar"><span>Historial</span></div>
          <div id="log"></div>
        </aside>
      </div>
    </aside>

    <main class="main-core">
      <div class="voice-module">
        <div class="orb-wrap mood-happy" id="orb" aria-hidden="true">
          <span class="ring"></span>
          <span class="ring"></span>
          <span class="bubble b1"></span>
          <span class="bubble b2"></span>
          <span class="bubble b3"></span>
          <div class="orb"></div>
        </div>
        <div class="waveform-container" id="waveform" aria-hidden="true">
          <span class="wave-bar"></span>
          <span class="wave-bar"></span>
          <span class="wave-bar"></span>
          <span class="wave-bar"></span>
          <span class="wave-bar"></span>
          <span class="wave-bar"></span>
          <span class="wave-bar"></span>
        </div>
        <div id="caption" class="" aria-live="polite"></div>
      </div>
      <form id="form">
        <button type="button" class="mic" id="mic" title="Hablar">Mic</button>
        <button type="button" class="mic hot" id="free" title="Siempre oye; solo responde si decís Ilaria">Oír</button>
        <input id="q" type="text" autocomplete="off" placeholder="Escribí una orden para F.R.I.D.A.Y.…" />
        <button type="submit">OK</button>
        <audio id="voice" style="display:none" preload="none"></audio>
      </form>
    </main>

    <aside class="sidebar-right">
      <div class="widget-box">
        <h3>Estado de la PC</h3>
        <div class="metric-row"><span>Ollama LLM</span><strong class="text-green" id="metric-ollama">—</strong></div>
        <div class="metric-row"><span>Puerto HUD</span><strong id="metric-port">—</strong></div>
        <div class="metric-row"><span>Voz</span><strong id="metric-tts">—</strong></div>
        <div class="metric-row"><span>Versión</span><strong id="metric-version">—</strong></div>
      </div>
      <div class="widget-box">
        <h3>Dispositivo móvil</h3>
        <div class="metric-row"><span>Android min</span><strong id="metric-android">—</strong></div>
        <div class="metric-row"><span>Canal PC</span><span id="queue-count">local-first</span></div>
      </div>
    </aside>
  </div>
  <button type="button" id="histBtn" title="Historial (Ctrl+H)">Hist</button>
'''

TAIL_PATCHES = [
    (
        """    function setOrb(mode) {
      orb.classList.remove("thinking", "speaking", "listening", "shy", "tickle");
      if (mode === "thinking") {
        orb.classList.add("thinking", "mood-think");
        orb.classList.remove("mood-happy", "mood-sad", "mood-scare");
      } else if (mode === "speaking") {
        orb.classList.add("speaking", "mood-happy");
        orb.classList.remove("mood-think", "mood-sad", "mood-scare");
      } else if (mode === "listening") {
        orb.classList.add("shy");
        setTimeout(function () {
          orb.classList.remove("shy");
          if (!busy && !speaking) orb.classList.add("listening");
        }, 240);
      }
    }""",
        """    const waveform = document.getElementById("waveform");
    function syncWave() {
      if (!waveform) return;
      const on = orb.classList.contains("listening") || orb.classList.contains("speaking") || orb.classList.contains("thinking");
      waveform.classList.toggle("active", on);
      waveform.classList.toggle("hot", orb.classList.contains("listening") || mic.classList.contains("hot"));
    }
    function setOrb(mode) {
      orb.classList.remove("thinking", "speaking", "listening", "shy", "tickle");
      if (mode === "thinking") {
        orb.classList.add("thinking", "mood-think");
        orb.classList.remove("mood-happy", "mood-sad", "mood-scare");
      } else if (mode === "speaking") {
        orb.classList.add("speaking", "mood-happy");
        orb.classList.remove("mood-think", "mood-sad", "mood-scare");
      } else if (mode === "listening") {
        orb.classList.add("shy");
        setTimeout(function () {
          orb.classList.remove("shy");
          if (!busy && !speaking) orb.classList.add("listening");
          syncWave();
        }, 240);
      }
      syncWave();
    }""",
    ),
    (
        """        orb.style.setProperty("--voice", Math.min(1, level / 0.12).toFixed(3));""",
        """        orb.style.setProperty("--voice", Math.min(1, level / 0.12).toFixed(3));
        if (waveform) {
          const bars = waveform.querySelectorAll(".wave-bar");
          const v = Math.min(1, level / 0.1);
          bars.forEach((bar, i) => {
            bar.style.height = (8 + v * (18 + (i % 3) * 10)).toFixed(1) + "px";
          });
        }""",
    ),
    (
        """    setInterval(pollAlerts, 4000);
  </script>""",
        """    setInterval(pollAlerts, 4000);

    async function refreshMetrics() {
      const ollamaEl = document.getElementById("metric-ollama");
      const ttsEl = document.getElementById("metric-tts");
      const portEl = document.getElementById("metric-port");
      const verEl = document.getElementById("metric-version");
      try {
        const h = await fetch("/health").then((r) => r.json());
        if (portEl) portEl.textContent = "Activo";
        if (ttsEl) ttsEl.textContent = (h.tts || "local").toUpperCase();
        if (verEl) verEl.textContent = "v" + (h.version || "?");
      } catch (e) {
        if (portEl) portEl.textContent = "Caído";
      }
      try {
        const me = await fetch("/api/me").then((r) => r.json());
        if (ollamaEl) {
          ollamaEl.textContent = me.has_llm ? "OK" : "OFF";
          ollamaEl.className = me.has_llm ? "text-green" : "text-warn";
        }
      } catch (e) {}
      try {
        const meta = await fetch("/api/meta").then((r) => r.json());
        const andEl = document.getElementById("metric-android");
        if (andEl) andEl.textContent = meta.min_required_android_client
          ? ("min " + meta.min_required_android_client)
          : "—";
      } catch (e) {}
    }
    refreshMetrics();
    setInterval(refreshMetrics, 12000);
  </script>""",
    ),
]


def main() -> None:
    original = INDEX.read_text(encoding="utf-8")
    start = original.find("  <script>")
    if start < 0:
        raise SystemExit("script block missing")
    script = original[start:]
    for old, new in TAIL_PATCHES:
        if old not in script:
            raise SystemExit(f"patch failed: {old[:48]!r}")
        script = script.replace(old, new, 1)
    INDEX.write_text(HEAD + "\n" + script, encoding="utf-8")
    print(f"OK wrote {INDEX} ({INDEX.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
