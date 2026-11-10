"""Write or verify the private eval MANIFEST.json (set hash, prompt hash, commit)."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from .prompt import TEMPLATE_VERSION, template_fingerprint


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_manifest(set_path: str | Path, harness_commit: str, catalog_commit: str | None = None) -> dict[str, object]:
    """Return the manifest the protocol freezes before the first model call."""

    path = Path(set_path)
    manifest: dict[str, object] = {
        "dataset_sha256": sha256_file(path),
        "dataset_bytes": path.stat().st_size,
        "prompt_template": {"version": TEMPLATE_VERSION, "sha256": template_fingerprint()},
        "harness_commit": harness_commit,
    }
    if catalog_commit:
        manifest["catalog_commit"] = catalog_commit
    return manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--set", required=True)
    parser.add_argument("--commit", required=True, help="Harness commit SHA")
    parser.add_argument("--catalog-commit", help="kinocut commit SHA the labels were checked against")
    parser.add_argument("--out", required=True)
    args = parser.parse_args(argv)
    manifest = build_manifest(args.set, args.commit, args.catalog_commit)
    Path(args.out).write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    print(json.dumps(manifest, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
