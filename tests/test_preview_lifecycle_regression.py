"""Real subprocess regression for preview lifetime at the CLI boundary."""

import json
import http.server
import os
import socket
import subprocess
import sys
import threading
from pathlib import Path

from kinocut.hyperframes_engine import _preview_ready, release_preview
import pytest


def test_readiness_rejects_other_process_and_project(tmp_path):
    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.end_headers()
            self.wfile.write(json.dumps({"isHyperframes": True, "pid": 42, "projectDir": str(tmp_path)}).encode())

    server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        port = server.server_port
        assert _preview_ready(port, tmp_path, 42)
        assert not _preview_ready(port, tmp_path, 43)
        assert not _preview_ready(port, tmp_path / "other", 42)
        with pytest.raises(RuntimeError):
            release_preview(port, 42)
    finally:
        server.shutdown()
        thread.join()
        server.server_close()


def test_preview_cli_keeps_the_reported_owned_server_alive(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    (project / "index.html").write_text('<div data-composition-id="main"></div>')
    cli = tmp_path / "hyperframes"
    cli.write_text(
        f"#!{sys.executable}\n"
        "import http.server, json, os, sys\n"
        "if '--version' in sys.argv: print('0.8.140'); sys.exit(0)\n"
        "port=int(sys.argv[sys.argv.index('--port')+1]); project=sys.argv[2]\n"
        "class Handler(http.server.BaseHTTPRequestHandler):\n"
        " def do_GET(self):\n"
        "  data=json.dumps({'isHyperframes':True,'projectDir':project,'pid':os.getpid()}).encode()\n"
        "  self.send_response(200); self.end_headers(); self.wfile.write(data)\n"
        "http.server.HTTPServer(('127.0.0.1',port),Handler).serve_forever()\n"
    )
    cli.chmod(0o755)
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    env = os.environ.copy()
    env.update(MCP_VIDEO_HYPERFRAMES_COMMAND=str(cli), KINOCUT_HYPERFRAMES_TELEMETRY="false")
    result = subprocess.run(
        [sys.executable, "-m", "kinocut", "--format", "json", "hyperframes-preview", str(project), "--port", str(port)],
        env=env,
        text=True,
        capture_output=True,
        timeout=20,
    )
    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout)
    try:
        with socket.socket() as s:
            assert s.connect_ex(("127.0.0.1", port)) == 0
        assert data["port"] == port
    finally:
        pid = data.get("pid")
        if isinstance(pid, int):
            try:
                # PID must still identify our fake executable, never an unrelated process.
                cmdline = Path(f"/proc/{pid}/cmdline").read_bytes()
                if str(cli).encode() in cmdline:
                    os.kill(pid, 15)
            except ProcessLookupError:
                pass
            except FileNotFoundError:
                pass
