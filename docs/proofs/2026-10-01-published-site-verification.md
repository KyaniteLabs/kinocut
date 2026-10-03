# Published site verification — 2026-10-01

Fresh requests at 22:58 UTC used Python's default certificate verification,
bounded responses (2 MiB), and the descriptive user agent
`Kinocut-release-readiness/1.0`.

| Surface | HTTP | Current published stamp | Response SHA256 |
| --- | --- | --- | --- |
| `https://kinocut.dev/` | 200 | JSON-LD `softwareVersion: 1.15.3` | `3674e2b5fa7d93d731400cbb5a59414fba61b92053d9a1dba8a5740ab46d7902` |
| `https://kinocut.dev/llms.txt` | 200 | Latest published release: 1.15.3 (2026-09-25) | `3c9984f89b5aea22b68b2fcceb9ea261afec87ab4dc5169e9350b7f36528bdfc` |

A subsequent request using that same client confirmed the homepage's JSON-LD
and the llms release line. A request using urllib's default user agent returned
403; availability is therefore established for the disclosed verification
client, not every possible client. No certificate checks were disabled.

This supersedes the October 1 proxy-blocked observations for these two URLs.
It addresses the published site-stamp evidence requested in
[issue #479](https://github.com/KyaniteLabs/kinocut/issues/479), using the current
published version rather than the ticket's stale 1.15.1 target. The matching
status update is in [NOW.md](../status/NOW.md).

The 1.16.0 candidate is not published. These responses do not accept candidate
messaging, browser pixels, other site pages, all registry providers, fleet
updates, or the complete Phase-0 exit. The source-of-truth/Phase-0 prerequisites
in [issue #487](https://github.com/KyaniteLabs/kinocut/issues/487) remain separate;
Forgejo work is excluded by the user.
