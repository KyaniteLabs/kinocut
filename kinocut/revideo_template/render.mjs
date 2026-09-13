// Kinocut revideo bridge render entry. Kinocut's Python engine invokes this
// via `npm run render` inside a materialized copy of this template. The job
// travels in src/job.json (compile-time inlined by vite, so the scene and the
// project settings always agree). The engine selects a fresh private output
// leaf through KINOCUT_REVIDEO_OUTPUT_FILE and validates that file directly.
import { createRequire } from 'node:module';
import { readFile } from 'node:fs/promises';
import path from 'node:path';

const require = createRequire(import.meta.url);
const { renderVideo } = require('@revideo/renderer');

const job = JSON.parse(await readFile(new URL('./src/job.json', import.meta.url), 'utf8'));

const outFile = process.env.KINOCUT_REVIDEO_OUTPUT_FILE ?? job.out_file ?? 'video.mp4';
const exporterFormat = new Map([
  ['.mp4', 'mp4'],
  ['.webm', 'webm'],
  ['.mov', 'proRes'],
]).get(path.extname(outFile));
if (exporterFormat === undefined) {
  throw new Error(`Unsupported Revideo output suffix: ${path.extname(outFile) || '(none)'}`);
}

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
    projectSettings: {
      exporter: {
        name: '@revideo/core/ffmpeg',
        options: {format: exporterFormat},
      },
    },
    ...(executablePath ? { puppeteer: { executablePath } } : {}),
  },
});

console.log(outPath);
