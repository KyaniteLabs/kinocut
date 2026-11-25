"""Classify changed paths for the CI change-detection job.

The single source of truth for which pathnames count as ``code`` (run the test
matrix) and ``docker`` (rebuild the image). ``.github/workflows/ci.yml`` feeds
the ``git diff --name-only -z`` stream here instead of re-implementing the rules
in bash, so the two can no longer drift.

    git diff --name-only -z BASE HEAD | python3 scripts/ci_scope.py --github-output "$GITHUB_OUTPUT"

Anything unlisted classifies as code (fail open to testing). Empty input
classifies as code as well. ``is_docs_meta_only`` keeps the older stdin/boolean
contract used by ad-hoc checks: every path must match a docs/meta pattern.
"""

import argparse
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

#: Pathnames whose change requires the Python/FFmpeg test matrix.
CODE_GLOBS = (
    "kinocut/*",
    "kinocut_sound/*",
    "plugins/*",
    "tests/*",
    "qa/*",
    "scripts/*",
    "workflows/05-confidence-baseline/*",
    "docs/public_claims.json",
    "README.md",
    "README-PYPI.md",
    "llms.txt",
    "server.json",
    "mcpb/*",
    "npm/*",
    "compat/*",
    "mcp_video.py",
    "pyproject.toml",
    "uv.lock",
    "Dockerfile",
    "Dockerfile.ci",
    ".github/workflows/*",
    ".github/scripts/*",
    ".github/actions/cache-ffmpeg/*",
    ".forgejo/*",
)
#: Pathnames whose change requires rebuilding the CI runner image.
DOCKER_GLOBS = (
    "Dockerfile",
    "Dockerfile.ci",
    "kinocut/*",
    "kinocut_sound/*",
    "mcp_video.py",
    "pyproject.toml",
    "uv.lock",
    ".dockerignore",
    ".github/workflows/ci.yml",
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


def classify(paths: list[str]) -> tuple[bool, bool]:
    """Return ``(code, docker)`` for a changed-path list.

    ``fnmatch`` treats ``*`` as matching across ``/``, exactly like the bash
    ``case`` patterns this replaces, so a nested path such as
    ``kinocut/cli/parser/x.py`` still matches ``kinocut/*``.
    """
    code = False
    docker = False
    for path in paths:
        if any(fnmatch.fnmatch(path, pattern) for pattern in CODE_GLOBS):
            code = True
        if any(fnmatch.fnmatch(path, pattern) for pattern in DOCKER_GLOBS):
            docker = True
    return code, docker


def _read_nul(stream) -> list[str]:
    """Split a NUL-delimited ``git diff -z`` stream; never splits a pathname."""
    data = stream.buffer.read()
    return [path.decode("utf-8", "surrogateescape") for path in data.split(b"\0") if path]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--github-output",
        help="append code=/docker= to this file instead of printing a boolean",
    )
    args = parser.parse_args(argv)
    if args.github_output:
        paths = _read_nul(sys.stdin)
        code, docker = classify(paths)
        for path in paths:
            print(f"changed: {path!r}")
        with open(args.github_output, "a", encoding="utf-8") as handle:
            handle.write(f"code={'true' if code else 'false'}\n")
            handle.write(f"docker={'true' if docker else 'false'}\n")
        return 0
    changed = [line.strip() for line in sys.stdin if line.strip()]
    print("false" if is_docs_meta_only(changed) else "true")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
