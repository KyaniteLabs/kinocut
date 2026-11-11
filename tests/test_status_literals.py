"""Lifecycle status strings live in contract enums, not as scattered literals.

A raw ``"status": "failed"`` write hides a state machine: nothing checks which
moves are legal.  The explicit pattern is ``RenderJobStatus`` plus
``_TRANSITIONS`` in ``kinocut/contracts/trusted_execution.py``.  The package
has zero raw writes; this test keeps it that way.
"""

from __future__ import annotations

import ast
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "kinocut"


def _is_status_key(node: ast.AST | None) -> bool:
    return isinstance(node, ast.Constant) and node.value == "status"


def _is_str(node: ast.AST | None) -> bool:
    return isinstance(node, ast.Constant) and isinstance(node.value, str)


def _is_untyped_dict_call(func: ast.AST) -> bool:
    """``dict(...)`` or ``x.update(...)``; typed model constructors validate their own fields."""
    return (isinstance(func, ast.Name) and func.id == "dict") or (
        isinstance(func, ast.Attribute) and func.attr == "update"
    )


def raw_status_writes(tree: ast.AST) -> list[int]:
    """Line numbers of ``{"status": "x"}``, ``obj["status"] = "x"`` and ``dict(..., status="x")``."""
    lines = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Dict):
            lines += [v.lineno for k, v in zip(node.keys, node.values, strict=True) if _is_status_key(k) and _is_str(v)]
        elif isinstance(node, ast.Assign) and _is_str(node.value):
            lines += [node.lineno for t in node.targets if isinstance(t, ast.Subscript) and _is_status_key(t.slice)]
        elif isinstance(node, ast.Call) and _is_untyped_dict_call(node.func):
            lines += [kw.value.lineno for kw in node.keywords if kw.arg == "status" and _is_str(kw.value)]
    return sorted(lines)


def current_counts() -> Counter[str]:
    counts: Counter[str] = Counter()
    for path in sorted(PACKAGE.rglob("*.py")):
        rel = path.relative_to(PACKAGE).as_posix()
        hits = raw_status_writes(ast.parse(path.read_text(encoding="utf-8"), filename=rel))
        if hits:
            counts[rel] = len(hits)
    return counts


def test_detector_sees_both_write_shapes() -> None:
    tree = ast.parse(
        'a = {"status": "failed"}\nb["status"] = "done"\nc = {"status": s}\n'
        'd = dict(a, status="x")\nd.update(status="y")\nModel(status="typed")\n'
    )
    assert raw_status_writes(tree) == [1, 2, 4, 5]


def test_no_raw_status_writes() -> None:
    counts = current_counts()
    assert not counts, (
        f"Raw status-string writes {dict(counts)}. Use a contracts enum with a transition table "
        "(see RenderJobStatus in kinocut/contracts/trusted_execution.py)."
    )
