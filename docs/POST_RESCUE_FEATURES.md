# Post-Rescue Planning Features

MCP Video's post-rescue layer turns ordinary editing requests into inspectable,
source-backed plans before media is changed. These features reuse rescue's hashes,
versioned policies, explicit approvals, capability reporting, verification, and receipts.

## What Is Included

- **Semantic timeline:** versioned words, speakers, shots, scenes, silence, audio events,
  and keyframes in source-time coordinates, with confidence and provenance.
- **Semantic query:** local retrieval that returns source span IDs and times instead of
  inventing clip descriptions.
- **Timeline edit planning:** an edit decision list and visible diff for trims, silence or
  filler cleanup, false starts, retakes, pacing, and explicit reorder requests.
- **Visual transform planning:** confidence-scored subject and camera evidence, crop tracks,
  reframe previews, crop budgets, and stabilization abstention.
- **Restorative planning:** evidence gates for denoise, color/HDR, deblur/upscale, background
  repair, and styled captions.
- **Composition planning:** hashed project assets, rights and provenance, source-backed
  selections, storyboard/timeline plans, branding, audio, captions, and output variants.
- **Creative autopilot planning:** coordination of only the planners and capabilities that
  are present and approved. Missing prerequisites produce an abstention, not a guess.
- **Remote egress planning:** an exact manifest of files and metadata proposed to leave the
  machine, provider and retention terms, estimated cost, and separate network approval.

## Ordinary Editing Guardrails

The planning layer treats these expectations as contracts:

- do not overwrite the source;
- do not remove, reorder, crop, synthesize, upload, or publish anything that was not shown
  in the plan and approval diff;
- preserve source attribution and make uncertainty visible;
- keep speech intelligible, captions synchronized and readable, and audio/video in sync;
- avoid cutting words, clipping text or subjects, introducing black borders, or exceeding
  the approved crop and quality budgets;
- keep credentials and private local paths out of plans and receipts;
- verify downloaded or rendered artifacts locally before promotion;
- never use cloud processing as a fallback for a missing local executor.

## Surfaces

The capability families have matching MCP tools, flat CLI commands, and Python client
methods. CLI planning commands accept one JSON request artifact, making approval inputs
reviewable and repeatable. Planning calls are side-effect free: they do not render media,
download models, contact providers, or submit remote jobs.

| Capability | MCP tool | CLI command | Python method |
|------------|----------|-------------|---------------|
| Semantic timeline | `video_semantic_timeline` | `semantic-timeline` | `semantic_timeline` |
| Semantic query | `video_semantic_query` | `semantic-query` | `semantic_query` |
| Timeline edits | `video_timeline_edit_plan` | `timeline-edit-plan` | `timeline_edit_plan` |
| Visual transforms | `video_visual_transform_plan` | `visual-transform-plan` | `visual_transform_plan` |
| Restoration | `video_restoration_plan` | `restoration-plan` | `restoration_plan` |
| Composition | `video_composition_plan` | `composition-plan` | `composition_plan` |
| Creative autopilot | `video_creative_autopilot_plan` | `creative-autopilot-plan` | `creative_autopilot_plan` |
| Remote egress | `video_remote_egress_plan` | `remote-egress-plan` | `remote_egress_plan` |

The visual surface dispatches `analysis`, `reframe`, or `stabilization`; restoration dispatches
`plan` or `evaluate`; composition dispatches `manifest`, `select`, `plan`, `preview`, `approve`,
`compile`, or `verify`; and remote egress dispatches `plan`, `approve`, `validate_approval`,
`map_fake_job`, `delivery`, `hosting`, `fake_receipt`, or `verify_local_promotion`. The operation
defaults to the primary planning action when omitted.

Rendering remains a separate, explicit step compiled to vetted MCP Video workflow or
compositor operations. A plan that requires an unavailable executor or an unimplemented
operation must abstain instead of silently changing intent.
