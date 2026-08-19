# First agent tasks

For contributors and agents improving Kinocut docs/examples without large engine work.

## Task 1 — Receipt-producing workflow example

Add an example under `examples/` or `workflows/` that:

1. Uses only public Client/CLI APIs
2. Writes a Video Receipt JSON
3. Documents absolute-path usage and human-review pending
4. Does not add flaky private media to git

## Task 2 — Prompt pack entry

Add one prompt to [PROMPTS.md](PROMPTS.md) that is deterministic-leaning, Kinocut-only, and ends with quality + human review.

## Task 3 — 360 assembly dry-run (master tip)

Using a **synthetic** 2:1 fixture (do not commit private X4 media): propose a `360_assembly_plan`, show cameras, refuse `.insv`, and document that render needs approve. Follow [360_ASSEMBLY.md](360_ASSEMBLY.md).

## Task 3b — Product matte dry-run

Follow [PRODUCT_MATTE.md](PRODUCT_MATTE.md). Run
`kino --format json hyperframes-remove-background --info` (no input file).
Confirm `models.birefnet-general.subject` is `products-and-objects` and that
`--info` did not download weights. Dry-run
`examples/product-matte/layers.json` only if the cutout/plate files are
present locally — do not commit private catalog media.

## Task 4 — Failure example

Document one fail-closed path in [FAILURE_EXAMPLES.md](FAILURE_EXAMPLES.md) with expected error type.

## Task 5 — Directory board update

After verifying a live directory page, update [DIRECTORY_STATUS.md](DIRECTORY_STATUS.md) with date.

## Rules

- No secrets or private media paths in commits
- Run `pytest tests/test_public_claims.py -q` if you touch claims/README/llms
- Design system changes are out of scope unless asked

See [CONTRIBUTING.md](../CONTRIBUTING.md) and [GOLDEN_PATH.md](GOLDEN_PATH.md).
