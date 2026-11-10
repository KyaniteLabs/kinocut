"""Static guards for the Hermes Desktop half of the Kinocut plugin.

plugin.js is plain uncompiled ESM loaded by Hermes Desktop; its SDK imports cannot
resolve here, so these tests check the contract rules from the Desktop plugin SDK
(opt-in, theme tokens only, tracked timers) without executing it.
"""

import re
from pathlib import Path

PLUGIN = Path(__file__).resolve().parents[1] / "plugins" / "kinocut" / "desktop" / "plugin.js"


def _source() -> str:
    return PLUGIN.read_text(encoding="utf-8")


def test_plugin_ships_beside_mcp_json() -> None:
    assert PLUGIN.is_file()
    assert (PLUGIN.parent.parent / "mcp.json").is_file()


def test_plugin_is_opt_in() -> None:
    assert re.search(r"defaultEnabled:\s*false", _source())


def test_plugin_has_no_hardcoded_colours() -> None:
    src = _source()
    assert not re.search(r"#[0-9a-fA-F]{3,8}\b", src)
    assert not re.search(r"\b(?:rgba?|hsla?|oklch)\(", src)


def test_plugin_uses_only_resolvable_imports() -> None:
    specs = re.findall(r"""^\s*import\b[^'"]*['"]([^'"]+)['"]""", _source(), re.M)
    assert specs
    assert set(specs) <= {"@hermes/plugin-sdk", "react", "react/jsx-runtime"}


def test_plugin_uses_scoped_timers_only() -> None:
    src = _source()
    assert not re.search(r"\bwindow\.(?:setTimeout|setInterval|addEventListener)\b", src)
    for match in re.finditer(r"(?<![\w.])(setTimeout|setInterval)\(", src):
        raise AssertionError(f"bare {match.group(1)}( outside ctx.")


def test_plugin_does_no_top_level_work() -> None:
    src = _source()
    assert not re.search(r"^\s*await\b", src, re.M)
