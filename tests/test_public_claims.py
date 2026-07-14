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
    # After cutover they match (e.g. both 1.8.0).
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

    # Do not claim the *next* unreleased X.Y.0 as shipped.
    major_s, minor_s, *_rest = claims["published_version"].split(".")
    next_minor = f"{major_s}.{int(minor_s) + 1}.0"
    assert re.search(rf"\b{re.escape(next_minor)}\b", readme) is None, (
        f"README must not claim unreleased {next_minor} while published is {claims['published_version']}"
    )
    assert f"pip install kinocut=={major_s}.{int(minor_s) + 1}" not in readme


def test_llms_txt_matches_public_claims(claims: dict) -> None:
    text = (ROOT / "llms.txt").read_text(encoding="utf-8")
    assert claims["published_version"] in text
    assert claims["registry_id"] in text
    assert claims["website"] in text or claims["website"].rstrip("/") in text
    assert str(claims["published_mcp_tools"]) in text
    assert str(claims["development_mcp_tools"]) in text
    assert "github.com/KyaniteLabs/mcp-video" not in text


def test_current_release_docs_and_compatibility_shim_match_claims(claims: dict) -> None:
    """Keep the current documentation set aligned with the published release."""
    published = claims["published_version"]
    shim = tomllib.loads((ROOT / "compat" / "mcp-video-shim" / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    shim_version = shim["version"]

    assert f"kinocut=={published}" in shim["dependencies"]
    assert f"mcp-video=={shim_version}" in (ROOT / "README.md").read_text(encoding="utf-8")
    assert f"{shim_version} shim → kinocut {published}" in (ROOT / "llms.txt").read_text(encoding="utf-8")

    roadmap = (ROOT / "ROADMAP.md").read_text(encoding="utf-8")
    assert f"Kinocut {published} is published" in roadmap
    assert "released 1.7.0 surface" not in roadmap

    checklist = (ROOT / "docs" / "RELEASE_1.8_CHECKLIST.md").read_text(encoding="utf-8")
    assert "**Status:** COMPLETE" in checklist
    assert f"**Published result:** {published}" in checklist

    release_notes = (ROOT / "docs" / "status" / "2026-07-14-1.8-release-notes.md").read_text(encoding="utf-8")
    assert "**Published:**" in release_notes
    assert "**Not published.**" not in release_notes
    assert f"mcp-video=={shim_version}" in release_notes

    docs_index = (ROOT / "docs" / "README.md").read_text(encoding="utf-8")
    assert "post-1.8 program status" in docs_index
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
