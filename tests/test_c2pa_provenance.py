"""Tests for optional C2PA provenance signing on final exports."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from mcp_video.errors import MCPVideoError
from mcp_video.models import EditResult


_DEFAULT_VERIFY_PAYLOAD = object()


def _fake_c2patool(
    path: Path,
    *,
    verify_failure: bool = False,
    verify_payload: object = _DEFAULT_VERIFY_PAYLOAD,
) -> Path:
    script = path / "fake-c2patool"
    success_payload = (
        {
            "active_manifest": "urn:uuid:kinocut-test",
            "manifests": {"urn:uuid:kinocut-test": {"claim_generator": "Kinocut test"}},
            "validation_state": "Valid",
            "validation_status": [],
        }
        if verify_payload is _DEFAULT_VERIFY_PAYLOAD
        else verify_payload
    )
    script.write_text(
        "\n".join(
            [
                "#!/usr/bin/env python3",
                "import json",
                "import sys",
                "from pathlib import Path",
                "log = Path(__file__).with_suffix('.log')",
                "args = sys.argv[1:]",
                "log.write_text(log.read_text() + json.dumps(args) + '\\n' if log.exists() else json.dumps(args) + '\\n')",
                "if '--manifest' in args or '-m' in args:",
                "    src = Path(args[0])",
                "    try:",
                "        out = Path(args[args.index('--output') + 1])",
                "    except ValueError:",
                "        out = Path(args[args.index('-o') + 1])",
                "    out.write_bytes(src.read_bytes() + b'\\nC2PA-SIGNED')",
                "    print(json.dumps({'signed': True, 'active_manifest': {'label': 'kinocut:test'}}))",
                "    raise SystemExit(0)",
                "if " + repr(verify_failure) + ":",
                "    print(json.dumps({'validation_status': [{'code': 'claimSignature.mismatch'}]}))",
                "    raise SystemExit(0)",
                "print(json.dumps(" + repr(success_payload) + "))",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    script.chmod(0o755)
    return script


def _fake_c2patool_nonzero_verify(path: Path) -> Path:
    script = _fake_c2patool(path)
    text = script.read_text(encoding="utf-8")
    text = text.replace(
        "print(json.dumps("
        + repr(
            {
                "active_manifest": "urn:uuid:kinocut-test",
                "manifests": {"urn:uuid:kinocut-test": {"claim_generator": "Kinocut test"}},
                "validation_state": "Valid",
                "validation_status": [],
            }
        )
        + "))",
        "print('https://private.example/claim /Users/private/asset.mp4 PRIVATE-CERT-DATA')\n"
        "print('signer=/opt/private/signer secret=SIGNING-MATERIAL', file=sys.stderr)\n"
        "raise SystemExit(9)",
    )
    script.write_text(text, encoding="utf-8")
    return script


def _manifest(path: Path) -> Path:
    manifest = path / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "claim_generator": "Kinocut test",
                "assertions": [{"label": "org.kinocut.test", "data": {"ok": True}}],
            }
        ),
        encoding="utf-8",
    )
    return manifest


def test_c2pa_provider_signs_then_verifies_with_fake_executable(tmp_path):
    from mcp_video.c2pa import sign_export_with_c2pa

    tool = _fake_c2patool(tmp_path)
    manifest = _manifest(tmp_path)
    asset = tmp_path / "final.mp4"
    asset.write_bytes(b"mp4 bytes")

    result = sign_export_with_c2pa(
        str(asset),
        manifest_path=str(manifest),
        tool_path=str(tool),
        signer_path="/opt/kinocut/signer",
    )

    assert result["status"] == "signed"
    assert result["verified"] is True
    assert result["trusted"] is True
    assert result["warning_codes"] == []
    assert set(result) == {"status", "verified", "trusted", "warning_codes"}
    assert "tool" not in result
    assert "manifest_path" not in result
    assert "signer_path" not in result
    assert str(tool) not in json.dumps(result)
    assert str(manifest) not in json.dumps(result)
    assert "/opt/kinocut/signer" not in json.dumps(result)
    calls = [json.loads(line) for line in tool.with_suffix(".log").read_text(encoding="utf-8").splitlines()]
    assert calls[0] == [
        str(asset),
        "--manifest",
        str(manifest),
        "--output",
        str(asset.with_name("final.c2pa-signing.mp4")),
        "--force",
        "--signer-path",
        "/opt/kinocut/signer",
    ]
    assert calls[1] == [str(asset.with_name("final.c2pa-signing.mp4"))]
    assert asset.read_bytes() == b"mp4 bytes\nC2PA-SIGNED"


def test_c2pa_provider_reports_untrusted_signing_credential_as_warning(tmp_path):
    from mcp_video.c2pa import sign_export_with_c2pa

    tool = _fake_c2patool(
        tmp_path,
        verify_payload={
            "active_manifest": "urn:uuid:kinocut-test",
            "manifests": {"urn:uuid:test": {"claim_generator": "Kinocut test"}},
            "validation_state": "Valid",
            "validation_status": [
                {
                    "code": "signingCredential.untrusted",
                    "explanation": "development signing certificate is not trusted",
                    "url": "self#jumbf=/c2pa/test/c2pa.signature",
                    "cert_chain": "PRIVATE-CERT-DATA",
                }
            ],
        },
    )
    manifest = _manifest(tmp_path)
    asset = tmp_path / "final.mp4"
    asset.write_bytes(b"mp4 bytes")

    result = sign_export_with_c2pa(str(asset), manifest_path=str(manifest), tool_path=str(tool))

    assert result["status"] == "signed"
    assert result["verified"] is True
    assert result["trusted"] is False
    assert result["warning_codes"] == ["signing_credential_untrusted"]
    assert set(result) == {"status", "verified", "trusted", "warning_codes"}
    serialized = json.dumps(result)
    assert "signingCredential.untrusted" not in serialized
    assert "development signing certificate" not in serialized
    assert "self#jumbf" not in serialized
    assert "PRIVATE-CERT-DATA" not in serialized


def test_c2pa_provider_fails_closed_when_verification_reports_errors(tmp_path):
    from mcp_video.c2pa import sign_export_with_c2pa

    tool = _fake_c2patool(tmp_path, verify_failure=True)
    manifest = _manifest(tmp_path)
    asset = tmp_path / "final.mp4"
    original_bytes = b"original mp4 bytes"
    asset.write_bytes(original_bytes)

    with pytest.raises(MCPVideoError) as exc:
        sign_export_with_c2pa(str(asset), manifest_path=str(manifest), tool_path=str(tool))

    assert exc.value.code == "c2pa_verification_failed"
    assert asset.read_bytes() == original_bytes
    assert not asset.with_name("final.c2pa-signing.mp4").exists()
    calls = [json.loads(line) for line in tool.with_suffix(".log").read_text(encoding="utf-8").splitlines()]
    assert calls[1] == [str(asset.with_name("final.c2pa-signing.mp4"))]


def test_c2pa_provider_fails_when_untrusted_status_has_invalid_validation_state(tmp_path):
    from mcp_video.c2pa import sign_export_with_c2pa

    tool = _fake_c2patool(
        tmp_path,
        verify_payload={
            "active_manifest": "urn:uuid:kinocut-test",
            "validation_state": "Invalid",
            "validation_status": [{"code": "signingCredential.untrusted"}],
        },
    )
    manifest = _manifest(tmp_path)
    asset = tmp_path / "final.mp4"
    original_bytes = b"original mp4 bytes"
    asset.write_bytes(original_bytes)

    with pytest.raises(MCPVideoError) as exc:
        sign_export_with_c2pa(str(asset), manifest_path=str(manifest), tool_path=str(tool))

    assert exc.value.code == "c2pa_verification_failed"
    assert asset.read_bytes() == original_bytes


def test_c2pa_provider_fails_when_untrusted_status_is_not_the_only_status(tmp_path):
    from mcp_video.c2pa import sign_export_with_c2pa

    tool = _fake_c2patool(
        tmp_path,
        verify_payload={
            "active_manifest": "urn:uuid:kinocut-test",
            "validation_state": "Valid",
            "validation_status": [
                {"code": "signingCredential.untrusted"},
                {"code": "claimSignature.mismatch"},
            ],
        },
    )
    manifest = _manifest(tmp_path)
    asset = tmp_path / "final.mp4"
    original_bytes = b"original mp4 bytes"
    asset.write_bytes(original_bytes)

    with pytest.raises(MCPVideoError) as exc:
        sign_export_with_c2pa(str(asset), manifest_path=str(manifest), tool_path=str(tool))

    assert exc.value.code == "c2pa_verification_failed"
    assert asset.read_bytes() == original_bytes


def test_c2pa_provider_fails_closed_when_verify_command_fails(tmp_path):
    from mcp_video.c2pa import sign_export_with_c2pa

    tool = _fake_c2patool_nonzero_verify(tmp_path)
    manifest = _manifest(tmp_path)
    asset = tmp_path / "final.mp4"
    asset.write_bytes(b"mp4 bytes")

    with pytest.raises(MCPVideoError) as exc:
        sign_export_with_c2pa(str(asset), manifest_path=str(manifest), tool_path=str(tool))

    assert exc.value.code == "c2pa_verification_failed"
    assert str(exc.value) == "C2PA verification failed: c2patool verification command failed"
    serialized = json.dumps(exc.value.to_dict())
    for sensitive in (
        "private.example",
        "/Users/private",
        "PRIVATE-CERT-DATA",
        "/opt/private/signer",
        "SIGNING-MATERIAL",
        str(tool),
        str(asset),
    ):
        assert sensitive not in serialized


@pytest.mark.parametrize("validation_status", [{}, 0, False, ""])
def test_c2pa_provider_rejects_present_non_list_validation_status(tmp_path, validation_status):
    from mcp_video.c2pa import sign_export_with_c2pa

    tool = _fake_c2patool(
        tmp_path,
        verify_payload={
            "active_manifest": "urn:uuid:kinocut-test",
            "validation_state": "Valid",
            "validation_status": validation_status,
        },
    )
    manifest = _manifest(tmp_path)
    asset = tmp_path / "final.mp4"
    asset.write_bytes(b"mp4 bytes")

    with pytest.raises(MCPVideoError) as exc:
        sign_export_with_c2pa(str(asset), manifest_path=str(manifest), tool_path=str(tool))

    assert exc.value.code == "c2pa_verification_failed"


def test_c2pa_provider_allows_missing_validation_status(tmp_path):
    from mcp_video.c2pa import sign_export_with_c2pa

    tool = _fake_c2patool(
        tmp_path,
        verify_payload={
            "active_manifest": "urn:uuid:kinocut-test",
            "validation_state": "Valid",
        },
    )
    manifest = _manifest(tmp_path)
    asset = tmp_path / "final.mp4"
    asset.write_bytes(b"mp4 bytes")

    result = sign_export_with_c2pa(str(asset), manifest_path=str(manifest), tool_path=str(tool))

    assert result == {"status": "signed", "verified": True, "trusted": True, "warning_codes": []}


@pytest.mark.parametrize(
    "manifest_evidence",
    [
        {"active_manifest": "urn:uuid:kinocut-test"},
        {"manifests": {"urn:uuid:kinocut-test": {}}},
        {
            "active_manifest": "urn:uuid:kinocut-test",
            "manifests": {"urn:uuid:kinocut-test": {}},
        },
    ],
)
def test_c2pa_provider_accepts_structured_manifest_evidence(tmp_path, manifest_evidence):
    from mcp_video.c2pa import sign_export_with_c2pa

    payload = {"validation_state": "Valid", "validation_status": [], **manifest_evidence}
    tool = _fake_c2patool(tmp_path, verify_payload=payload)
    manifest = _manifest(tmp_path)
    asset = tmp_path / "final.mp4"
    asset.write_bytes(b"mp4 bytes")

    result = sign_export_with_c2pa(str(asset), manifest_path=str(manifest), tool_path=str(tool))

    assert result["status"] == "signed"


@pytest.mark.parametrize(
    "manifest_evidence",
    [
        {},
        {"active_manifest": ""},
        {"active_manifest": True},
        {"active_manifest": {"label": "truthy but invalid"}},
        {"manifests": {}},
        {"manifests": []},
        {"manifests": True},
        {"manifests": {"": {}}},
    ],
)
def test_c2pa_provider_rejects_invalid_manifest_evidence(tmp_path, manifest_evidence):
    from mcp_video.c2pa import sign_export_with_c2pa

    payload = {"validation_state": "Valid", "validation_status": [], **manifest_evidence}
    tool = _fake_c2patool(tmp_path, verify_payload=payload)
    manifest = _manifest(tmp_path)
    asset = tmp_path / "final.mp4"
    asset.write_bytes(b"mp4 bytes")

    with pytest.raises(MCPVideoError) as exc:
        sign_export_with_c2pa(str(asset), manifest_path=str(manifest), tool_path=str(tool))

    assert exc.value.code == "c2pa_verification_failed"


@pytest.mark.parametrize("payload", [[], False, 0, "verification"])
def test_c2pa_provider_rejects_non_object_top_level_json(tmp_path, payload):
    from mcp_video.c2pa import sign_export_with_c2pa

    tool = _fake_c2patool(tmp_path, verify_payload=payload)
    manifest = _manifest(tmp_path)
    asset = tmp_path / "final.mp4"
    asset.write_bytes(b"mp4 bytes")

    with pytest.raises(MCPVideoError) as exc:
        sign_export_with_c2pa(str(asset), manifest_path=str(manifest), tool_path=str(tool))

    assert exc.value.code == "c2pa_verification_failed"


def test_c2pa_provider_rejects_signed_only_verification_payload(tmp_path):
    from mcp_video.c2pa import sign_export_with_c2pa

    tool = _fake_c2patool(tmp_path, verify_payload={"signed": True, "validation_status": []})
    manifest = _manifest(tmp_path)
    asset = tmp_path / "final.mp4"
    original_bytes = b"original mp4 bytes"
    asset.write_bytes(original_bytes)

    with pytest.raises(MCPVideoError) as exc:
        sign_export_with_c2pa(str(asset), manifest_path=str(manifest), tool_path=str(tool))

    assert exc.value.code == "c2pa_verification_failed"
    assert asset.read_bytes() == original_bytes
    assert not asset.with_name("final.c2pa-signing.mp4").exists()


def test_c2pa_provider_requires_available_executable(tmp_path):
    from mcp_video.c2pa import sign_export_with_c2pa

    manifest = _manifest(tmp_path)
    asset = tmp_path / "final.mp4"
    asset.write_bytes(b"mp4 bytes")

    with pytest.raises(MCPVideoError) as exc:
        sign_export_with_c2pa(str(asset), manifest_path=str(manifest), tool_path=str(tmp_path / "missing"))

    assert exc.value.code == "c2patool_not_found"


def test_export_video_defaults_to_unsigned(monkeypatch, tmp_path):
    from mcp_video import engine_export

    output = tmp_path / "exported.mp4"

    def fake_convert(*args, **kwargs):
        output.write_bytes(b"mp4")
        return EditResult(output_path=str(output), operation="convert")

    monkeypatch.setattr("mcp_video.engine_convert.convert", fake_convert)
    monkeypatch.setattr(engine_export, "_validate_input_path", lambda p: p)

    result = engine_export.export_video("input.mp4", output_path=str(output), format="mp4")

    assert result.c2pa is None
    assert result.operation == "export"


def test_export_video_can_sign_final_mp4(monkeypatch, tmp_path):
    from mcp_video import engine_export

    manifest = _manifest(tmp_path)
    tool = _fake_c2patool(tmp_path)
    output = tmp_path / "exported.mp4"

    def fake_convert(*args, **kwargs):
        output.write_bytes(b"mp4")
        return EditResult(output_path=str(output), operation="convert")

    monkeypatch.setattr("mcp_video.engine_convert.convert", fake_convert)
    monkeypatch.setattr(engine_export, "_validate_input_path", lambda p: p)

    result = engine_export.export_video(
        "input.mp4",
        output_path=str(output),
        format="mp4",
        c2pa_manifest_path=str(manifest),
        c2pa_tool_path=str(tool),
    )

    assert result.c2pa is not None
    assert result.c2pa["status"] == "signed"
    assert result.c2pa["verified"] is True
    assert result.c2pa["trusted"] is True
    assert result.operation == "export"


def test_video_export_threads_c2pa_options(monkeypatch, tmp_path):
    from mcp_video import server_tools_media

    manifest = _manifest(tmp_path)
    tool = _fake_c2patool(tmp_path)
    seen = {}

    def fake_export_video(input_path, **kwargs):
        seen.update(kwargs)
        return EditResult(output_path=str(tmp_path / "out.mp4"), operation="export", c2pa={"status": "signed"})

    monkeypatch.setattr(server_tools_media, "_validate_input_path", lambda p: p)
    monkeypatch.setattr(server_tools_media, "export_video", fake_export_video)

    result = server_tools_media.video_export(
        "input.mp4",
        format="mp4",
        c2pa_manifest_path=str(manifest),
        c2pa_tool_path=str(tool),
        c2pa_signer_path="/opt/kinocut/signer",
    )

    assert result["success"] is True
    assert result["c2pa"]["status"] == "signed"
    assert seen["c2pa_manifest_path"] == str(manifest)
    assert seen["c2pa_tool_path"] == str(tool)
    assert seen["c2pa_signer_path"] == "/opt/kinocut/signer"


def test_client_export_threads_c2pa_options(monkeypatch, tmp_path):
    from mcp_video import Client

    manifest = _manifest(tmp_path)
    tool = _fake_c2patool(tmp_path)
    seen = {}

    def fake_export_video(video, **kwargs):
        seen.update(kwargs)
        return EditResult(output_path=str(tmp_path / "out.mp4"), operation="export", c2pa={"status": "signed"})

    monkeypatch.setattr("mcp_video.client.media._export_video", fake_export_video)

    result = Client().export(
        "input.mp4",
        c2pa_manifest_path=str(manifest),
        c2pa_tool_path=str(tool),
        c2pa_signer_path="/opt/kinocut/signer",
    )

    assert result.c2pa == {"status": "signed"}
    assert seen["c2pa_manifest_path"] == str(manifest)
    assert seen["c2pa_tool_path"] == str(tool)
    assert seen["c2pa_signer_path"] == "/opt/kinocut/signer"


def test_cli_export_parser_accepts_c2pa_options():
    from mcp_video.cli.parser import build_parser

    parser = build_parser()
    args = parser.parse_args(
        [
            "export",
            "input.mp4",
            "--c2pa-manifest",
            "manifest.json",
            "--c2pa-tool",
            "fake-c2patool",
            "--c2pa-signer-path",
            "signer",
        ]
    )

    assert args.c2pa_manifest == "manifest.json"
    assert args.c2pa_tool == "fake-c2patool"
    assert args.c2pa_signer_path == "signer"


@pytest.mark.slow
def test_cli_export_json_can_sign_with_fake_c2patool(sample_video, tmp_path):
    tool = _fake_c2patool(tmp_path)
    manifest = _manifest(tmp_path)
    output = tmp_path / "cli-signed.mp4"

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "mcp_video",
            "--format",
            "json",
            "export",
            sample_video,
            "--output",
            str(output),
            "--c2pa-manifest",
            str(manifest),
            "--c2pa-tool",
            str(tool),
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["success"] is True
    assert payload["operation"] == "export"
    assert payload["c2pa"]["status"] == "signed"
    assert payload["c2pa"]["verified"] is True
    assert payload["c2pa"]["trusted"] is True
    assert payload["c2pa"]["warning_codes"] == []
    serialized = json.dumps(payload["c2pa"])
    assert str(tool) not in serialized
    assert str(manifest) not in serialized
    assert str(tmp_path) not in serialized
    assert "tool" not in payload["c2pa"]
    assert "manifest_path" not in payload["c2pa"]
    assert "signer_path" not in payload["c2pa"]
    assert output.is_file()


@pytest.mark.slow
def test_real_c2patool_signs_when_tool_and_manifest_are_available(sample_video, tmp_path):
    from mcp_video.engine_export import export_video

    c2patool = shutil.which("c2patool")
    manifest = os.environ.get("KINOCUT_C2PA_TEST_MANIFEST")
    signer = os.environ.get("KINOCUT_C2PA_TEST_SIGNER")
    if c2patool is None or not manifest:
        pytest.skip("requires c2patool and KINOCUT_C2PA_TEST_MANIFEST")

    output = tmp_path / "signed.mp4"
    result = export_video(
        sample_video,
        output_path=str(output),
        format="mp4",
        c2pa_manifest_path=manifest,
        c2pa_tool_path=c2patool,
        c2pa_signer_path=signer,
    )

    assert output.is_file()
    assert result.c2pa is not None
    assert result.c2pa["status"] == "signed"
    assert result.c2pa["verified"] is True
    assert result.c2pa["trusted"] in {True, False}
    assert "warning_codes" in result.c2pa
