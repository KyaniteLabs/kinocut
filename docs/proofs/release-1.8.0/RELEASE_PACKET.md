# Kinocut 1.8.0 release packet

**Status:** Candidate packet. Fresh validation on the final release SHA is required before publication.

## Release identities

- Kinocut / npm / server metadata / staged MCPB manifest: `1.8.0`
- `mcp-video` compatibility shim: `1.6.2`
- Native MCPB: staged/local-only; not published as an external artifact.

## Contributor acknowledgement

Thanks to @betsmayank for the Hyperframes MCP no-TTY initialization fix (#361).

## Historical evidence boundary

`3812 passed, 170 skipped, 10 expected warnings` is recorded pre-R2 evidence only. It is not current QA and cannot be used as final-release proof. Fresh validation is required on the final release SHA.

## Required final-SHA evidence

- Isolated checkout with clean status and exact-SHA verification.
- Durable full-suite log for `python3 -m pytest tests/ -x -q --tb=short`, including exit code, terminal count, and duration.
- Targeted privacy, distribution, doctor, and readiness checks.
- Runtime doctor and affected operator-path evidence.
- Independent read-only APPROVE review covering ancestry, privacy, version parity, contributor acknowledgement, MCPB nonpublication, packet truthfulness, leak scan, and master-diff correctness.

## Privacy boundary

Public benchmark receipts use a fixed allowlist. They exclude raw machine, processor, platform, hostname, operating-system, kernel, notes, status, and unknown capability data.
