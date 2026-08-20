"""Kinocut-owned product/object cutouts (birefnet-general ONNX)."""


def run_object_matte(*args, **kwargs):
    """Lazy so a missing extra raises dependency_error, not ImportError."""
    from .api import run_object_matte as _run

    return _run(*args, **kwargs)


__all__ = ["run_object_matte"]
