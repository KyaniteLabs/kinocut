"""The doctor never runs a package-manager probe.

A package manager resolves its package over the network, so a configured
`npx --yes hyperframes` prefix would take the doctor online — which its own
comment forbids. The doctor reports the configured command instead.

The rule is inverted rather than an allowlist: only the Hyperframes
executable itself is probed, and only when the doctor can read it and clear
it. A shell, an interpreter, a package manager, a binary, and a file that
invokes a package manager anywhere inside it are all reported, not run.
"""

from __future__ import annotations

from kinocut import doctor
from kinocut.doctor_offline import executable_probe_refusal, is_package_manager_prefix
from kinocut.hyperframes_engine import HYPERFRAMES_COMMAND_ENV


def _script(tmp_path, name: str, body: str) -> str:
    """A readable script the doctor is allowed to run."""
    path = tmp_path / name
    path.write_text(body, encoding="utf-8")
    return str(path)


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


def test_a_resolved_executable_is_still_probed(tmp_path, monkeypatch):
    path = _script(tmp_path, "hyperframes", "#!/usr/bin/env node\nconsole.log('1.2.3');\n")
    monkeypatch.setenv(HYPERFRAMES_COMMAND_ENV, path)
    calls: list[list[str]] = []

    def fake_runner(command):
        calls.append(command)
        return "1.2.3"

    result = doctor._check_hyperframes_cli(lambda name: path, fake_runner)
    assert calls == [[path, "--version"]]
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


def test_configured_interpreters_are_refused_without_an_allowlist(monkeypatch):
    # An allowlist of interpreter names is always incomplete: perl, ruby and
    # deno were missing from the first one. Only the executable itself passes.
    for command in (
        "perl -e 'system(\"npx\")'",
        "ruby -e 'system(\"npx\")'",
        "deno run -A x.ts",
        "busybox npx hyperframes",
        "python3 -c 'import npx'",
    ):
        monkeypatch.setenv(HYPERFRAMES_COMMAND_ENV, command)
        calls: list[list[str]] = []

        def fake_runner(argv, _calls=calls):
            _calls.append(argv)
            return "1.0.0"

        result = doctor._check_hyperframes_cli(lambda name: "/usr/bin/hyperframes", fake_runner)
        assert calls == [], f"{command} must not be probed"
        assert result["ok"] is False


def test_a_path_shim_that_calls_a_package_manager_is_read_not_run(tmp_path):
    shim = tmp_path / "hyperframes"
    shim.write_text("#!/bin/sh\nexec npx --yes hyperframes\n")
    assert executable_probe_refusal(str(shim)) is not None

    direct = tmp_path / "hyperframes-real"
    direct.write_text("#!/usr/bin/env node\nconsole.log('1.2.3');\n")
    assert executable_probe_refusal(str(direct)) is None


def test_a_shim_without_an_interpreter_line_is_not_run(tmp_path):
    # A file the doctor cannot classify is a file it does not run.
    shim = tmp_path / "hyperframes"
    shim.write_text("npx --yes hyperframes\n")
    assert executable_probe_refusal(str(shim)) is not None


def test_a_binary_shim_is_not_run(tmp_path):
    binary = tmp_path / "hyperframes"
    binary.write_bytes(b"\x7fELF\x02\x01\x01\x00npx --yes hyperframes")
    assert executable_probe_refusal(str(binary)) is not None


def test_a_package_manager_beyond_the_first_read_window_is_still_found(tmp_path):
    # The old scan read 8192 bytes, so a call past that window was missed.
    shim = tmp_path / "hyperframes"
    shim.write_text("#!/bin/sh\n" + ("# padding line\n" * 2000) + "exec npx --yes hyperframes\n")
    assert executable_probe_refusal(str(shim)) is not None


def test_a_path_that_is_not_a_regular_file_is_not_run(tmp_path):
    assert executable_probe_refusal(str(tmp_path)) is not None
    assert executable_probe_refusal(str(tmp_path / "missing")) is not None


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
