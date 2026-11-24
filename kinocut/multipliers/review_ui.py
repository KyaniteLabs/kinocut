"""Minimal human review surface HTML (P4.3)."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from ..errors import MCPVideoError
from ..ffmpeg_helpers import _atomic_artifact, _open_staged_writer, _validate_artifact_location, _validate_artifact_path

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
    function safeFilename(value) {
      return value && /^[a-z0-9]/i.test(value) && !/[^a-z0-9._-]/i.test(value) ? value : null;
    }
    const timelineUrl = safeFilename(params.get('timeline')) || __DEFAULT_TIMELINE__;
    const mediaUrl = safeFilename(params.get('media'));
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
    if not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9._-]*", timeline_name):
        raise MCPVideoError(
            "Expected a relative timeline filename", error_type="validation_error", code="invalid_parameter"
        )
    _validate_artifact_location(str(root), "Review directory")
    html_path = root / "review.html"
    payload = _HTML.replace("__DEFAULT_TIMELINE__", json.dumps(timeline_name)).encode("utf-8")
    with _atomic_artifact(_validate_artifact_path(str(html_path))) as staged, _open_staged_writer(staged) as stream:
        stream.write(payload)
    return {
        "artifact_kind": "review_surface",
        "html_path": str(html_path.resolve()),
        "timeline_filename": timeline_name,
        "hot_reload_ms": 2000,
        "notes": "Open review.html next to the timeline file; polls every 2s.",
    }
