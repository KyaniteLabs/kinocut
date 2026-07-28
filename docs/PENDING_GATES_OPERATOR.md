# Kinocut pending gates: the easy version

Run this whenever you want the current answer:

```bash
./scripts/kinocut-pending.py
```

It is read-only. It does not remove labels, publish packages, sign artifacts,
submit directories, or change Forgejo.

To print only the reply form:

```bash
./scripts/kinocut-pending.py --copy-paste
```

## What is actually waiting on you

### 1. Runner activation — #110

Needed:

- a working Docker daemon;
- Forgejo runner-admin access;
- approval to register the runner labels from `docs/CI_RUNNER_TOPOLOGY.md`.

Reply with:

```text
Kinocut: Docker works and runner-admin access is available. Activate #110.
```

### 2. Native MCPB — #125 and #257

Needed:

- approved FFmpeg/runtime source and license family;
- macOS, Linux, and Windows clean-machine runners;
- later, exact signing and release authority.

Reply with:

```text
Kinocut MCPB runtime family approved: <name/source>.
Available clean-machine runners: <list>.
No release or signing authority yet.
```

### 3. Post-release Waves D–H

Do not remove `blocked:post-release` because the code looks ready. Remove it
only when the real milestone has happened.

Reply with:

```text
Kinocut post-release milestone is genuinely satisfied.
Remove the post-release gates and continue with Wave D.
```

### 4. Publishing and directory work — #88

Authorization must name the exact action. Examples:

```text
Authorize Smithery submission only. Do not tag or publish packages.
```

```text
Authorize tag vX.Y.Z and PyPI only. No npm, signing, or directory submissions.
```

Silence or a broad “continue” is not release authority.

### 5. Real-user evidence — #92

Synthetic tests do not count. When real conversations exist, provide links or
short notes. The campaign can organize and summarize them but will not invent
users, quotes, listening sessions, or adoption.

## One reply that covers everything

Copy, fill in, and send:

```text
Kinocut authority update:
- Post-release milestone is genuinely satisfied: YES / NO
- Remove blocked:post-release labels now: YES / NO
- Runner-admin access and working Docker are available: YES / NO
- Approved MCPB runtime/source family: <name or NOT YET>
- Release actions authorized: NONE / <exact actions>
- Real-user evidence available: NONE / <links or notes>
```

If an answer is `NO` or `NOT YET`, the board stays honest and nothing unsafe
happens.
