"""Design auto-fix descriptions must match the fixes that are actually wired (#653)."""

import inspect
import re
from pathlib import Path

from kinocut.design_quality.guardrails import checks
from kinocut.design_quality.guardrails.fixes import FixesMixin

ROOT = Path(__file__).resolve().parents[1]
WIRED = {"brightness", "saturation"}


def _fix_methods() -> set[str]:
    return {name for name, _ in inspect.getmembers(FixesMixin, inspect.isfunction) if name.startswith("_auto_")}


def test_every_fix_helper_is_attached_by_a_check():
    source = inspect.getsource(checks)
    unwired = {name for name in _fix_methods() if f"self.{name}(" not in source}
    assert not unwired, f"auto-fix helpers defined but never attached to a DesignIssue: {sorted(unwired)}"


def test_wired_fixes_are_exactly_brightness_and_saturation():
    assert {re.sub(r"^_auto_fix_", "", name) for name in _fix_methods()} == WIRED


def test_fix_descriptions_do_not_claim_audio_or_contrast_fixes():
    from kinocut.server_tools_ai import video_fix_design_issues

    doc = inspect.getdoc(getattr(video_fix_design_issues, "__wrapped__", video_fix_design_issues)) or ""
    summary = doc.split("Args:")[0]
    claims = [summary]
    for rel in ("docs/TOOLS.md", "docs/PYTHON_CLIENT.md"):
        claims += [line for line in (ROOT / rel).read_text().splitlines() if "fix_design_issues" in line]
    for text in claims:
        lowered = " ".join(text.lower().split())
        assert "brightness" in lowered and "saturation" in lowered, text
        assert "audio level issues" not in lowered, text
        assert "brightness, contrast" not in lowered, text
        assert "audio" not in lowered or "not change" in lowered or "not changed" in lowered, text
