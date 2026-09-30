# PR validation and publication scope

The user authorized banking the reviewed changes in commits and creating a PR.
This document records validation separately from published-package status and
from contributor draft PRs; those draft PRs were reviewed and adapted, not merged.
See [the backlog review](github-backlog/2026-09-30/REPORT.md) and
[Unreleased changes](../../CHANGELOG.md).

## Earlier integration checkpoint

At base `a820bd42205e43ca81eebc435e8529b2d0d42fcc`, the frozen local integration
checkpoint passed **7,320 tests, 183 skipped, 8 warnings** in 899.29 seconds.
[Recorded command and scope](github-backlog/2026-09-30/validation.json) and
[full log](github-backlog/2026-09-30/full-suite.log) retain that evidence.
Focused counts overlap the full suite and must not be added to it. Optional skips
are not validation of the missing backends.

## Final source inventory

The [PR checkpoint allocation](runtime-allocation/pr-checkpoint/allocation.json)
records 624 runtime files, 1,431 tracked paths (1,515 inventoried paths including
unignored new files), and source shares of **96.9297% deterministic, 2.6400% prose,
0.4303% traditional ML**. These are source-byte classifications, not execution
cost, inference frequency or measured quality. Host skill prose is separate.
The review branch is `codex/kinocut-reliability-and-backlog`.

## Final publication gate

The required frozen-tree gate passed **7,390 tests, 185 skipped, 8 warnings**
in 1,003.32 seconds, exit 0. Command:

```sh
UV_CACHE_DIR=/workspace/.cache/uv npm_config_cache=/workspace/.cache/npm .venv/bin/python -m pytest tests/ -x -q --tb=short
```

[Final log](runtime-allocation/pr-checkpoint/full-suite.log) and
[structured result](runtime-allocation/pr-checkpoint/validation.json) retain the
outcome. Changed Python files passed Ruff; whitespace checks and the canonical
`kinocut.Client is mcp_video.Client` import check passed. The implementation
commit is `2ced642928ac93423fc6d92a260f7c4503919aaa`. Documentation-only publication metadata follows separately.

Native HTTPS Git publication passed its dry run. GitHub API requests currently
return `Forbidden`; the PR creation outcome is reported separately from branch
publication. [Review branch comparison](https://github.com/KyaniteLabs/kinocut/compare/master...codex/kinocut-reliability-and-backlog?expand=1).
This evidence does not assert a submitted PR, remote CI success or a merge.

Final scope includes staged trim/speed failure preservation, finite trim-time
validation, and canonical Client mixing/ducking aliases. These do not extend
transactional publication to every engine writer or add MCP/CLI tool names.
