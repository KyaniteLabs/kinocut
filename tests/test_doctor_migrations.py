"""Doctor migration / readiness checks (#56)."""

from __future__ import annotations

from kinocut.doctor import _check_alias_identity, _check_legacy_env_paths, run_diagnostics


def test_run_diagnostics_includes_a_migrations_section():
    report = run_diagnostics()
    assert "migrations" in report
    names = {check["name"] for check in report["migrations"]}
    assert "alias_identity" in names
    assert "legacy_env_paths" in names


def test_alias_identity_check_passes_when_kinocut_and_mcp_video_share_client():
    check = _check_alias_identity()
    assert check["name"] == "alias_identity"
    assert check["category"] == "migration"
    assert check["ok"] is True
    assert check["remediation"]


def test_alias_identity_check_fails_when_alias_is_broken(monkeypatch):
    import mcp_video

    class _Other:
        pass

    monkeypatch.setattr(mcp_video, "Client", _Other, raising=False)
    check = _check_alias_identity()
    assert check["ok"] is False
    assert "kinocut.Client" in check["remediation"] or "alias" in check["remediation"].lower()


def test_legacy_env_check_passes_when_no_stale_paths(monkeypatch):
    monkeypatch.delenv("MCP_VIDEO_CRUSH_PATH", raising=False)
    check = _check_legacy_env_paths()
    assert check["name"] == "legacy_env_paths"
    assert check["ok"] is True


def test_legacy_env_check_flags_stale_crush_env(monkeypatch):
    monkeypatch.setenv("MCP_VIDEO_CRUSH_PATH", "/old/.mcp-video/crush")
    check = _check_legacy_env_paths()
    assert check["ok"] is False
    assert "MCP_VIDEO_CRUSH_PATH" in check["remediation"]


def test_migration_checks_are_read_only_and_carry_remediation():
    report = run_diagnostics()
    for check in report["migrations"]:
        assert check["category"] == "migration"
        assert "remediation" in check
        # Migration checks are advisory readiness signals, never required gates.
        assert check.get("required") in (None, False)
