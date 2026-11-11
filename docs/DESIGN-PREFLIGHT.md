# Design preflight: KinoCut icon (optical calcite, then silver + calcite)

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

## 10. Launch reel colorway (2.0 reel, 2026-11-10)

Simon, 2026-11-10: "agate is purple because of its stone. but kinocut is a different stone use the colorway of the optical calcite". The reel was built on the AG4TE launch-reel template and had inherited agate's violet and magenta.

| Role | Value | Basis |
|---|---|---|
| Ground | near-black cool graphite `#05080b`, raised `#0e171c` | Family register: dark ground, crystal planes |
| Crystal / ink | water-clear ice `#f2fafb`, `#dff4f7` | Iceland spar is colourless and transparent (Wikipedia, "Iceland spar") |
| Glass tints | `#a8e4ec`, `#8fc9d2`, `#5fb8c4` | Clear crystal seen edge-on over a dark ground. **Assumption:** a light cool tint reads as "clear" on video; pure white would flatten |
| Edge light | family turquoise `#00FFE6` | Family palette law (§8) |
| Signature | doubled offset ghost on the hook line and wordmark | Double refraction: one source, two images (§4) |
| Removed | violet `#a78bfa`/`#7c3aed`, magenta `#e879f9`, navy-purple ground | Agate's colorway, not calcite's |

The K logo (`plugins/kinocut/assets/icon.png`) is approved brand art and is not recoloured.

**Correction, 2026-11-10 (Simon: "why does the new icon look black").** The K art is clear glass with a dark interior baked into the pixels (about a third of its opaque pixels are near-black). The old navy-violet ground lit that interior; the calcite near-black ground did not, so the mark read as black. Fix: the halo behind the mark is raised to ice `rgba(223,244,247,0.55)` → glass `rgba(95,184,196,0.38)` → edge `rgba(0,255,230,0.12)`. The logo art itself is still untouched.

**Correction 2, 2026-11-10 (Simon: "is the black the color of optical calcite?").** No. Optical calcite (Iceland spar) is colourless and water-clear, sometimes faintly white or pale honey. The near-black ground `#05080b` was an invented stage, not the stone's colour, and it breaks the stone-colour rule. Replaced with a light, clear colorway:
- ground: clear `#f4f9fa`, raised `#e6f1f3` (faint ice tint, as seen through spar);
- ink: deep cold slate `#0f2229` for text, `#4d6670` muted;
- glass tints: `#a8e4ec`, `#5fb8c4`; edge/accent: deep calcite teal `#0f8a95`, the family turquoise `#00FFE6` only as a thin highlight;
- doubled offset ghost stays on the hook and wordmark (double refraction), now in pale glass `#a8e4ec`;
- the K logo is unchanged and sits on the light ground.
**Assumption:** the logo's baked dark glass interior reads acceptably on a light ground; to be verified by test frame and Simon's eye-gate.

### Correction 3 (2026-11-10): the reel used a grey logo copy, not the approved art

Simon: "still looks black ar eyob ling". He was right. The reel's `assets/logo.png` was a desaturated, dark variant of the film-strip/lens mark. It was not the approved art. The approved mark (kinocut-site `img/brand/kinocut-approved-512.png`, the same art `mcpb/icon.png` carried before #791) is bright prismatic crystal. Changing the background was never going to fix this. The earlier claim that the dark glass "reads as smoky crystal" was wrong. Fix: crop the approved mark to its alpha bounds and fit it proportionally into the end-card box, with no recolour. The old file is kept as `logo.grey-old.png`.
Lesson: before blaming the ground, diff the shipped asset against the approved source.

### Correction 4 (2026-11-10): the logo itself must be optical calcite

Simon: "no ... i asked for the ... optical calcite you promised". Swapping in the older neon logo was the wrong fix. The ask is for the mark itself to read as Iceland spar. Fix for the reel: a calcite treatment of the CEO's current mark (`plugins/kinocut/assets/icon.png`, commit a1458ecc). The body is water-clear: near-white glass at about 30% opacity. Facet edges are drawn in deep slate-teal. A pale offset ghost copy shows double refraction (one source, two images). The script is in the session scratchpad at `calc/make.py`. The source art is untouched. This rule overrides the earlier "never recolour" note, at Simon's direction.
**Assumption:** this is a reel-only treatment. A canonical calcite mark for the catalog still needs the icon pipeline and Simon's eye-gate.

## 11. New icon concept: native silver + optical calcite (2026-11-10)

Simon's brief: "generate a brand new icon, give it all the other hackathon icons as references of the design style I want for kinocut, and give it silver AND optical calcite as the crystals for it." Model: `gpt-6.1-sol` at xhigh effort through Codex, as named. No substitution.

**Family references (style, not content):**

| Plugin | Icon | What it teaches |
|---|---|---|
| Epoch | `KyaniteLabs/Epoch` `plugins/epoch-hermes/icon.png` | Photoreal macro object; polished metal frame holding real stone |
| AG4TE | `KyaniteLabs/ag4te` `plugins/ag4te-hermes/icon.png` | A real stone slice fills the tile; the product idea is drawn in the stone |
| UNBL0CK | `KyaniteLabs/unbl0ck` `assets/logo/icon-512.png` | Real crystal habit (prisms), product meaning layered on top |
| Selenite | `KyaniteLabs/selenite` `icon.png` | Single real specimen, true colour, plain ground |

Family style: photoreal, product-photo lighting, the true mineral as the hero, one bold silhouette.

**Materials (facts):**
- Optical calcite / Iceland spar: transparent, colourless calcite. Rhombohedral cleavage. Strong double refraction, so a line seen through it appears doubled (Wikipedia, "Iceland spar").
- Native silver: pure metallic Ag. Lustrous white metal, highest reflectivity of any metal. Habits are filiform (wire), arborescent and dendritic (Wikipedia, "Native silver"; "Silver").

**Form proposal:** a clear Iceland spar rhomb, with a native silver frame, wire or film-strip element carrying the cut idea (film strip + cutting wedge + lens). Seen through the calcite, the silver doubles. That double image is the Kinocut idea: one frame, two takes, the cut between them.
- **Assumption:** silver is used as polished metal (as Epoch uses chrome) and/or wire habit. Tarnish is avoided because it reads as black at small size.
- **Assumption:** a plain transparent or soft-neutral ground, matching Selenite/Epoch.

**Status:** concept only. It is not the Kinocut icon until Simon approves by eye. The current marks stayed unchanged until approval.

### Correction 5 (2026-11-10): keep the Kinocut mark

Simon looked at the section 11 concepts (a calcite block over a film strip) and said: "way too different from the kino logo." Both concepts are rejected.

What changes: the new icon must keep the existing Kinocut mark's form, from `plugins/kinocut/assets/icon.png`:
- the two film-strip arms with three sprocket windows each and arrow ends;
- the cutting wedge pointing left;
- the lens barrel on the right.

Only the material changes:
- silver for the structure (film-strip arms, lens barrel rings);
- optical calcite for the clear parts (wedge, lens glass, sprocket windows), water-clear with doubled edges.

Rendering moves to the photoreal hackathon family style.

What does not change: the hackathon icons stay the style reference, and nothing is canonical without Simon's eye-gate.

### Correction 6 (2026-11-10): more life

Simon looked at round 2 (the Kinocut mark in silver and calcite, on charcoal and on light grey) and said: "It needs a bit more life."

What changes: the colour and light come from real behaviour of the two materials, not a neon overlay.
- Calcite shows prismatic fire at its edges, plus rainbow fringes along the doubled edges (double refraction splits light).
- Polished silver throws hot specular glints and reflects coloured studio light.
- A beam or flare through the lens, and rim light around the shape, give energy.
- The family-ledger catch colours (turquoise `#00FFE6`, magenta `#FF1A6E`, yellow `#FFD11A`) may appear only as reflected or refracted light. They do not tint the body.
- **Assumption:** a dark ground stays, because round 2 showed it reads best at 32 px.

What does not change: the shape of the mark, silver plus calcite as the materials, and Simon's eye-gate.

### Approval and what shipped (2026-11-10)

Simon approved round 3, candidate A ("a approved"). A is the subtle variant: fire and glints, with almost no colour cast.

This replaces the calcite icon from #791 (section 9). Both were approved on the same day. This one is the newer brief: a brand-new icon in silver and calcite, made in the hackathon family style.

- Render: Codex `gpt-6.1-sol` at xhigh, round 3, candidate A. It was 1254² on opaque charcoal, sha256 `84db40ce…b850`.
- Matte: the charcoal background connected to the canvas edge is keyed out, with a 1.5 px soft edge and the edge colour pulled away from the charcoal. Floating shadow and reflection patches on the ground are dropped, so only the mark remains. It is then cropped to the mark, centred in a square with 4% margin and resized with Lanczos.
- Transparent background, per the family ledger law. The Epoch and UNBL0CK icons ship opaque; this one doesn't.
- Shipped: `plugins/kinocut/assets/icon.png` 2000² (`41911ec7…`). `plugins/kinocut/icon.png` and `mcpb/icon.png` are uniform 512² resizes (`23e04bca…`).
- Known gaps: the 2000² master is upscaled from a 1254² render. The mark reads at 32 px, but at 16 px it is a silver blob. A faint grey shadow flake stays attached above the wedge.
