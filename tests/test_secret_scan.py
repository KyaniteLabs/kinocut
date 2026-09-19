"""Regression pins for the vendored secret scanner and its CI gate (card F5).

The red-test acceptance demo (a planted fake token must fail the gate) is the
reason these exist: the scanner must keep catching planted secrets, the
allowlist must keep requiring reasons, and the ci.yml gate jobs must stay
wired exactly as verified.
"""

from __future__ import annotations

import hashlib
import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_SCRIPT = ROOT / "scripts" / "secret_scan.py"
_spec = importlib.util.spec_from_file_location("secret_scan", _SCRIPT)
secret_scan = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(secret_scan)

EMPTY_ALLOW: tuple[set[str], set[str], set[str]] = (set(), set(), set())


def _scan_dir(tmp_path: Path, content: str, allow: tuple[set[str], set[str], set[str]] = EMPTY_ALLOW):
    target = tmp_path / "planted.txt"
    target.write_text(content, encoding="utf-8")
    findings, scanned, _suppressed = secret_scan.scan_worktree(tmp_path, allow)
    return findings, scanned


def test_scanner_flags_planted_github_pat(tmp_path):
    findings, scanned = _scan_dir(tmp_path, 'demo = "ghp_KinocutRedTeam9Zq4Xw7Lm2Rt5Vb8Nc3Jk6HfDs2Pq"\n')
    assert scanned == 1
    assert [(f.rule, f.path, f.line) for f in findings] == [("github_pat", "planted.txt", 1)]
    assert findings[0].describe().startswith("FINDING github_pat planted.txt:1")
    assert "ghp_K" not in findings[0].describe()  # preview stays redacted


def test_scanner_flags_private_key_header(tmp_path):
    findings, _ = _scan_dir(tmp_path, "-----BEGIN OPENSSH PRIVATE KEY-----\n")
    assert [f.rule for f in findings] == ["private_key_block"]


def test_generic_rule_requires_entropy_and_rejects_placeholders(tmp_path):
    high_entropy = 'api_key = "7Qz2Lm9Xw4Rt8Vb3Nc6Jk1Hf5Ds0Pq"\n'
    low_entropy = "password = 'aaaaaaaaaaaaaaaa'\n"
    placeholder = 'secret = "example-placeholder-not-real"\n'
    findings, _ = _scan_dir(tmp_path, high_entropy + low_entropy + placeholder)
    assert [f.line for f in findings] == [1]  # only the high-entropy literal


def test_documented_example_values_never_flag(tmp_path):
    findings, _ = _scan_dir(tmp_path, 'aws_key = "AKIAIOSFODNN7EXAMPLE"\n')
    assert findings == []


def test_bare_identifier_references_do_not_flag(tmp_path):
    findings, _ = _scan_dir(tmp_path, "token=SYNTHETIC_GITHUB_TOKEN\n")
    assert findings == []


def test_allowlist_suppresses_by_content_hash_and_requires_reasons(tmp_path):
    content = 'demo = "ghp_KinocutRedTeam9Zq4Xw7Lm2Rt5Vb8Nc3Jk6HfDs2Pq"\n'
    digest = hashlib.sha256(content.strip().encode()).hexdigest()[:8]
    allow = (set(), set(), {f"planted.txt:{digest}"})
    findings, _suppressed = _scan_dir(tmp_path, content, allow=allow)
    assert findings == []
    assert _suppressed == 1

    bad = tmp_path / "allow.txt"
    bad.write_text("some/path\n", encoding="utf-8")
    _files, _lines, _hashes, errors = secret_scan.load_allowlist(bad)
    assert errors and "reason" in errors[0]


def test_main_red_and_green_exit_codes(tmp_path):
    planted = tmp_path / "planted.txt"
    planted.write_text('demo = "ghp_KinocutRedTeam9Zq4Xw7Lm2Rt5Vb8Nc3Jk6HfDs2Pq"\n', encoding="utf-8")
    allowlist = tmp_path / "allow.txt"
    allowlist.write_text("# empty\n", encoding="utf-8")
    red = secret_scan.main(["--root", str(tmp_path), "--allowlist", str(allowlist), "--skip-history"])
    assert red == 1
    planted.unlink()
    green = secret_scan.main(["--root", str(tmp_path), "--allowlist", str(allowlist), "--skip-history"])
    assert green == 0


def test_ci_yml_wires_the_security_gate_jobs():
    """Prose-to-code pin: the F5 card's gates must stay in ci.yml, always-on."""
    workflow = (ROOT / ".forgejo" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    _head, sep, gates = workflow.partition("\n  secret-scan:")
    assert sep, "ci.yml must define a secret-scan job"
    assert "\n  dep-audit:" in gates, "ci.yml must define a dep-audit job after secret-scan"
    assert "workflow_dispatch:" in workflow
    assert gates.count("runs-on: light") == 2, "both gate jobs ride the light runner"
    assert gates.count("ci-images-base:v1") == 2, "gate jobs run in the prebuilt base image"
    assert "apt-get" not in gates, "toolchain is baked into the image; no per-job apt"
    assert "scripts/secret_scan.py" in gates
    assert "scripts/pip_audit_allowlist.txt" in gates
