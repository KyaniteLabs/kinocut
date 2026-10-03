"""Optional approved-icon packaging; synthetic PNGs remain test-only."""

from __future__ import annotations

import importlib.util
import json
import os
import stat
from types import SimpleNamespace
import zipfile
import zlib
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]


def _load(path: str):
    spec = importlib.util.spec_from_file_location("mcpb_icon_test_helper", ROOT / path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _builder():
    return _load("scripts/build-mcpb.py")


def _ci_helper():
    return _load(".github/scripts/mcpb-ci.py")


def _png_chunk(kind: bytes, body: bytes) -> bytes:
    return len(body).to_bytes(4, "big") + kind + body + zlib.crc32(kind + body).to_bytes(4, "big")


def _tiny_png(width: int = 1, height: int = 1) -> bytes:
    """Safe structural fixture; never shipped as product artwork."""
    header = width.to_bytes(4, "big") + height.to_bytes(4, "big") + bytes([8, 6, 0, 0, 0])
    return (
        b"\x89PNG\r\n\x1a\n"
        + _png_chunk(b"IHDR", header)
        + _png_chunk(b"IDAT", zlib.compress(b"\0\xff\0\0\xff"))
        + _png_chunk(b"IEND", b"")
    )


def _icon_sources(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    builder = _builder()
    manifest = builder._load_manifest()
    manifest["icon"] = "icon.png"
    staged = tmp_path / "mcpb"
    (staged / "server").mkdir(parents=True)
    (staged / "README.md").write_text("fixture")
    (staged / "server/launcher.js").write_text("fixture")
    (staged / "manifest.json").write_text(json.dumps(manifest))
    (staged / "icon.png").write_bytes(_tiny_png())
    monkeypatch.setattr(builder, "MCPB_DIR", staged)
    return builder, staged, manifest


def test_optional_icon_is_referenced_validated_and_audited(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    builder, staged, manifest = _icon_sources(tmp_path, monkeypatch)
    assert builder.validate_manifest(manifest) == []
    bundle = builder.build_bundle(tmp_path / "dist")
    receipt = builder.audit_bundle(bundle)
    assert receipt["archive_inventory"] == ["README.md", "icon.png", "manifest.json", "server/launcher.js"]
    with zipfile.ZipFile(bundle) as archive:
        assert json.loads(archive.read("manifest.json"))["icon"] == "icon.png"
        assert archive.read("icon.png") == (staged / "icon.png").read_bytes()
    extracted = tmp_path / "extracted"
    assert _ci_helper()._extract(bundle, extracted) == receipt["archive_inventory"]
    assert (extracted / "icon.png").read_bytes() == _tiny_png()


@pytest.mark.parametrize(
    "value",
    [None, True, ["icon.png"], "/icon.png", "../icon.png", "server/icon.png", "icon.jpg", "ICON.PNG", "icon.png\0"],
)
def test_icon_manifest_rejects_every_non_allowlisted_reference(tmp_path, value):
    from kinocut.errors import MCPVideoError

    builder = _builder()
    manifest = builder._load_manifest()
    manifest["icon"] = value
    with pytest.raises(MCPVideoError) as caught:
        builder.validate_manifest(manifest, check_sources=False)
    assert caught.value.error_type == "validation_error" and caught.value.code == "invalid_mcpb_icon"


@pytest.mark.parametrize(
    "damage",
    [
        "missing",
        "symlink",
        "directory",
        "oversize",
        "signature",
        "zero_width",
        "large_height",
        "crc",
        "truncated",
        "trailing",
        "no_data",
    ],
)
def test_icon_source_fails_closed_with_redacted_typed_error(tmp_path, monkeypatch, damage):
    from kinocut.errors import MCPVideoError

    builder, staged, _ = _icon_sources(tmp_path, monkeypatch)
    icon = staged / "icon.png"
    if damage in {"missing", "symlink", "directory"}:
        icon.unlink()
        if damage == "symlink":
            outside = tmp_path / "private-artwork.png"
            outside.write_bytes(_tiny_png())
            icon.symlink_to(outside)
        elif damage == "directory":
            icon.mkdir()
    elif damage == "oversize":
        with icon.open("wb") as handle:
            handle.truncate(builder.MAX_ICON_BYTES + 1)
        monkeypatch.setattr(builder, "_validate_icon", lambda data: pytest.fail("oversize source was read"))
    else:
        data = {
            "signature": b"private-artwork",
            "zero_width": _tiny_png(width=0),
            "large_height": _tiny_png(height=builder.MAX_ICON_DIMENSION + 1),
            "crc": _tiny_png()[:29] + b"bad!" + _tiny_png()[33:],
            "truncated": _tiny_png()[:-1],
            "trailing": _tiny_png() + b"private-artwork",
            "no_data": _tiny_png()[:33] + _png_chunk(b"IEND", b""),
        }[damage]
        icon.write_bytes(data)
    with pytest.raises(MCPVideoError) as caught:
        builder.build_bundle(tmp_path / "dist")
    assert caught.value.code == "invalid_mcpb_icon"
    assert "private" not in str(caught.value) and str(tmp_path) not in str(caught.value)
    assert not (tmp_path / "dist").exists()


@pytest.mark.skipif(os.name == "nt", reason="POSIX FIFO")
def test_icon_fifo_is_rejected_without_opening(tmp_path, monkeypatch):
    from kinocut.errors import MCPVideoError

    builder, staged, _ = _icon_sources(tmp_path, monkeypatch)
    (staged / "icon.png").unlink()
    os.mkfifo(staged / "icon.png")
    monkeypatch.setattr(builder.os, "open", lambda *args: pytest.fail("FIFO was opened"))
    with pytest.raises(MCPVideoError) as caught:
        builder.build_bundle(tmp_path / "dist")
    assert caught.value.code == "invalid_mcpb_icon"


@pytest.mark.parametrize("case", ["unreferenced", "missing", "oversize", "invalid", "symlink"])
def test_archive_icon_must_match_manifest_and_pass_bounded_admission(tmp_path, case):
    from kinocut.errors import MCPVideoError

    builder = _builder()
    manifest = builder._load_manifest()
    if case == "unreferenced":
        manifest.pop("icon", None)
    else:
        manifest["icon"] = "icon.png"
    bundle = tmp_path / "icon.mcpb"
    with zipfile.ZipFile(bundle, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("manifest.json", json.dumps(manifest))
        archive.writestr("README.md", "fixture")
        archive.writestr("server/launcher.js", "fixture")
        if case != "missing":
            data = (
                b"x" * (builder.MAX_ICON_BYTES + 1)
                if case == "oversize"
                else b"invalid"
                if case == "invalid"
                else _tiny_png()
            )
            member = zipfile.ZipInfo("icon.png")
            if case == "symlink":
                member.create_system = 3
                member.external_attr = (stat.S_IFLNK | 0o777) << 16
            archive.writestr(member, data)
    with pytest.raises(MCPVideoError) as caught:
        builder.audit_bundle(bundle)
    assert caught.value.code == "invalid_mcpb_icon"


def test_icon_growth_after_stat_is_read_only_to_cap_plus_one(tmp_path, monkeypatch):
    from kinocut.errors import MCPVideoError

    builder, staged, _ = _icon_sources(tmp_path, monkeypatch)
    with (staged / "icon.png").open("wb") as handle:
        handle.truncate(builder.MAX_ICON_BYTES * 2)
    original = builder.os.fstat
    monkeypatch.setattr(builder.os, "fstat", lambda fd: SimpleNamespace(st_mode=original(fd).st_mode, st_size=0))
    sizes = []
    validator = builder._validate_icon

    def record(data):
        sizes.append(len(data))
        validator(data)

    monkeypatch.setattr(builder, "_validate_icon", record)
    with pytest.raises(MCPVideoError) as caught:
        builder.build_bundle(tmp_path / "dist")
    assert caught.value.code == "invalid_mcpb_icon"
    assert sizes == [builder.MAX_ICON_BYTES + 1]
