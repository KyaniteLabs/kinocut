# Governance

Kinocut is currently maintained as a benevolent-maintainer open source project.

## Decision Model

- The maintainer sets project direction, release timing, and quality gates.
- Contributors are encouraged to open issues or discussions before large changes.
- Pull requests should stay small, testable, and aligned with the existing architecture.
- Security-sensitive reports follow `SECURITY.md`, not public issues.

## Maintainer Responsibilities

- Keep `master` releasable.
- Keep CI green.
- Review issues and pull requests in good faith.
- Prefer boring, reliable implementation over speculative rewrites.
- Protect users from unsafe FFmpeg command construction, unbounded subprocesses, and generated artifact sprawl.

## Contributor Path

1. Start with a bug report, feature request, or discussion.
2. Confirm the change fits the project direction.
3. Add or update tests before changing behavior.
4. Open a pull request with exact validation evidence.

## Scope Boundaries

The project is an MCP-first video editing toolkit. It should not become:

- a hosted SaaS product inside this repo,
- a full GUI video editor,
- a dumping ground for generated media,
- a speculative abstraction layer over every video framework.

Those may be separate projects if they become real products.
