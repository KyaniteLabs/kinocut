"""The doctor never runs a package-manager probe.

A package manager resolves its package over the network, so a configured
`npx --yes hyperframes` prefix would take the doctor online — which its own
comment forbids. The doctor reports the configured command instead.
"""

from __future__ import annotations

from kinocut import doctor
from kinocut.doctor_offline import is_package_manager_prefix
from kinocut.hyperframes_engine import HYPERFRAMES_COMMAND_ENV


def test_a_configured_package_manager_probe_is_never_executed(monkeypatch):
    monkeypatch.setenv(HYPERFRAMES_COMMAND_ENV, "npx --yes hyperframes")
    calls: list[list[str]] = []

    def fake_runner(command):
        calls.append(command)
        return "1.0.0"

    result = doctor._check_hyperframes_cli(lambda name: "/usr/bin/hyperframes", fake_runner)
    assert calls == []
    assert result["ok"] is False
    assert result["version"] is None
    assert "package manager" in result["install_hint"]


def test_a_resolved_binary_is_still_probed(monkeypatch):
    monkeypatch.setenv(HYPERFRAMES_COMMAND_ENV, "/usr/local/bin/hyperframes")
    calls: list[list[str]] = []

    def fake_runner(command):
        calls.append(command)
        return "1.2.3"

    result = doctor._check_hyperframes_cli(lambda name: "/usr/bin/hyperframes", fake_runner)
    assert calls == [["/usr/local/bin/hyperframes", "--version"]]
    assert result["ok"] is True
    assert result["version"] == "1.2.3"


def test_the_package_manager_list_covers_the_usual_resolvers():
    for prefix in ("npx", "npm", "pnpm", "yarn", "bunx"):
        assert is_package_manager_prefix([prefix, "hyperframes"]) is True
    assert is_package_manager_prefix(["/usr/local/bin/hyperframes"]) is False
    assert is_package_manager_prefix([]) is False
