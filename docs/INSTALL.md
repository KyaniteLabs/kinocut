# Install matrix

**Published package:** see [`public_claims.json`](public_claims.json) (`published_version`).  
**Prerequisite:** [FFmpeg](https://ffmpeg.org/) on `PATH`.

## OS package managers

| OS | FFmpeg |
| --- | --- |
| macOS | `brew install ffmpeg` |
| Ubuntu/Debian | `sudo apt install ffmpeg` |
| Windows | Install a build with `ffmpeg` on PATH (e.g. winget/chocolatey/scoop or official builds) |

## Kinocut package

| Goal | Command |
| --- | --- |
| Stable publish | `pip install kinocut` |
| Upgrade | `pip install -U kinocut` |
| From former name | `pip install -U mcp-video` (shim → current Kinocut) |
| Editable clone | `pip install -e .` from repo root |
| No global install | `uvx --from kinocut kino doctor` |

## Verify (doctor-first)

```bash
kino doctor
# or
kino doctor --json
```

**Pass:** `summary.required_ok == true` (or text status without missing required items).  
Optional AI extras can be missing for core editing.

Then prove plumbing:

```bash
python scripts/golden_path.py   # from a clone
```

## MCP hosts

### Claude Code

```bash
claude mcp add kinocut -- uvx --from kinocut kino
```

### Cursor / generic stdio JSON

```json
{
  "mcpServers": {
    "kinocut": {
      "command": "uvx",
      "args": ["--from", "kinocut", "kino"]
    }
  }
}
```

Same shape works for other MCP clients that launch a local stdio server.

### Claude Desktop MCPB (staged)

Local package under `mcpb/` — launches an existing Python env with Kinocut; still needs FFmpeg.  
Native self-contained bundles are **not** published yet. See [MCPB.md](MCPB.md).

## Optional extras

| You want | Install | Notes |
| --- | --- | --- |
| Whisper transcription | `pip install "kinocut[transcribe]"` | Large (torch) |
| Image analysis | `pip install "kinocut[image]"` | ~50 MB |
| Stem separation | `pip install "kinocut[stems]"` | Large |
| AI upscale | `pip install "kinocut[upscale]"` | Large; Python ≤3.12 often |
| Procedural audio | `pip install "kinocut[audio]"` | numpy |
| Everything AI | `pip install "kinocut[ai]"` | Several GB |

Core golden path **does not** require extras.

## Hyperframes (optional)

Node.js 22+ and a resolvable Hyperframes CLI (`hyperframes` on PATH or `MCP_VIDEO_HYPERFRAMES_COMMAND`). Not required for FFmpeg tools or golden path.

## Python client

```python
from kinocut import Client
Client().info("clip.mp4")
```

## Failure recovery

| Symptom | Fix |
| --- | --- |
| `ffmpeg: command not found` | Install FFmpeg; restart shell |
| `kino: command not found` | `pip install kinocut` or use `python -m kinocut` |
| Import errors / old Python | Use Python 3.11+ |
| Doctor missing optional AI | Expected unless you installed extras |
| Hyperframes hang/init | See Hyperframes doctor; skip for core path |
| Golden path fails mid-workflow | Re-run; check disk space; open workflow stderr |

## Related

- [GOLDEN_PATH.md](GOLDEN_PATH.md)
- [faq.md](faq.md)
- [CLI_REFERENCE.md](CLI_REFERENCE.md)
