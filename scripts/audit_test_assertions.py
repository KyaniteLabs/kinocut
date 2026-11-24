"""Audit tests for direct or delegated assertions; --run-delegated executes helper-only cases.

This is a review aid, not a proof of assertion quality: only explicit assertions,
exception/warning expectations, mock assertions, and calls to local checked helpers count.
Run from the checkout root: python scripts/audit_test_assertions.py --run-delegated.
"""

from __future__ import annotations

import argparse
import ast
import subprocess
import sys
from collections import Counter
from pathlib import Path


def _observations(function):
    calls = set()
    pending = list(function.body)
    nested = {}
    while pending:
        node = pending.pop()
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            nested[node.name] = node
            continue
        if isinstance(node, (ast.ClassDef, ast.Lambda)):
            continue
        if isinstance(node, ast.Assert) or (
            isinstance(node, ast.Raise)
            and isinstance(node.exc, ast.Call)
            and ast.unparse(node.exc.func) == "AssertionError"
        ):
            return True, calls
        if isinstance(node, ast.Call):
            name = ast.unparse(node.func)
            if name in {"pytest.raises", "pytest.warns", "pytest.fail"} or ".assert_" in name:
                return True, calls
            calls.add(name)
        pending.extend(ast.iter_child_nodes(node))
    for name in calls & nested.keys():
        observed, inner_calls = _observations(nested[name])
        if observed:
            calls.add("<checked helper>")
        calls.update(inner_calls)
    return False, calls


def classify(path):
    nodes = {}

    def visit(items, prefix=""):
        for node in items:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                nodes[prefix + node.name] = _observations(node)
            elif isinstance(node, ast.ClassDef):
                visit(node.body, node.name + "::")

    module = ast.parse(path.read_text(encoding="utf-8"))
    visit(module.body)
    imported_assertions = {
        alias.asname or alias.name
        for node in module.body
        if isinstance(node, ast.ImportFrom)
        for alias in node.names
        if alias.name.startswith("assert_")
    } - nodes.keys()
    direct = {name for name, (observed, _) in nodes.items() if observed}
    checked = direct.copy()
    while True:
        previous = checked.copy()
        for name, (_, calls) in nodes.items():
            scope = name.rpartition("::")[0]
            if "<checked helper>" in calls or any(
                call in imported_assertions
                or (scope + "::" + call[5:] if call.startswith("self.") else call) in previous
                for call in calls
            ):
                checked.add(name)
        if previous == checked:
            break
    for name in nodes:
        if name.split("::")[-1].startswith("test_"):
            yield f"{path}::{name}", "direct" if name in direct else "delegated" if name in checked else "unverified"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-delegated", action="store_true")
    args = parser.parse_args()
    results = dict(row for path in sorted(Path("tests").rglob("test_*.py")) for row in classify(path))
    for node, kind in results.items():
        if kind != "direct":
            print(f"{kind}: {node}")
    counts = Counter(results.values())
    print(f"direct={counts['direct']}, delegated={counts['delegated']}, unverified={counts['unverified']}", flush=True)
    delegated = [node for node, kind in results.items() if kind == "delegated"]
    if args.run_delegated and delegated:
        status = subprocess.call([sys.executable, "-m", "pytest", "-q", *delegated])
        if status:
            return status
    return int(bool(counts["unverified"]) or not results)


if __name__ == "__main__":
    raise SystemExit(main())
