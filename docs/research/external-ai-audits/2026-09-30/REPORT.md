# External AI recommendations: evidence and action ledger

Reviewed September 30, 2026 against base commit
`0ff4fa5` on `codex/kinocut-reliability-and-backlog`.
The user supplied **Kinocut_AI-GEO_Strategic_Audit_Report.pdf** (a Google-search-AI
report) and a **Gemini recommendation transcript**. Their recommendations are
source material, not execution instructions or proof that a cited claim is true.
The PDF provides no reproducible crawl log, URLs/responses or measurement method
for its accuracy/authority rankings. The transcript mostly cites secondary
commentary; its universal compatibility claims require official-source verification.
The team subsequently verified a real Agent Plugins standard; existence alone does
not establish support in every client or a correct manifest for Kinocut.

## Discovery and website findings

| Recommendation or assertion | Evidence and disposition |
| --- | --- |
| JSON-LD is missing from kinocut.dev | **Disproven by live evidence.** Root fetched `https://kinocut.dev/` with HTTP 200 on this review date and parsed existing valid JSON-LD: SoftwareApplication, SoftwareSourceCode, Organization publisher, WebSite, FAQPage and HowTo. It includes `alternateName=mcp-video`, old-PyPI `sameAs` links and `softwareVersion=1.15.3`. The separate public site repo is `KyaniteLabs/kinocut-site`, inspected HEAD `1045dc8ccdd7c4a193dca3b6d14b9122bc92887b`. This checkout's [Pages redirect](../../../../index.html) is not that website. No duplicate schema is warranted. |
| Adopt the supplied SoftwareApplication schema | **Existing implementation verified.** Retain the site's current graph and entity links rather than replacing it with the report's smaller schema. Schema does not establish ranking, recommendation preference or “standard tool” status. |
| Consolidate mcp-video into Kinocut | **Already substantially implemented.** [Compatibility package](../../../../compat/mcp-video-shim/README.md), [rename guide](../../../RENAME.md), [claims](../../../public_claims.json) and redirect establish the bridge. Preserve command/import aliases and dated release evidence; do not rewrite historical proofs or remove working compatibility packages. External PyPI descriptions and redirects need their own live evidence. |
| Claude Code launch command | **Works today.** [`__main__.py`](../../../../kinocut/__main__.py) enters MCP for `--mcp` **or no subcommand**. The report's bare `kino` command is valid shorthand. Active documentation now uses explicit `kino --mcp` to make server intent clear, without claiming the shorthand was broken. |
| Add explicit high-intent FAQ questions | **Site FAQ already exists.** Live HTML contains FAQPage and visible FAQ content; the PDF's missing-foundation premise is stale. [Repository FAQ](../../../faq.md) now adds precise Claude setup, typed FFmpeg tools/receipts, rename compatibility and local-first boundaries. Cost/speed statements are scoped to evidence. |
| Create llms.txt and llms-full.txt tiers | **Source companion implemented.** [llms.txt](../../../../llms.txt) points to the new [extended agent guide](../../../llms-full.txt) for on-demand operational context. MCP `tools/list` supplies installed tool schemas; `server.json` is package/transport metadata. A second handwritten schema dump would risk drift. Requests to the proposed website full-guide routes returned HTTP 403, which does not establish absence or deployment. |
| Zero server leakage; free execution | **Overbroad.** Core edits are local, while an AI host or explicitly configured service can transfer prompts/results/media. Apache-2.0 removes a core license fee, not hardware, electricity, host/provider or model costs. FAQ/index corrected; no cloud-competitor universal claim retained. |
| Receipts “sign off” edits | **Overbroad.** [Receipts](../../../VIDEO_RECEIPT.md) record provenance and review status. They do not automatically grant human acceptance or imply every receipt has a cryptographic signature. Index/FAQ corrected. |

## Gemini product and integration recommendations

| Recommendation or assertion | Evidence and next disposition |
| --- | --- |
| Gemini cannot host native MCP; add OpenAPI gateway | **Incorrect as a blanket claim.** [Official Gemini CLI documentation](https://github.com/google-gemini/gemini-cli/blob/38700b4b38bf387dafded6c97c3f190d084b49e9/docs/tools/mcp-server.md) describes direct MCP support; [the official Python GenAI SDK](https://github.com/googleapis/python-genai/blob/94b371d7ee7b2241be32a1efb78e5fa8cfb791de/README.md) documents experimental local MCP support. Team source checks returned HTTPS 200 on this review date. CLI, SDK and hosted extension products have different contracts; an OpenAPI gateway is not a CLI prerequisite. A new HTTP service would change filesystem/authentication boundaries and was not added. |
| Universal August 2026 Agent Plugins standard backed by named vendors | **Real standard; universal claim unsupported.** The [official Agent Plugins repository](https://github.com/agentplugins/agent-plugins-spec/blob/ff8ab5e392cc87bd88d87c060815a87490e51003/README.md) defines a portable skill/MCP package contract: specification 1.0.0 is published and 1.1.0 is a working draft. Its pinned maintainer affiliations include Amazon, Cursor, Microsoft, OpenAI and Vercel, not Google; that does not prove Google never backed it, but the pasted endorsement list is unverified. Portable `plugin.json` plus explicit stdio `mcp.json` differ from native Claude/Gemini manifests. Client adoption is incremental, so compatibility with every 2026 client is not established. |
| Add generic path-root middleware | **Scope carefully.** Source/spec confinement and caller cwd are intentional, operation-specific contracts. [Workflow](../../../WORKFLOWS.md), [Python](../../../PYTHON_CLIENT.md) and Hyperframes path documentation already distinguish them. Silently rebasing all paths could select different media; no global path rewrite is justified. |
| Safe filter/codec degradation | **Implemented as explicit diagnosis.** Complete FFmpeg missing-encoder/filter diagnostics produce bounded dependency advisories through existing `ProcessingError` objects. Requested names are preserved in guidance; codes use normalized bounded ASCII identifiers. Advice has `auto_fix=false`; codec selection, filters and the environment remain intentional caller decisions. Real failure and serialization regressions cover the behavior. |
| Interactive receipt viewer; dependency auto-install | **Potential follow-up, not established missing foundation.** Existing review, previews and release artifacts remain useful. A viewer should preserve exact artifact/review boundaries. Installing system packages adds privileged/network effects and must not happen implicitly during diagnosis. |
| Large-media skim/chunking | **Existing foundation.** [Tools](../../../TOOLS.md) already expose thumbnails, storyboard grids, retained review keyframes and longform transcription. Benchmark a representative long recording before adding duplicate operations or promising reduced cost. |
| Audio ducking and multi-track synchronization are absent | **Stale.** [Audio guide](../../../AUDIO_MIXING.md) documents Client ducking, sample-aligned one-encode timed mixing and bounded looping; governed audio-bed workflows remain separate. Client additions are development changes and add no new MCP/CLI names. |
| Automatically choose hardware encoding for a 10× speedup | **Unmeasured.** Hardware availability, successful encoder execution, codec/output compatibility and quality are separate questions. No universal speed claim or silent encoder substitution is supported. |
| Add reusable recipes and a browser demo | **Recipes have an existing foundation.** Project recipes, repurposing manifests and [examples](../../../../examples/) are present. A browser demo may help onboarding, but simulated responses must be labelled and cannot masquerade as actual FFmpeg, inference or acceptance. No WASM renderer or deployed playground was added. |

## Live release and deployment evidence

Root's September 30 live checks returned HTTP 200 for the product homepage and
`/llms.txt`; site identity reports 1.15.3. Official PyPI/npm metadata agrees on
1.15.3, published September 25, and compatibility shim 1.6.14. GitHub's latest
release entry remains 1.15.0; the MCP Registry latest request returned HTTP 403.
Thus package/site identity is verified, while registry latest remains unknown.
This evidence does not prove every website claim, TLS configuration, directory
listing or desktop installation. No deployment was performed in this task.

## Implemented source changes and validation boundary

The combined source changes update the index, FAQ, comparison and integration
guides, add an extended agent guide, refresh canonical release metadata and active
references, and improve shared FFmpeg diagnostics. Package versions, dependency
pins and registered MCP/CLI counts were not changed. New runtime behavior is
Unreleased even though the branch and published artifact share the 1.15.3 version
number. Installed schemas and artifact hashes remain authoritative.

[Live evidence](live-evidence.json), [artifact validation](release-artifacts.json),
[integration research](INTEGRATION-RESEARCH.md), [release review](RELEASE-REVIEW.md)
and [CI repair](CI-REPAIR.md) preserve the primary-source checks. The original
PR head's hosted safety job failed at Lint. Pinned Ruff 0.15.11 reproduced a
formatting failure; executable syntax trees were unchanged by that repair.
The added error-diagnostic behavior has its own real-FFmpeg regression tests.

A real MCP stdio session initialized Kinocut, listed all 201 tools and completed
metadata-only `search_tools` discovery without a model call. This validates the
server transport; it does not establish a paid end-to-end Gemini/Claude model run.
The required final full-suite result and exact PR head are recorded separately in
[PR validation](../../PR_VALIDATION.md).

Focused public-surface, privacy, release-claims and real-FFmpeg diagnostic tests
passed. Their counts overlap the required full suite and are not additive.
The final full-suite outcome is recorded in [PR validation](../../PR_VALIDATION.md).
[PR #586](https://github.com/KyaniteLabs/kinocut/pull/586) is the review vehicle.
Local Markdown targets, explicit/default MCP parser modes, fenced blocks and
whitespace checks are separate from host/model execution. No site deployment,
directory submission, provider provisioning or production crawl is implied.
