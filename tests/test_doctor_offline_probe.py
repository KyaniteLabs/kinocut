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


def test_windows_executable_forms_are_still_refused(monkeypatch):
    # Windows resolves `npx` as `npx.cmd`; the refusal must survive the suffix.
    for command in ("npx.cmd --yes hyperframes", "npm.cmd exec hyperframes", "bunx.exe hyperframes"):
        monkeypatch.setenv(HYPERFRAMES_COMMAND_ENV, command)
        calls: list[list[str]] = []

        def fake_runner(argv, _calls=calls):
            _calls.append(argv)
            return "1.0.0"

        result = doctor._check_hyperframes_cli(lambda name: "/usr/bin/hyperframes", fake_runner)
        assert calls == [], f"{command} must not be probed"
        assert result["ok"] is False


def test_wrapper_prefixes_are_never_executed(monkeypatch):
    # `env npx`, `sh -c npx` and `cmd /c npx` all reach the network.
    for command in ("env npx --yes hyperframes", "sh -c npx --yes hyperframes", "cmd /c npx --yes hyperframes"):
        monkeypatch.setenv(HYPERFRAMES_COMMAND_ENV, command)
        calls: list[list[str]] = []

        def fake_runner(argv, _calls=calls):
            _calls.append(argv)
            return "1.0.0"

        result = doctor._check_hyperframes_cli(lambda name: "/usr/bin/hyperframes", fake_runner)
        assert calls == [], f"{command} must not be probed"
        assert result["ok"] is False


def test_a_path_shim_that_calls_a_package_manager_is_read_not_run(tmp_path):
    from kinocut.doctor_offline import script_invokes_package_manager

    shim = tmp_path / "hyperframes"
    shim.write_text("#!/bin/sh\nexec npx --yes hyperframes\n")
    assert script_invokes_package_manager(str(shim)) is True

    direct = tmp_path / "hyperframes-real"
    direct.write_text("#!/usr/bin/env node\nconsole.log('1.2.3');\n")
    assert script_invokes_package_manager(str(direct)) is False


def test_a_malformed_telemetry_setting_does_not_crash_the_doctor(monkeypatch):
    monkeypatch.setenv("KINOCUT_HYPERFRAMES_TELEMETRY", "maybe")
    environment = doctor._doctor_probe_environment()
    # The conservative reading of an invalid value is telemetry off.
    assert environment["KINOCUT_HYPERFRAMES_TELEMETRY"] == "false"
    assert environment["HYPERFRAMES_NO_UPDATE_CHECK"] == "1"
