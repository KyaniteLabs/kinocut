# Design preflight: KinoCut icon polish (optical calcite)

Scope: a polish and craftsmanship revision of the approved KinoCut mark. The
work keeps its composition and does not redesign it. Simon asked for it on
2026-11-10: "kinocuts approved icon needs you to give it a polish and
craftsmanship revision". Written 2026-11-10 under DECREE-003. No candidate
replaces the repo icon until Simon approves it by eye.

## 1. Purpose

KinoCut lets an agent edit video locally, with guardrails and receipts. Outcome
for the user: "my agent can cut, caption and package video on my own machine,
and show me proof of what it did."

## 2. Title ↔ stone ↔ purpose

| Item | Value | Evidence class |
|---|---|---|
| Title | KinoCut (plugin id `kinocut`) | Repo: `plugins/kinocut/plugin.yaml` |
| Stone | **Optical calcite (Iceland spar), picked by Simon 2026-11-10.** Earlier note: Simon, 2026-11-10: "they need to look like they live in the same world … kinocut should have some mineral crystal justification somewhere" | No KinoCut stone in design MEMORY.md or the icon ledger |
| Candidates (unassigned) | 1. Clear quartz (rock crystal): piezoelectric quartz oscillators keep time in electronics, and rock crystal was ground into early lenses. The cone becomes a natural hexagonal quartz point. 2. Optical calcite (Iceland spar): strong double refraction, used in Nicol polarizing prisms; one source, two images. 3. Watermelon tourmaline (elbaite): pink core, green rind; slices read as frames | Mineral facts: Wikipedia "Quartz", "Crystal oscillator", "Iceland spar", "Elbaite" (to fetch and cite once a stone is picked). Metaphors are ours |
| Taken, not offered | Epoch opal wood; DialectOS apatite; TasteCheck tiger's eye; STR4TI smoky quartz + citrine; CheckYourself black tourmaline; Innerscape selenite, blue lace agate, rose quartz, amethyst; Achiote amber + carnelian; FL4WRITE fluorite; OpenGlaze celestine, milky quartz, garnet, orange calcite; Elixis labradorite (tentative); kyanite reserved for the org | ATLAS-STONE-PROPOSALS.md exclusion register, ledger §1 |
| Purpose fit | A crystal film strip (cut frames), a cutting wedge, and a camera lens | The CEO's own composition |
| Base mark | `plugins/kinocut/assets/icon.png`, 2000×2000 RGBA, sha256 `4b801cc5…20fcc3b` (verified) | Commit a1458ecc: "CEO's new logo … superseding the frozen icon" |
| Superseded | B6 `3105bc9d…e47d0b`. The ledger still lists it as frozen, but it is no longer the catalog image | Ledger §1.12 and commit a1458ecc |

## 3. Rejected directions

- A mark that does not share the family's material world (Simon, 2026-11-10). The r1 renders (`cand-a/b/c`) polished the glass but carry no mineral, so they stay as evidence only.

- A new composition, a new metaphor or a return to the blue B6 mark.
- Adding glitter, more glow or extra facets as a stand-in for craft.
- A flat vector redraw. The family mark is a pipeline render.

## 4. Material reference

- Mineral facts (Wikipedia, "Iceland spar", fetched 2026-11-10): "a colourless,
  transparent variety of calcium carbonate"; "typically forming rhombohedral
  crystals"; it "exhibits double refraction, splitting a ray of light into two
  rays"; "easily divided into parallelepipeds".
- Specimen photo: Wikimedia Commons `File:Silfurberg.jpg` (CC BY-SA 3.0,
  ArniEin), sha256 `fa000172…`. Only the crystal is used; the hand and sky are
  not. `File:Calcite. Mexico-9030.jpg` was rejected as a reference because
  third-party branding shows through it.
- Product fit (our metaphor): double refraction turns one source into two
  images, as KinoCut turns one cut into many deliverables. The doubled edge
  seen through the crystal is the signature.

- The family crystal register: transparent machined glass/crystal planes with
  neon edge light on black. Quiet, broad faces; precise bevels; sharp
  speculars (eye-gate SKILL.md, material-realism.md).
- Design's KinoCut renders, used as craft inspiration (Simon, 2026-11-10): B6 `3105bc9d…` and the 512 reference `541b4e61…` show the target symmetry, faceted cone and crisp edge light.
- The publisher K crystal (`42c49e79…a0ca1f5`) is the family material
  standard, and is used for reference only.

## 5. Family icon law and form

Keep the base's silhouette and all its parts in place:
- two perforated film-strip bars with arrow ends
- the Z-like inner wedge arms
- the faceted cone
- the lens on the right
- a transparent background.

Defects to fix, measured on the base:

- **Mirror match.** The top and bottom strips match poorly (mirror IoU 0.53).
  - The perforations differ in size and spacing between the two strips.
  - The inner wedge arms are misaligned.
  - The arrow-end tips are inconsistent.
- **Lens.** The rim thickness is uneven.
- **Cone.** The facets are muddy.
- **Edges.** The neon edge glow blooms into the faces, so the planes read as
  haze rather than machined glass.

The fix is face shading and clean bevel lines, not keylines.

## 6. Typography

Lockup law: Chakra Petch Bold 700, uppercase, native kerning
(typography-lockups.md §1.4). This pass makes no lockup.

## 7. Platform conventions

| Surface | Convention source | Applied |
|---|---|---|
| Hermes plugin catalog | `plugin-catalog/*.yaml` (ag4te, epoch) | Square PNG icon, transparent, pinned by commit |
| Repo | `plugins/kinocut/assets/icon.png` 2000², `plugins/kinocut/icon.png` 512² | Same paths, uniform resize only |

## 8. UI colour

The family palette law:
- turquoise #00FFE6
- magenta #FF1A6E
- yellow #FFD11A catches
- white speculars
- dark inner planes.

**Assumption:** Simon's "no brown or orange" rule applies to this revision. The
base's amber/orange catches (14% of coloured pixels fall in hue 15–45°) shift to
family yellow. If Simon wants the amber kept, this receipt is updated first.

## 9. Approval and what shipped

Simon approved candidate B by eye on 2026-11-10 ("calcite b applied").

- Render: Codex `gpt-image-2`, round 2, candidate B. It was 1254² on opaque black, sha256 `ca8524a8…dba70`.
- Matte: upscaled to 2000² with Lanczos. The background connected to the canvas edge is transparent, and edge glow is kept as translucent light. The silhouette stays opaque, like the base.
- Shipped: `plugins/kinocut/assets/icon.png` 2000² (`bb7dd7f2…`). `plugins/kinocut/icon.png` and `mcpb/icon.png` are uniform 512² resizes (`01861af7…`).
- Known gaps, accepted as shipped: the cone has fewer facets than the base, and the edge glow is quieter than the family's.
