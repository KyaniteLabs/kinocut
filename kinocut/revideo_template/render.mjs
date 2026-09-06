// Kinocut revideo bridge render entry. Kinocut's Python engine invokes this
// via `npm run render` inside a materialized copy of this template. The job
// travels in src/job.json (compile-time inlined by vite, so the scene and the
// project settings always agree). Output: out/video.mp4; the absolute path is
// printed on the last stdout line for the engine to consume.
import { createRequire } from 'node:module';
import { readFile } from 'node:fs/promises';
import path from 'node:path';

const require = createRequire(import.meta.url);
const { renderVideo } = require('@revideo/renderer');

const job = JSON.parse(await readFile(new URL('./src/job.json', import.meta.url), 'utf8'));

const outFile = job.out_file ?? 'video.mp4';

// Browser selection: revideo's puppeteer defaults to its downloaded
// chrome-headless-shell, which macOS may refuse to exec on provenance
// grounds (spawn ECANCELED). Callers point at a system Chrome via
// KINOCUT_REVIDEO_EXECUTABLE_PATH or job.puppeteer.executablePath.
const executablePath =
  job.puppeteer?.executablePath ?? process.env.KINOCUT_REVIDEO_EXECUTABLE_PATH ?? undefined;

const outPath = await renderVideo({
  projectFile: path.resolve('src/project.ts'),
  settings: {
    outDir: 'out',
    outFile,
    workers: job.workers ?? 2,
    logProgress: false,
    ...(executablePath ? { puppeteer: { executablePath } } : {}),
  },
});

console.log(outPath);
