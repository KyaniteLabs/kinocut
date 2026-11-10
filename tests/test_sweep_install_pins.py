"""The release pin sweep moves current pins and leaves records alone."""

from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


SCRIPT = _load("sweep_install_pins", ROOT / "scripts" / "sweep_install_pins.py")
SWEEP = SCRIPT._load_sweep()
OLD = {"kinocut": "1.16.5", "mcp-video": "1.6.20"}
NEW = {"kinocut": "2.0.0", "mcp-video": "1.6.21"}


def _rewrite(text: str):
    return SCRIPT.rewrite(text, OLD, NEW, SWEEP)


def test_every_spelling_of_a_current_pin_moves():
    text = (
        "pip install kinocut==1.16.5\n"
        'claude mcp add kinocut -- uvx --from "kinocut[ai]==1.16.5" kino --mcp\n'
        '    "args": ["kinocut==1.16.5"]\n'
        "pip install --upgrade 'kinocut==1.16.5' 'mcp-video==1.6.20'\n"
        "Apache 2.0. pip install kinocut==1.16.5.\n"
    )
    after, moved, _prose = _rewrite(text)
    assert moved == 6
    assert "1.16.5" not in after and "1.6.20" not in after
    assert "pip install kinocut==2.0.0.\n" in after
    assert '"kinocut[ai]==2.0.0"' in after


def test_records_keep_their_versions():
    text = (
        "## 1.16.5 - 2026-10-27\n\n- pip install kinocut==1.16.5\n\n## Install\n\n"
        "Published 2026-10-27: `mcp-video==1.6.20` installs `kinocut==1.16.5`.\n"
        "First shipped as `kinocut[object-matte]==1.15.1`.\n"
    )
    after, moved, prose = _rewrite(text)
    assert moved == 0
    assert after == text
    assert prose == []


def test_prose_naming_the_old_release_is_reported_not_rewritten():
    text = "## Status\n\nPublished 1.16.5 lists 20 tools by default.\n"
    after, moved, prose = _rewrite(text)
    assert moved == 0 and after == text
    assert prose == [(3, "Published 1.16.5 lists 20 tools by default.")]


def test_a_longer_version_is_not_mistaken_for_the_old_one():
    text = "pip install kinocut==1.16.50\n"
    after, moved, _prose = _rewrite(text)
    assert moved == 0 and after == text
