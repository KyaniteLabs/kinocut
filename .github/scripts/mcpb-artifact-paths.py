"""Select one version-matched wheel/bundle pair before emitting CI outputs."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from kinocut.errors import MCPVideoError  # noqa: E402 - standalone CI script bootstraps the checkout path


def candidate_paths(directory: Path, project_file: Path) -> dict[str, str]:
    version = tomllib.loads(project_file.read_text(encoding="utf-8"))["project"]["version"]
    if not isinstance(version, str) or not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", version):
        raise MCPVideoError("MCPB candidate requires a stable release version", error_type="validation_error")
    wheels = sorted(directory.glob("*.whl"))
    bundles = sorted(directory.glob("*.mcpb"))
    if len(wheels) != 1 or len(bundles) != 1:
        raise MCPVideoError("MCPB candidate requires exactly one wheel and one bundle", error_type="validation_error")
    wheel, bundle = wheels[0], bundles[0]
    if not wheel.is_file() or not bundle.is_file():
        raise MCPVideoError("MCPB candidate artifacts must be files", error_type="validation_error")
    wheel_pattern = rf"kinocut-{re.escape(version)}-[A-Za-z0-9_.]+-[A-Za-z0-9_.]+-[A-Za-z0-9_.]+\.whl"
    if not re.fullmatch(wheel_pattern, wheel.name) or bundle.name != f"kinocut-{version}.mcpb":
        raise MCPVideoError("MCPB candidate artifact versions disagree with the project", error_type="validation_error")
    return {"version": version, "wheel_file": wheel.name, "bundle_file": bundle.name}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = candidate_paths(args.directory, ROOT / "pyproject.toml")
    except (OSError, KeyError, ValueError, MCPVideoError) as exc:
        parser.exit(1, f"MCPB candidate selection failed: {exc}\n")
    output = os.environ.get("GITHUB_OUTPUT")
    if output:
        with Path(output).open("a", encoding="utf-8") as target:
            target.write("".join(f"{key}={value}\n" for key, value in result.items()))
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
