#!/usr/bin/env node

const { spawn } = require("node:child_process");
const { constants, readFileSync, realpathSync, accessSync } = require("node:fs");
const path = require("node:path");
const { dirname, join, resolve, delimiter } = path;

const BUNDLE_ROOT = resolve(dirname(__filename), "..");
const RUNTIME_ROOT = join(BUNDLE_ROOT, "runtime");

function isContainedPath(pathApi, root, candidate) {
  const fromRoot = pathApi.relative(root, candidate);
  return Boolean(fromRoot)
    && !pathApi.isAbsolute(fromRoot)
    && fromRoot !== ".."
    && !fromRoot.startsWith(`..${pathApi.sep}`)
    && pathApi.resolve(root, fromRoot) === candidate;
}

function fail(message) {
  console.error(message);
  process.exit(126);
}

function hostTarget() {
  const os = process.platform === "win32" ? "windows" : process.platform;
  return `${os}-${process.arch}`;
}

function containedExecutable(executablePath) {
  try {
    const bundle = realpathSync(BUNDLE_ROOT);
    const root = realpathSync(RUNTIME_ROOT);
    if (!isContainedPath(path, bundle, root)) {
      fail("Kinocut MCPB contains an invalid bundled runtime.");
    }
    const resolved = realpathSync(executablePath);
    if (!isContainedPath(path, root, resolved)) {
      fail("Kinocut MCPB contains an invalid bundled runtime.");
    }
    accessSync(resolved, constants.X_OK);
    return resolved;
  } catch {
    fail("Kinocut MCPB contains an invalid bundled runtime.");
  }
}

function runtimePaths() {
  const windows = process.platform === "win32";
  const nodeBin = windows ? join(RUNTIME_ROOT, "node") : join(RUNTIME_ROOT, "node", "bin");
  const pythonBin = windows ? join(RUNTIME_ROOT, "python") : join(RUNTIME_ROOT, "python", "bin");
  const ffmpegBin = join(RUNTIME_ROOT, "ffmpeg", "bin");
  return {
    python: containedExecutable(join(pythonBin, windows ? "python.exe" : "python3")),
    ffmpeg: containedExecutable(join(ffmpegBin, windows ? "ffmpeg.exe" : "ffmpeg")),
    ffprobe: containedExecutable(join(ffmpegBin, windows ? "ffprobe.exe" : "ffprobe")),
    path: [pythonBin, ffmpegBin, nodeBin].join(delimiter),
  };
}

function validateTarget() {
  try {
    const metadata = JSON.parse(readFileSync(join(RUNTIME_ROOT, "runtime-metadata.json"), "utf8"));
    if (metadata.target !== hostTarget() || metadata.target !== `${metadata.os}-${metadata.arch}`) {
      fail(`Kinocut MCPB target ${metadata.target} does not match this host (${hostTarget()}).`);
    }
  } catch (error) {
    if (error && error.code === undefined && String(error.message).includes("does not match")) {
      throw error;
    }
    fail("Kinocut MCPB runtime metadata is missing or invalid.");
  }
}

function main() {
  validateTarget();
  const runtime = runtimePaths();
  const env = {
    ...process.env,
    PATH: runtime.path,
    KINOCUT_FFMPEG_EXECUTABLE: runtime.ffmpeg,
    KINOCUT_FFPROBE_EXECUTABLE: runtime.ffprobe,
  };
  const child = spawn(runtime.python, ["-I", "-s", "-m", "kinocut", "--mcp"], {
    stdio: "inherit",
    env,
    shell: false,
  });
  child.once("error", () => fail("Kinocut MCPB could not start its bundled Python runtime."));
  child.once("exit", (code, signal) => {
    if (signal) {
      process.removeAllListeners(signal);
      process.kill(process.pid, signal);
      return;
    }
    process.exit(code ?? 1);
  });
  for (const signal of ["SIGINT", "SIGTERM"]) {
    process.on(signal, () => child.kill(signal));
  }
}

module.exports = { isContainedPath };

if (require.main === module) {
  main();
}
