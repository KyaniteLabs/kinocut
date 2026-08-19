"""Claim-drift guards for public marketing and discovery surfaces.

``docs/public_claims.json`` is the single source of truth for version,
tool/CLI counts, registry id, and canonical URLs. These tests fail when
README, llms.txt, package metadata, or Pages stubs drift from that file.
"""

from __future__ import annotations

import json
import re
import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
CLAIMS_PATH = ROOT / "docs" / "public_claims.json"


@pytest.fixture(scope="module")
def claims() -> dict:
    data = json.loads(CLAIMS_PATH.read_text(encoding="utf-8"))
    assert data.get("schema_version") == 1
    return data


def test_public_claims_file_is_complete(claims: dict) -> None:
    required = (
        "package_name",
        "published_version",
        "release_candidate_version",
        "published_mcp_tools",
        "published_cli_commands",
        "development_mcp_tools",
        "development_cli_commands",
        "registry_id",
        "website",
        "github",
        "forgejo",
        "pypi",
        "license",
        "formerly",
    )
    missing = [key for key in required if key not in claims]
    assert missing == []
    assert claims["published_mcp_tools"] <= claims["development_mcp_tools"]
    assert claims["published_cli_commands"] <= claims["development_cli_commands"]
    assert claims["website"].startswith("https://")
    assert claims["registry_id"] == "io.github.KyaniteLabs/kinocut"


def test_pyproject_version_matches_release_candidate_claim(claims: dict) -> None:
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    assert project["name"] == claims["package_name"]
    assert project["version"] == claims["release_candidate_version"]
    # Mid-cutover: candidate may lead published until PyPI/npm catch up.
    # After a completed cutover they match.
    assert claims["published_mcp_tools"] <= claims["development_mcp_tools"]


def test_server_json_matches_public_claims(claims: dict) -> None:
    server = json.loads((ROOT / "server.json").read_text(encoding="utf-8"))
    assert server["name"] == claims["registry_id"]
    assert server["websiteUrl"] == claims["website"]
    assert server["repository"]["url"] == claims["github"]
    assert server["packages"][0]["identifier"] == claims["package_name"]


def test_pages_stub_points_at_canonical_website(claims: dict) -> None:
    site = (ROOT / "index.html").read_text(encoding="utf-8")
    assert f'href="{claims["website"]}"' in site or f'href="{claims["website"].rstrip("/")}/"' in site
    assert f"url={claims['website']}" in site or f"url={claims['website'].rstrip('/')}/" in site
    assert claims["github"] in site or "KyaniteLabs/kinocut" in site
    # Stale personal or old-slug Pages URLs must not return.
    assert "pastorsimon1798" not in site
    assert "kyanitelabs.github.io/mcp-video" not in site


def test_readme_states_published_version_and_tip_counts(claims: dict) -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert claims["published_version"] in readme
    assert claims["website"] in readme or claims["website"].rstrip("/") in readme
    assert claims["registry_id"] in readme
    assert claims["github"] in readme
    assert "kyanitelabs.github.io/mcp-video" not in readme
    assert "github.com/KyaniteLabs/mcp-video" not in readme

    # Tip badges / explicit tip language must match development surface.
    tip_badge = re.search(r"MCP-(\d+)%20tools", readme)
    assert tip_badge is not None
    assert int(tip_badge.group(1)) == claims["development_mcp_tools"]

    cli_badge = re.search(r"CLI-(\d+)%20commands", readme)
    assert cli_badge is not None
    assert int(cli_badge.group(1)) == claims["development_cli_commands"]

    # Published surface language in the FAQ / status table.
    assert str(claims["published_mcp_tools"]) in readme
    assert str(claims["published_cli_commands"]) in readme
    assert str(claims["development_mcp_tools"]) in readme
    assert str(claims["development_cli_commands"]) in readme
    assert claims["release_candidate_version"] in readme

    _assert_no_pip_today_overclaim(readme, claims)


def _assert_no_pip_today_overclaim(text: str, claims: dict) -> None:
    """Candidate may appear as tip; it must not be pip-today / latest published."""
    published = claims["published_version"]
    candidate = claims["release_candidate_version"]
    if published == candidate:
        return
    idx = text.find("what you get from `pip install kinocut` today")
    if idx != -1:
        window = text[max(0, idx - 40) : idx + 10]
        assert published in window
        assert candidate not in window
    assert f"**{candidate} is the latest published release.**" not in text
    assert "Latest **published** Kinocut" not in text or published in text
    pip_today = "is what you get from `pip install kinocut` today"
    assert pip_today not in text or (
        f"**{published}** is what you get from `pip install kinocut` today" in text
        or f"Kinocut **{published}** is what you get from `pip install kinocut` today" in text
    )


def test_key_docs_do_not_claim_candidate_is_on_pip(claims: dict) -> None:
    paths = (
        ROOT / "docs" / "status" / "NOW.md",
        ROOT / "docs" / "HUMAN_GATES.md",
        ROOT / "docs" / "faq.md",
        ROOT / "docs" / "CLI_REFERENCE.md",
        ROOT / "docs" / "status" / "2026-08-15-1.15.0-release-notes.md",
        ROOT / "ROADMAP.md",
        ROOT / "llms.txt",
        ROOT / "CHANGELOG.md",
    )
    for path in paths:
        _assert_no_pip_today_overclaim(path.read_text(encoding="utf-8"), claims)


def test_llms_txt_matches_public_claims(claims: dict) -> None:
    text = (ROOT / "llms.txt").read_text(encoding="utf-8")
    assert claims["published_version"] in text
    assert claims["registry_id"] in text
    assert claims["website"] in text or claims["website"].rstrip("/") in text
    assert str(claims["published_mcp_tools"]) in text
    assert str(claims["development_mcp_tools"]) in text
    assert "github.com/KyaniteLabs/mcp-video" not in text


def _shim_kinocut_pins(shim: dict) -> set[str]:
    pins: set[str] = set()
    for dep in shim.get("dependencies") or []:
        if isinstance(dep, str) and dep.startswith("kinocut"):
            pins.add(dep.rsplit("==", 1)[-1])
    extras = shim.get("optional-dependencies") or {}
    for group in extras.values():
        for dep in group:
            if isinstance(dep, str) and "kinocut" in dep and "==" in dep:
                pins.add(dep.rsplit("==", 1)[-1])
    return pins


def test_current_release_docs_and_compatibility_shim_match_claims(claims: dict) -> None:
    """Keep the current documentation set aligned with published + candidate states."""
    published = claims["published_version"]
    candidate = claims["release_candidate_version"]
    shim = tomllib.loads((ROOT / "compat" / "mcp-video-shim" / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    shim_version = shim["version"]
    pins = _shim_kinocut_pins(shim)
    allowed = {published, candidate}
    assert pins <= allowed
    assert len(pins) == 1, f"shim pins must be uniform, got {pins}"
    pin = next(iter(pins))

    assert f"mcp-video=={shim_version}" in (ROOT / "README.md").read_text(encoding="utf-8")
    llms = (ROOT / "llms.txt").read_text(encoding="utf-8")
    assert f"{shim_version} shim → kinocut {pin}" in llms
    assert f"kinocut=={published}" in (ROOT / "README.md").read_text(encoding="utf-8")
    assert published in llms

    discovery = (ROOT / "docs" / "AI_AGENT_DISCOVERY.md").read_text(encoding="utf-8")
    assert f"{claims['published_mcp_tools']} MCP tools / {claims['published_cli_commands']} CLI" in discovery
    assert f"{claims['development_mcp_tools']} MCP tools / {claims['development_cli_commands']} CLI" in discovery

    directory_status = (ROOT / "docs" / "DIRECTORY_REBRAND_STATUS.md").read_text(encoding="utf-8")
    assert f"Current release: {published}" in directory_status
    assert f"Published surface: {claims['published_mcp_tools']} MCP tools" in directory_status

    mcpb = (ROOT / "docs" / "MCPB.md").read_text(encoding="utf-8")
    assert f"kinocut=={published}" in mcpb
    assert f"dist/kinocut-{published}.mcpb" in mcpb

    stream_shorts = (ROOT / "docs" / "STREAM_SHORTS.md").read_text(encoding="utf-8")
    assert "Development tip only until a published release" not in stream_shorts

    compat_readme = (ROOT / "compat" / "mcp-video-shim" / "README.md").read_text(encoding="utf-8")
    major_s, minor_s, *_rest = published.split(".")
    assert f"{major_s}.{minor_s}.x line" in compat_readme

    roadmap = (ROOT / "ROADMAP.md").read_text(encoding="utf-8")
    assert f"Kinocut {published} is published" in roadmap
    assert "released 1.7.0 surface" not in roadmap
    assert "post-campaign tip status" in roadmap

    checklist = (ROOT / "docs" / "RELEASE_1.8_CHECKLIST.md").read_text(encoding="utf-8")
    assert "**Status:** COMPLETE" in checklist
    assert f"**Published result:** {published}" in checklist

    release_notes = (ROOT / "docs" / "status" / "2026-07-14-1.8-release-notes.md").read_text(encoding="utf-8")
    assert "**Published:**" in release_notes
    assert "**Not published.**" not in release_notes
    assert f"mcp-video=={shim_version}" in release_notes

    docs_index = (ROOT / "docs" / "README.md").read_text(encoding="utf-8")
    assert "post-campaign tip status" in docs_index
    assert "`docs/status/` entries are snapshots" in docs_index


def test_public_surface_expected_counts_match_development_claims(claims: dict) -> None:
    """Keep characterization counts and marketing tip counts synchronized."""
    surface = (ROOT / "tests" / "test_public_surface.py").read_text(encoding="utf-8")
    assert f"== {claims['development_cli_commands']}" in surface
    assert f"== {claims['development_mcp_tools']}" in surface


def test_sitemap_and_robots_point_at_canonical_site(claims: dict) -> None:
    robots = (ROOT / "robots.txt").read_text(encoding="utf-8")
    sitemap = (ROOT / "sitemap.xml").read_text(encoding="utf-8")
    site = claims["website"].rstrip("/")
    assert f"Sitemap: {site}/sitemap.xml" in robots or f"Sitemap: {claims['website']}sitemap.xml" in robots
    assert f"{site}/" in sitemap or claims["website"] in sitemap
