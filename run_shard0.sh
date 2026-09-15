#!/bin/bash
cd /tmp/k3clone
.venv0/bin/python - <<'PY' > /tmp/k3clone/shard0_local.log 2>&1
from pathlib import Path
import pytest
tests = sorted(Path("tests").rglob("test_*.py"))
selected = tests[0::4]
print(f"shard 0: {len(selected)} files", flush=True)
raise SystemExit(pytest.main([*(str(p) for p in selected), "-q", "-m", "not slow", "--tb=short", "-rf"]))
PY
