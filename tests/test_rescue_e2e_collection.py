"""Cross-platform collection regressions for the rescue end-to-end module."""

from __future__ import annotations

import runpy
import sys
from pathlib import Path


def test_rescue_e2e_collects_without_resource(monkeypatch):
    monkeypatch.setitem(sys.modules, "resource", None)

    namespace = runpy.run_path(
        str(Path(__file__).with_name("test_rescue_e2e.py")),
        run_name="test_rescue_e2e_without_resource",
    )

    assert "test_planning_performance_receipt_has_required_context" in namespace
    assert namespace["_optional_max_rss"]() is None
