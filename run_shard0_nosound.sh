#!/bin/bash
cd /tmp/k3clone
.venv0/bin/python - <<'PY' > /tmp/k3clone/shard0_nosound.log 2>&1
from pathlib import Path
import pytest
tests = sorted(Path("tests").rglob("test_*.py"))
selected = [p for p in tests[0::4] if "sound" not in p.name]
print(f"shard 0 minus sound files: {len(selected)} files", flush=True)
raise SystemExit(pytest.main([*(str(p) for p in selected), "-q", "-m", "not slow", "--tb=short", "-rf"]))
PY
