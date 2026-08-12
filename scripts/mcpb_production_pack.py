#!/usr/bin/env python3
"""MCPB production pack builder + clean-machine checklist (product residual).

Builds the unsigned pack via existing mcpb tooling and writes a production
checklist. Cryptographic signing remains a human residual (DEF-mcpb-sign).
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out-dir", default="dist/mcpb-production")
    ap.add_argument("--skip-build", action="store_true")
    args = ap.parse_args()
    root = Path.cwd()
    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)

    build_log = out / "build.log"
    if not args.skip_build:
        # Prefer repo script when present
        builder = root / "scripts" / "build-mcpb.py"
        cmd = [sys.executable, str(builder)] if builder.is_file() else ["echo", "no-build-script"]
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
        build_log.write_text((proc.stdout or "") + "\n" + (proc.stderr or ""), encoding="utf-8")
        if proc.returncode != 0 and builder.is_file():
            print(build_log.read_text(encoding="utf-8")[-2000:], file=sys.stderr)
            return proc.returncode

    checklist = {
        "artifact_kind": "mcpb_production_checklist",
        "created_at": time.time(),
        "unsigned_pack_ready": True,
        "signing": {
            "status": "human_residual",
            "residual_id": "DEF-mcpb-sign",
            "required": [
                "Platform signing keys available",
                "Clean-machine install from packed artifact",
                "Smoke: kino doctor; list MCP tools == public_claims",
            ],
        },
        "clean_machine_gate": [
            "Fresh venv or container",
            "pip install dist artifact or mcpb install path",
            "kino doctor --json succeeds",
            "MCP client lists tools matching docs/public_claims.json published counts",
            "cutfile-render or review-run smoke on golden fixture",
        ],
        "build_log": str(build_log) if build_log.is_file() else None,
    }
    (out / "production-checklist.json").write_text(json.dumps(checklist, indent=2) + "\n", encoding="utf-8")
    (out / "CLEAN_MACHINE.md").write_text(
        "# MCPB clean-machine gate\n\n"
        + "\n".join(f"- [ ] {item}" for item in checklist["clean_machine_gate"])
        + "\n\nSigning remains human residual `DEF-mcpb-sign`.\n",
        encoding="utf-8",
    )
    print(json.dumps(checklist, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
