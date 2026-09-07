#!/usr/bin/env node

const { spawn, spawnSync } = require("node:child_process");
const { accessSync, constants, existsSync, readFileSync, renameSync, unlinkSync, writeFileSync } = require("node:fs");
const { basename, dirname, join } = require("node:path");

const DEFAULT_PROBE_TIMEOUT_MS = 5000;
const DEFAULT_KILL_GRACE_MS = 500;
const DEFAULT_MAX_OUTPUT_BYTES = 4096;
const PROBE_PROGRAM = [
  "import json, sys",
  "from importlib.metadata import PackageNotFoundError, version",
  "try:",
  "    installed = version('kinocut')",
  "except PackageNotFoundError:",
  "    installed = None",
  "print(json.dumps({'python': list(sys.version_info[:3]), 'kinocut': installed}))",
].join("\n");

function loadRequiredVersion() {
  const manifestPath = join(__dirname, "..", "manifest.json");
  const value = JSON.parse(readFileSync(manifestPath, "utf8")).version;
  if (typeof value !== "string" || !/^\d+\.\d+\.\d+$/.test(value)) {
    throw new Error("The bundled MCPB manifest has an invalid Kinocut version.");
  }
  return value;
}

function pythonCandidates() {
  const configured = process.env.KINOCUT_MCPB_PYTHON?.trim();
  if (configured) return [configured];
  return process.platform === "win32" ? ["py", "python"] : ["python3", "python"];
}

function isExecutable(path) {
  try {
    accessSync(path, constants.X_OK);
    return true;
  } catch {
    return false;
  }
}

function configureFfmpeg(env) {
  const ffmpegPath = env.KINOCUT_MCPB_FFMPEG?.trim();
  if (!ffmpegPath) return;
  const executableName = basename(ffmpegPath).toLowerCase();
  const expectedName = process.platform === "win32" ? "ffmpeg.exe" : "ffmpeg";
  if (executableName !== expectedName || !existsSync(ffmpegPath) || !isExecutable(ffmpegPath)) {
    throw new Error("KINOCUT_MCPB_FFMPEG must point to an executable named ffmpeg.");
  }
  const probeName = process.platform === "win32" ? "ffprobe.exe" : "ffprobe";
  const ffprobePath = join(dirname(ffmpegPath), probeName);
  if (!existsSync(ffprobePath) || !isExecutable(ffprobePath)) {
    throw new Error("KINOCUT_MCPB_FFMPEG requires an adjacent executable named ffprobe.");
  }
  env.KINOCUT_FFMPEG_EXECUTABLE = ffmpegPath;
  env.KINOCUT_FFPROBE_EXECUTABLE = ffprobePath;
}

function signalTree(pid, signal) {
  if (!pid) return;
  try {
    if (process.platform === "win32") {
      spawnSync("taskkill", ["/PID", String(pid), "/T", "/F"], {
        shell: false,
        stdio: "ignore",
        timeout: DEFAULT_KILL_GRACE_MS,
      });
    } else {
      process.kill(-pid, signal);
    }
  } catch {
    // A process that already exited needs no further cleanup.
  }
}

function stopProbe(child, graceMs) {
  signalTree(child.pid, "SIGTERM");
  return new Promise((resolve) => {
    const timer = setTimeout(() => {
      signalTree(child.pid, "SIGKILL");
      resolve();
    }, graceMs);
    child.once("close", () => {
      clearTimeout(timer);
      resolve();
    });
  });
}

function classifyProbe(stdout, requiredVersion) {
  let payload;
  try {
    payload = JSON.parse(stdout);
  } catch {
    return { ok: false, reason: "invalid_probe_output" };
  }
  if (!Array.isArray(payload.python) || payload.python.length < 2) {
    return { ok: false, reason: "invalid_probe_output" };
  }
  if (payload.python[0] < 3 || (payload.python[0] === 3 && payload.python[1] < 11)) {
    return { ok: false, reason: "python_too_old" };
  }
  if (payload.kinocut === null) return { ok: false, reason: "kinocut_missing" };
  if (payload.kinocut !== requiredVersion) return { ok: false, reason: "wrong_kinocut_version" };
  return { ok: true };
}

function probePython(command, requiredVersion, options = {}) {
  const timeoutMs = options.timeoutMs ?? DEFAULT_PROBE_TIMEOUT_MS;
  const killGraceMs = options.killGraceMs ?? DEFAULT_KILL_GRACE_MS;
  const maxOutputBytes = options.maxOutputBytes ?? DEFAULT_MAX_OUTPUT_BYTES;
  const args = command === "py" ? ["-3", "-c", PROBE_PROGRAM] : ["-c", PROBE_PROGRAM];
  return new Promise((resolve) => {
    const child = spawn(command, args, {
      detached: process.platform !== "win32",
      env: { ...process.env, PYTHONNOUSERSITE: "1" },
      shell: false,
      stdio: ["ignore", "pipe", "pipe"],
    });
    let stdout = "";
    let bytes = 0;
    let settled = false;
    let timer;
    const finish = (result) => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      resolve(result);
    };
    const stopAndFinish = (result) => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      stopProbe(child, killGraceMs).then(() => resolve(result));
    };
    const capture = (chunk, keep) => {
      bytes += chunk.length;
      if (bytes > maxOutputBytes) {
        stopAndFinish({ ok: false, reason: "probe_output_overflow" });
      } else if (keep) {
        stdout += chunk.toString("utf8");
      }
    };
    child.stdout.on("data", (chunk) => capture(chunk, true));
    child.stderr.on("data", (chunk) => capture(chunk, false));
    child.once("error", () => finish({ ok: false, reason: "python_not_startable" }));
    child.once("close", (code) => {
      if (!settled) {
        finish(code === 0 ? classifyProbe(stdout.trim(), requiredVersion) : { ok: false, reason: "probe_failed" });
      }
    });
    timer = setTimeout(() => {
      stopAndFinish({ ok: false, reason: "probe_timeout" });
    }, timeoutMs);
  });
}

function probeFailureMessage(reason, requiredVersion) {
  const messages = {
    python_not_startable: "Configured Python could not be started.",
    python_too_old: "Configured Python is too old; Python 3.11+ is required.",
    kinocut_missing: `Configured Python does not have kinocut==${requiredVersion} installed.`,
    wrong_kinocut_version: `Configured Python has a different Kinocut version; install kinocut==${requiredVersion}.`,
    invalid_probe_output: "Python returned an invalid preflight response.",
    probe_failed: "Python preflight command failed.",
    probe_timeout: "Python preflight timed out.",
    probe_output_overflow: "Python preflight produced too much output.",
  };
  return messages[reason] ?? `Unable to find Python 3.11+ with kinocut==${requiredVersion} installed.`;
}

function launch(command, env, supervised) {
  const args = command === "py" ? ["-3", "-m", "kinocut", "--mcp"] : ["-m", "kinocut", "--mcp"];
  return spawn(command, args, {
    detached: process.platform !== "win32" && !supervised,
    stdio: "inherit",
    env,
    shell: false,
  });
}

function stopServer(child, signal, supervised) {
  if (supervised) child.kill(signal);
  else signalTree(child.pid, signal);
}

function forwardTermination(child, supervised) {
  for (const signal of ["SIGINT", "SIGTERM"]) {
    process.once(signal, () => {
      stopServer(child, signal, supervised);
      setTimeout(() => stopServer(child, "SIGKILL", supervised), DEFAULT_KILL_GRACE_MS);
    });
  }
}

function recordSupervisedChild(child) {
  const destination = process.env.KINOCUT_MCPB_SUPERVISED_PID_FILE?.trim();
  const token = process.env.KINOCUT_MCPB_SUPERVISED_TOKEN?.trim();
  if (!destination && !token) return;
  if (!destination || !/^[0-9a-f]{64}$/.test(token) || existsSync(destination)) {
    throw new Error("invalid supervised process observation request");
  }
  const temporary = `${destination}.${process.pid}.tmp`;
  try {
    writeFileSync(temporary, JSON.stringify({ token, pid: child.pid }), { encoding: "utf8", flag: "wx", mode: 0o600 });
    renameSync(temporary, destination);
  } catch (error) {
    try { unlinkSync(temporary); } catch {}
    throw error;
  }
}

async function main() {
  const requiredVersion = loadRequiredVersion();
  const env = { ...process.env };
  try {
    configureFfmpeg(env);
  } catch (error) {
    console.error(error.message);
    process.exit(126);
  }
  let lastReason = "python_not_startable";
  for (const command of pythonCandidates()) {
    const result = await probePython(command, requiredVersion);
    if (!result.ok) {
      lastReason = result.reason;
      continue;
    }
    const supervised = process.env.KINOCUT_MCPB_SUPERVISED_PROCESS_TREE === "1";
    const child = launch(command, env, supervised);
    try {
      if (supervised) recordSupervisedChild(child);
    } catch {
      stopServer(child, "SIGKILL", supervised);
      console.error("Kinocut MCPB process ownership could not be recorded.");
      process.exit(126);
      return;
    }
    forwardTermination(child, supervised);
    child.once("error", () => {
      console.error("Kinocut passed preflight but the MCP server could not start.");
      process.exit(127);
    });
    child.once("exit", (code, signal) => {
      if (signal) process.kill(process.pid, signal);
      else process.exit(code ?? 1);
    });
    return;
  }
  console.error(`Unable to start Kinocut MCPB. ${probeFailureMessage(lastReason, requiredVersion)}`);
  process.exit(127);
}

module.exports = { loadRequiredVersion, probeFailureMessage, probePython, pythonCandidates };
if (require.main === module) {
  main().catch(() => {
    console.error("Kinocut MCPB launcher failed during bounded preflight.");
    process.exit(1);
  });
}
