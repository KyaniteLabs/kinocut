# Stream-to-shorts operator guide

Local-only path from a **saved shorts plan** through human review, platform render,
and portable packages. **No posting, scheduling, or authentication.**

Development tip only until a published release claims these stages. See
[`public_claims.json`](public_claims.json) for published vs tip surface counts.

## Stages (canonical)

| Stage | CLI | MCP | Client |
| --- | --- | --- | --- |
| Show proposals (source-free) | `kino shorts-plan-show PLAN` | `shorts_plan_show` | `client.shorts_plan_show` |
| Record review | `kino shorts-review PLAN --candidate-id ID --decision DECISION` | `shorts_review` | `client.shorts_review` |
| Render drafts | `kino shorts-render PLAN --candidate-id ID` | `shorts_render` | `client.shorts_render` |
| Package drafts | `kino shorts-package PLAN --candidate-id ID` | `shorts_package` | `client.shorts_package` |

Namespace aliases: `kino shorts plan-show|review|render|package ...`.

`PLAN` is a path to one plan JSON file **or** a directory that contains exactly one
plan. Ambiguous directories fail closed.

## Decision vocabulary

`--decision` accepts a bare action or a JSON object:

- `approve` — unlock render for that candidate
- `reject` — clear approval
- `trim` / `title_hook_edit` / sensitivity edits — mutate effective bounds/metadata;
  still need a current `approve` before render

Render and package both call `resolve_approved_candidate` and fail with
`shorts_review_required` when approval is missing.

## Example (after a plan exists)

```bash
# 1) Source-free proposal review (does not re-ingest the long-form source)
kino shorts-plan-show /path/to/plans --format json

# 2) Human decision
kino shorts-review /path/to/plans \
  --candidate-id candidate_01 \
  --decision approve

# 3) Platform drafts (youtube-shorts + instagram-reel by default plan platforms)
kino shorts-render /path/to/plans --candidate-id candidate_01

# 4) Portable packages (video, captions.srt, thumbnail, metadata, manifest)
kino shorts-package /path/to/plans --candidate-id candidate_01
```

Python:

```python
from kinocut import Client

client = Client()
print(client.shorts_plan_show("/path/to/plans"))
client.shorts_review("/path/to/plans", candidate_id="candidate_01", decision="approve")
client.shorts_render("/path/to/plans", candidate_id="candidate_01")
client.shorts_package("/path/to/plans", candidate_id="candidate_01")
```

## Fail-closed behavior

| Code | Meaning | Recovery |
| --- | --- | --- |
| `shorts_plan_not_found` / `shorts_plan_ambiguous` | Plan path missing or not unique | Point at one exact plan file/dir |
| `shorts_review_required` | No current approve | `shorts-review ... --decision approve` |
| `shorts_package_render_required` | No `RenderRecord`s | Run `shorts-render` first |
| `source_checksum_mismatch` | Package video digest mismatch | Re-render, then package |

Rerenders with unchanged digest + present files report `cache_hit: true`.

## Human gates (not automated)

Automated metrics (duration, loudness targets, package checksums, visual smoke) do
**not** replace:

1. **Listening** — ear-check each platform draft and any boundary WAVs from acceptance.
2. **Visual** — confirm crop, captions, and thumbnail still read on a phone-sized frame.

Record listening/visual approval outside this tool surface. Do not mark a release
candidate ready while those human gates are open.

## Acceptance proof (issue #407)

A full G004 acceptance pass on the licensed multi-minute fixture is a separate
receipt under `docs/proofs/` after automation + human listening complete. This doc
only documents the commands; it does not claim that receipt exists yet.
