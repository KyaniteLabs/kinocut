# Security Policy

Kinocut shells out to FFmpeg and handles local media paths, so security reports are taken seriously.

## Supported Versions

Security fixes target the repository's default branch and the latest published package version. Older versions may receive guidance, but fixes are not backported unless a maintainer explicitly announces that support window.

## Reporting a Vulnerability

Please do not open a public issue for vulnerabilities.

Report privately through [GitHub private vulnerability reporting](https://github.com/KyaniteLabs/kinocut/security/advisories/new) and include only the minimum detail needed to establish contact.

Helpful reports include:

- The affected MCP tool, CLI command, or Python API.
- A minimal reproduction using non-sensitive media.
- The expected impact, such as command injection, path traversal, unsafe file overwrite, denial of service, dependency compromise, or secret exposure.
- Your OS, Python version, FFmpeg version, and Kinocut version.

## Response Expectations

- Initial acknowledgment target: within 3 business days.
- Triage/update target: within 7 business days.
- Fix timeline depends on severity and complexity.

Confirmed vulnerabilities will be fixed in a private branch when possible, then disclosed after a patched release or clear mitigation is available.

## Security Scope

In scope:

- FFmpeg filter injection or unsafe command construction.
- Path validation bypasses, null-byte handling, and unsafe overwrites.
- Server-side validation gaps that allow resource exhaustion or unexpected local file access.
- Dependency or packaging issues that affect normal installation or runtime.

Out of scope:

- Reports requiring malicious local code execution before using Kinocut.
- Issues only affecting third-party FFmpeg builds outside this project.
- Denial-of-service reports that require unrealistic media sizes beyond documented limits.
