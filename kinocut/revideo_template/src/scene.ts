import { waitFor } from '@revideo/core';
import { makeScene2D, Rect, Txt } from '@revideo/2d';
import job from './job.json';

// Deterministic PRNG (mulberry32): identical job.json => identical pixels,
// on every machine, forever. The bridge contract depends on this.
function mulberry32(seed: number) {
  let a = seed >>> 0;
  return function () {
    a |= 0;
    a = (a + 0x6d2b79f5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

export default makeScene2D('bridge', function* (view) {
  const cols = 12;
  const cell = Math.max(job.width, job.height) / cols;
  const rows = Math.ceil(job.height / cell);
  const fittedCols = Math.ceil(job.width / cell);

  // Precompute every cell's per-frame value from one seeded stream so the
  // sequence is reproducible regardless of render worker count.
  const rng = mulberry32(job.seed);
  const values: number[][] = [];
  for (let f = 0; f < job.frames; f++) {
    const frame: number[] = [];
    for (let i = 0; i < rows * fittedCols; i++) frame.push(rng());
    values.push(frame);
  }

  const cells: Rect[] = [];
  for (let r = 0; r < rows; r++) {
    for (let c = 0; c < fittedCols; c++) {
      const rect = new Rect({
        x: -job.width / 2 + cell * (c + 0.5),
        y: -job.height / 2 + cell * (r + 0.5),
        width: cell,
        height: cell,
        fill: '#000000',
      });
      cells.push(rect);
      view.add(rect);
    }
  }

  const label = new Txt({
    text: 'kinocut revideo bridge — frame 1',
    fontSize: Math.max(job.height / 18, 24),
    fill: '#ffffff',
    y: 0,
  });
  view.add(label);

  for (let f = 0; f < job.frames; f++) {
    for (let i = 0; i < cells.length; i++) {
      const v = values[f][i];
      cells[i].fill(`hsl(${Math.floor(v * 360)}, 55%, ${12 + Math.floor(v * 70)}%)`);
    }
    label.text(`kinocut revideo bridge — frame ${f + 1}/${job.frames}`);
    yield* waitFor(1 / job.fps);
  }
});
