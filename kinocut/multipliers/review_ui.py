"""Minimal human review surface HTML (P4.3)."""

from __future__ import annotations

from pathlib import Path
from typing import Any


_HTML = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8"/>
  <title>Kinocut review surface</title>
  <style>
    body { font-family: ui-monospace, monospace; background:#0b0d10; color:#e8eaed; margin:1.5rem; }
    h1 { font-size:1.1rem; }
    #status { color:#9aa0a6; }
    pre { background:#151920; padding:1rem; overflow:auto; border:1px solid #2a2f3a; }
    video { max-width:100%; margin-top:1rem; background:#000; }
  </style>
</head>
<body>
  <h1>Kinocut human review surface</h1>
  <p id="status">Loading timeline…</p>
  <video id="player" controls></video>
  <pre id="out">{}</pre>
  <script>
    const params = new URLSearchParams(location.search);
    const timelineUrl = params.get('timeline') || 'timeline.json';
    const mediaUrl = params.get('media') || '';
    const status = document.getElementById('status');
    const out = document.getElementById('out');
    const player = document.getElementById('player');
    if (mediaUrl) player.src = mediaUrl;
    async function load() {
      try {
        const res = await fetch(timelineUrl + '?t=' + Date.now(), {cache:'no-store'});
        const data = await res.json();
        out.textContent = JSON.stringify(data, null, 2);
        status.textContent = 'Loaded ' + timelineUrl + ' @ ' + new Date().toISOString();
      } catch (e) {
        status.textContent = 'Failed to load timeline: ' + e;
      }
    }
    load();
    setInterval(load, 2000); // hot-reload poll
  </script>
</body>
</html>
"""


def write_review_surface(output_dir: str, *, timeline_name: str = "timeline.json") -> dict[str, Any]:
    """Write a static hot-reloading review HTML page into output_dir."""
    root = Path(output_dir)
    root.mkdir(parents=True, exist_ok=True)
    html_path = root / "review.html"
    html_path.write_text(_HTML, encoding="utf-8")
    return {
        "artifact_kind": "review_surface",
        "html_path": str(html_path.resolve()),
        "timeline_filename": timeline_name,
        "hot_reload_ms": 2000,
        "notes": "Open review.html next to timeline.json; polls every 2s.",
    }
