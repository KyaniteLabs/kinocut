"""Atomic content-addressed storage for private derived artifact bytes."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

from kinocut.errors import MCPVideoError
from kinocut.projectstore import layout, store


@dataclass(frozen=True)
class InstalledArtifact:
    """Identity and private project-relative location of an installed file."""

    artifact_id: str
    location: str


def install_bytes(project: store.Project, content: bytes, *, name: str) -> InstalledArtifact:
    """Atomically install trusted encoder bytes at their canonical hash path."""

    artifact_id = "sha256:" + hashlib.sha256(content).hexdigest()
    relative = layout.artifact_relative_path(artifact_id, name)
    try:
        with store._project_lock(project):
            destination = store.safe_target(project, relative)
            if destination.exists():
                if destination.read_bytes() != content:
                    raise MCPVideoError(
                        "inspection artifact content does not match its identity",
                        error_type="store_error",
                        code="artifact_identity_mismatch",
                    )
            else:
                store._write_atomically(destination, lambda writer: writer.write(content), binary=True)
    except MCPVideoError as exc:
        if exc.code == "artifact_identity_mismatch":
            raise
        raise MCPVideoError(
            "inspection artifact could not be stored",
            error_type="store_error",
            code="artifact_store_failed",
        ) from exc
    except OSError as exc:
        raise MCPVideoError(
            "inspection artifact could not be stored",
            error_type="store_error",
            code="artifact_store_failed",
        ) from exc
    return InstalledArtifact(artifact_id=artifact_id, location=str(relative))
