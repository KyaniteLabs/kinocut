"""Optional extra + ONNX session for product/object cutouts."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ..errors import BackendUnavailableError, MCPVideoError

_INSTALL = 'pip install "kinocut[object-matte]"'
_DOCS = "docs/PRODUCT_MATTE.md"


def require_object_matte_deps() -> None:
    """Fail closed when the object-matte extra is missing."""
    try:
        import numpy  # noqa: F401
        import onnxruntime  # noqa: F401
        from PIL import Image  # noqa: F401
    except ImportError as exc:
        raise MCPVideoError(
            f"Product/object cutouts require {_INSTALL} "
            f"and the pinned birefnet-general weights. {exc}. "
            f"People cutouts: omit --model. Guide: {_DOCS}.",
            error_type="dependency_error",
            code="missing_object_matte",
            suggested_action={
                "auto_fix": False,
                "description": f"Run: {_INSTALL} for products, or omit --model for people.",
            },
            docs_url=_DOCS,
        ) from None


def providers_for_device(device: str) -> list[str]:
    """Map Kinocut device names to ONNX Runtime execution providers."""
    import onnxruntime as ort

    available = list(ort.get_available_providers())
    if device in {"auto", "cpu"}:
        return ["CPUExecutionProvider"]
    wanted = {"coreml": "CoreMLExecutionProvider", "cuda": "CUDAExecutionProvider"}.get(device)
    if wanted is None:
        raise MCPVideoError(
            f"Unsupported object-matte device {device!r}. Use auto, cpu, coreml, or cuda.",
            error_type="validation_error",
            code="invalid_parameter",
            docs_url=_DOCS,
        )
    if wanted not in available:
        raise BackendUnavailableError(
            f"device={device} needs ONNX Runtime {wanted}. Available: {available}. Guide: {_DOCS}.",
            docs_url=_DOCS,
        )
    return [wanted]


def make_session(weights: Path, device: str) -> tuple[Any, list[str]]:
    """Create an ONNX inference session. device=auto uses CPU in v1."""
    import onnxruntime as ort

    providers = providers_for_device(device)
    session = ort.InferenceSession(str(weights), providers=providers)
    return session, list(session.get_providers())
