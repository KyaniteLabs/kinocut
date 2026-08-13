"""Package import stays lazy; public names and the mcp_video alias still resolve."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

_HEAVY = (
    "kinocut.ai_engine",
    "kinocut.audio_engine",
    "kinocut.client",
    "kinocut.contracts",
    "kinocut.design_quality",
    "kinocut.effects_engine",
    "kinocut.quality_guardrails",
    "kinocut.transitions_engine",
)


def _run(code: str) -> str:
    return subprocess.check_output([sys.executable, "-c", code], cwd=ROOT, text=True)


def test_bare_import_does_not_load_engines() -> None:
    loaded = _run("import sys, kinocut; print(','.join(m for m in sys.modules if m in " + repr(_HEAVY) + "))").strip()
    assert loaded == ""


def test_client_attribute_loads_client_only() -> None:
    out = _run(
        "import sys, kinocut; kinocut.Client; print('client' if 'kinocut.client' in "
        "sys.modules else 'missing'); print('ai' if 'kinocut.ai_engine' in "
        "sys.modules else 'no-ai')"
    )
    assert "client" in out
    assert "no-ai" in out


def test_submodule_import_still_resolves() -> None:
    out = _run("from kinocut import engine_audio_bed; print(engine_audio_bed.__name__)")
    assert out.strip() == "kinocut.engine_audio_bed"


def test_mcp_video_import_does_not_load_engines() -> None:
    loaded = _run(
        "import sys, mcp_video; print(','.join(m for m in sys.modules if m in " + repr(_HEAVY) + "))"
    ).strip()
    assert loaded == ""


def test_star_import_and_compat_identity() -> None:
    out = _run(
        "import kinocut, mcp_video; "
        "from kinocut import Client, assert_quality, contracts; "
        "assert kinocut.Client is mcp_video.Client; "
        "assert Client is kinocut.Client; "
        "assert callable(assert_quality); "
        "assert contracts.__name__ == 'kinocut.contracts'; "
        "print('ok', kinocut.__version__)"
    )
    assert out.strip().startswith("ok ")


def test_unknown_attribute_raises() -> None:
    code = (
        "import kinocut\n"
        "try:\n"
        "    kinocut.definitely_not_a_public_name\n"
        "except AttributeError as exc:\n"
        "    print(type(exc).__name__)\n"
        "else:\n"
        "    print('no-error')\n"
    )
    assert _run(code).strip() == "AttributeError"


def test_ship_seam_docs_name_durable_min_score_as_unused() -> None:
    handler = (ROOT / "kinocut" / "server_tools_repurpose.py").read_text(encoding="utf-8")
    cli_ref = (ROOT / "docs" / "CLI_REFERENCE.md").read_text(encoding="utf-8")
    client_doc = (ROOT / "docs" / "PYTHON_CLIENT.md").read_text(encoding="utf-8")
    assert "not applied" in handler
    assert "--min-score" in cli_ref
    assert "--allow-fail" in cli_ref
    assert "does not apply `min_score`" in cli_ref or "does **not** apply `min_score`" in cli_ref
    assert "allow_fail" in client_doc
