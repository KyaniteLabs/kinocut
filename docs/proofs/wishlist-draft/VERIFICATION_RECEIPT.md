# Wishlist draft verification receipt

**Receipt state:** pre-PR documentation checkpoint

**Source snapshot:** `c88f8efa21709d5d073ddab6667ffa3def64ee4f`

**Documentation-complete integration verified:** `7911d1ed10ebbc047356a525d8980b29a7962fa1`

**Release state:** prohibited

This receipt is intentionally narrow. It records checks run for the documentation/public-safety
unit and lists the gates the publication controller must run on the final integrated commit. It
does not promote task-local or older-commit test output into current proof.

## Checks recorded by this documentation unit

| Gate | Command | Result |
| --- | --- | --- |
| Markdown diff hygiene | `git diff --check` | pass |
| Public-surface contract | `python3 -m pytest tests/test_public_surface.py -q --tb=short` | pass: 25 tests |
| Canonical import alias | `python3 -c "import kinocut, mcp_video; assert kinocut.Client is mcp_video.Client"` | pass |
| Forbidden artifacts | `python3 .github/scripts/check-forbidden-artifacts.py` | pass |
| Repository readiness | `python3 scripts/repo-readiness-audit.py` | pass with expected uncommitted/unpublished-branch warnings |
| Professional/leak audit | `./scripts/git-professional-audit.sh` | expected pre-push failure: isolated branch has no upstream; integrity and branch checks pass |

The professional audit must be rerun after the publication branch is committed and its upstream is
configured. The current failure is recorded rather than hidden; it is not a content or leak finding.

## Integrated verification recorded by the controller

The following gates ran on integration commit
`7911d1ed10ebbc047356a525d8980b29a7962fa1` before this receipt-only update:

| Gate | Result |
| --- | --- |
| Full repository suite | `3046 passed, 15 skipped, 10 warnings in 569.02s` |
| Architecture and public surface | `32 passed` |
| Ruff | pass |
| Canonical and compatibility imports | pass |
| Diff hygiene | pass |
| Forbidden tracked artifacts | pass |
| Repository readiness | pass |
| Gitleaks working-tree scan | pass; no leaks found |
| Public documentation metadata scan | pass |
| Professional audit | 0 failures; three workspace/configuration warnings documented below |

The professional-audit warnings were: the durable branch is intentionally ahead of its upstream,
six unrelated local branches track deleted remotes, and `init.defaultBranch` is unset. They do not
change the draft contents. Unrelated branches were not pruned or rewritten during this task.

The final publication branch is a sanitized squash with a different commit identity. The
publication controller must rerun the full gate on that exact commit and report the result in the
draft PR; this integration receipt must not be represented as proof for a different tree.

## Required final integrated gates

Before the draft PR is described as test-green, the publication controller must run these on the
exact publication commit and replace this section with timestamped results:

```bash
python3 -m pytest tests/ -x -q --tb=short
python3 -c "import kinocut, mcp_video; assert kinocut.Client is mcp_video.Client"
python3 -m ruff check kinocut tests
git diff --check upstream-github/master...HEAD
python3 .github/scripts/check-forbidden-artifacts.py
python3 scripts/repo-readiness-audit.py
./scripts/git-professional-audit.sh
```

The receipt must include the exact commit SHA, test totals, skips/warnings, elapsed time, and any
known limitations. A green result on a different commit is supporting history, not completion
evidence.

## Human review gate

No automated receipt makes generated media publishable. Release artifacts still require explicit
human visual and audio review bound to their exact hashes. This repository-level receipt also does
not authorize a release action.
