"""Lifecycle status strings live in contract enums, not as scattered literals.

A raw ``"status": "failed"`` write hides a state machine: nothing checks which
moves are legal.  The explicit pattern is ``RenderJobStatus`` plus
``_TRANSITIONS`` in ``kinocut/contracts/trusted_execution.py``.  This ratchet
pins today's raw writes per module.  A module may only go down; when you
convert one to an enum, lower (or delete) its entry here.
"""

from __future__ import annotations

import ast
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "kinocut"

# Raw status-string writes known on origin/master; shrink only.
ALLOWED = {
    "c2pa.py": 1,
    "intent/broll.py": 1,
    "product/shorts_flow.py": 8,
    "product/shorts_package.py": 2,
    "product/shorts_render.py": 2,
    "product/shorts_review.py": 1,
    "server_tools_advanced.py": 4,
    "still_plates/edit.py": 2,
    "still_plates/grade.py": 1,
    "still_plates/match.py": 1,
    "still_plates/package.py": 1,
    "te/hooks.py": 1,
    "te/sphere_director.py": 1,
    "te/sphere_plan.py": 3,
    "te/sphere_render.py": 1,
}


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


def test_raw_status_writes_only_shrink() -> None:
    counts = current_counts()
    grew = {f: n for f, n in counts.items() if n > ALLOWED.get(f, 0)}
    stale = {f: (n, counts.get(f, 0)) for f, n in ALLOWED.items() if counts.get(f, 0) < n}
    assert not grew, (
        f"New raw status-string writes {grew}. Use a contracts enum with a transition table "
        "(see RenderJobStatus in kinocut/contracts/trusted_execution.py)."
    )
    assert not stale, f"Ratchet can go down {stale}: lower ALLOWED to the new count."
