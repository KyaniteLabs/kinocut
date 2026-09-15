"""Classify a changed-path list as code ("true") or docs/meta-only ("false").

Feeds the CI path filter for test-ffmpeg-matrix and test-slow; stdin carries
`git diff --name-only <base> HEAD`. The safe-skip set is derived, not guessed:
none of the ffmpeg-matrix test files (test_engine_composite_layers,
test_server_tools_composite_layers, test_workflow_golden, test_engine_overlay,
test_rescue_e2e), their conftest chain, or any slow-marked test reads the paths
below, while every docs-bound test (test_projectstore_threat_model,
test_kinocut_sound_s15_stop, test_public_claims) lives in the not-slow shards
that run on every pipeline — so skipping the matrix and slow suite on these
paths cannot mask a failure. Anything unlisted (all code, tests, manifests,
assets, and .forgejo/**) classifies as code. Empty input fails open.
"""

import fnmatch
import sys

SAFE_SKIP = (
    "docs/*",
    "*.md",
    "LICENSE",
    "LICENSE.*",
    ".gitignore",
    ".editorconfig",
    ".gitattributes",
    "robots.txt",
    "sitemap.xml",
    "og-social-preview.png",
)


def is_docs_meta_only(paths: list[str]) -> bool:
    if not paths:
        return False
    for path in paths:
        if path.endswith(".py") or path.startswith(".forgejo/"):
            return False
        if not any(fnmatch.fnmatch(path, pattern) for pattern in SAFE_SKIP):
            return False
    return True


if __name__ == "__main__":
    changed = [line.strip() for line in sys.stdin if line.strip()]
    print("false" if is_docs_meta_only(changed) else "true")
