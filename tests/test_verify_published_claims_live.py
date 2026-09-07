from __future__ import annotations

import json
from pathlib import Path
from urllib.error import HTTPError

import pytest

import scripts.verify_published_claims_live as live


def test_all_four_official_providers_must_match(monkeypatch) -> None:
    probes = (
        ("pypi", lambda: ("1.15.1", "")),
        ("npm", lambda: ("1.15.1", "")),
        ("github_release", lambda: ("1.15.0", "")),
        ("mcp_registry", lambda: (None, "timeout")),
    )
    monkeypatch.setattr(live, "PROVIDERS", probes)
    assert live.verify_claim("1.15.1") == [
        "github_release: expected 1.15.1, got 1.15.0",
        "mcp_registry: timeout",
    ]


def test_provider_schema_is_fail_closed(monkeypatch) -> None:
    monkeypatch.setattr(live, "_get_json", lambda url: (200, {"wrong": {}}, ""))
    assert live.pypi_latest() == (None, "unexpected response schema")
    assert live.npm_latest() == (None, "unexpected response schema")
    assert live.github_latest_release() == (None, "unexpected response schema")
    assert live.mcp_registry_latest() == (None, "unexpected response schema")


@pytest.mark.parametrize(
    ("probe", "body", "url_fragment"),
    [
        (live.pypi_latest, {"info": {"version": "1.15.1"}}, "pypi.org/pypi/kinocut/json"),
        (live.npm_latest, {"version": "1.15.1"}, "registry.npmjs.org/kinocut/latest"),
        (live.github_latest_release, {"tag_name": "v1.15.1"}, "repos/KyaniteLabs/kinocut/releases/latest"),
        (
            live.mcp_registry_latest,
            {"server": {"version": "1.15.1"}},
            "servers/io.github.KyaniteLabs%2Fkinocut/versions/latest",
        ),
    ],
)
def test_provider_happy_schemas_and_urls(monkeypatch, probe, body, url_fragment) -> None:
    observed = []

    def get_json(url):
        observed.append(url)
        return 200, body, ""

    monkeypatch.setattr(live, "_get_json", get_json)
    assert probe() == ("1.15.1", "")
    assert url_fragment in observed[0]


class _Response:
    status = 200

    def __init__(self, body: bytes):
        self.body = body

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self, limit):
        return self.body[:limit]


def test_get_json_applies_timeout_and_response_cap(monkeypatch) -> None:
    observed = {}

    def open_ok(request, timeout):
        observed["timeout"] = timeout
        return _Response(b"x" * (live.MAX_RESPONSE_BYTES + 1))

    monkeypatch.setattr(live.urllib.request, "urlopen", open_ok)
    assert live._get_json("https://example.invalid")[2] == "response exceeded byte limit"
    assert observed["timeout"] == live.TIMEOUT

    monkeypatch.setattr(
        live.urllib.request,
        "urlopen",
        lambda request, timeout: (_ for _ in ()).throw(TimeoutError("slow")),
    )
    status, body, error = live._get_json("https://example.invalid")
    assert (status, body) == (0, None)
    assert "slow" in error

    monkeypatch.setattr(
        live.urllib.request,
        "urlopen",
        lambda request, timeout: (_ for _ in ()).throw(HTTPError(request.full_url, 503, "unavailable", {}, None)),
    )
    assert live._get_json("https://example.invalid") == (503, None, "HTTP 503")


@pytest.mark.parametrize(
    ("probes", "expected"),
    [
        (("1.15.1", ""), 0),
        (("1.15.0", ""), 1),
        ((None, "timeout"), 1),
    ],
)
def test_main_requires_all_provider_results(monkeypatch, tmp_path: Path, probes, expected: int) -> None:
    claims = tmp_path / "claims.json"
    claims.write_text(json.dumps({"published_version": "1.15.1"}), encoding="utf-8")
    monkeypatch.setattr(live, "PROVIDERS", tuple((name, lambda result=probes: result) for name in ("a", "b", "c", "d")))
    assert live.main(["--claims", str(claims)]) == expected
