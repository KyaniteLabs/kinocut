# Kinocut Revideo Bridge Template

Kinocut-owned, lockfile-pinned [Revideo](https://github.com/redotvideo/revideo)
(MIT, Motion Canvas fork) project skeleton. This is the Kino side of the
Sinter×Kino integration (liminal #999): Sinter hands over winners bundles,
Kinocut renders.

## Gotchas baked into this template (learned the hard way, 2026-08-31)

1. **`makeScene2D` requires the scene NAME as its first argument** —
   `makeScene2D('bridge', function* (view) {...})`. Passing only the
   generator compiles fine but fails at render time with
   `Cannot read properties of undefined (reading 'name')` (the description's
   `config` stays undefined). The upstream skeleton this template forked from
   had exactly this bug — it had never been rendered.
2. **`waitFor` must be imported from `@revideo/core`** — it is not a global.
3. **`@revideo/renderer` has undeclared internal deps** (`@revideo/telemetry`,
   `@revideo/vite-plugin`, `@revideo/ui`) that its own `dependencies` omits —
   this template declares all of them pinned because `npm ci` will not
   discover them.
4. **macOS may refuse to exec puppeteer's downloaded chrome-headless-shell**
   (`spawn ... ECANCELED`, protected `com.apple.provenance` xattr). Point at a
   system Chrome via `KINOCUT_REVIDEO_EXECUTABLE_PATH` (the engine does this
   automatically when `kino doctor` knows a browser).
5. **Determinism verified:** two independent renders of the same `job.json`
   produced byte-identical output (sha256
   `bf528e28fdfef4f5b6ce42ed279129a6a4d341a5c86a29c766b6aadb9cb19560` for the
   640×360/10-frame/seed-7 smoke job). Preserve this: scenes must derive all
   randomness from `job.seed`, never from `Math.random()` or wall-clock.

## Contract

- **Versions are pinned exactly** (`0.10.4` / TypeScript `5.3.3`) and
  `package-lock.json` is committed. Installs use `npm ci` — never `npm install`
  — so a materialized project is byte-reproducible. Never widen a version
  range without regenerating the lockfile and re-running the smoke render.
- **The job travels in `src/job.json`** (width, height, fps, frames, seed,
  workers, optional out_file). `src/project.ts` reads it for the canvas size;
  `src/scene.ts` reads it for the sequence. `render.mjs` wraps
  `@revideo/renderer`'s `renderVideo` and prints the output path.
- **`src/scene.ts` is the swap point.** The vendored scene is a deterministic
  seeded reference sequence (mulberry32 — same job.json ⇒ same pixels on any
  machine, forever). Artwork adapters (Sinter winners: p5/three/glsl/hydra
  code + params) replace this file per render job; they must preserve the
  deterministic-render property.
- **Never commit** `node_modules/` or `out/` from this directory.

## Engine

`kinocut/revideo_engine.py` materializes a copy of this template per job
(without `node_modules/`/`out/`), optionally swaps in a scene, writes the job,
runs `npm ci` + `npm run render` under timeouts with a closed stdin, then
ffprobe-verifies the output and records its SHA-256.
