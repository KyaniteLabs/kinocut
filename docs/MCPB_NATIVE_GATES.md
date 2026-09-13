# MCPB future native-only bundle gates (#125 / #257)

**Status:** future native-only scope; separate from the staged user-configured-local-access product.

## Acceptance checklist (clean machine)

1. `python scripts/build-mcpb.py` produces `dist/kinocut-*.mcpb`
2. Manifest validates (`mcpb` / schema in repo)
3. Native launcher starts stdio without host Python (when native runtime present)
4. Supply-chain doc: `docs/MCPB_SUPPLY_CHAIN.md`
5. License + signing artifacts reviewed by human
6. Clean-machine install: no network beyond package fetch; doctor passes required deps

## Explicit non-goals for agents

- No unauthorized MCPB registry submit
- No claim of “public native publish” without human gate

## Residual

Native target matrix (macOS/Windows/Linux signed runtimes) remains an infra/human
pipeline item when signing certs and release authority are available.
