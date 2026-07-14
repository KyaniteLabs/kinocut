#!/usr/bin/env node

const { spawn } = require("node:child_process");
const { accessSync, constants, existsSync } = require("node:fs");
const { basename, dirname, delimiter, join } = require("node:path");

function splitCommands(value) {
  return value
    .split(delimiter)
    .map((item) => item.trim())
    .filter(Boolean);
}

function pythonCandidates() {
  const configured = process.env.KINOCUT_MCPB_PYTHON?.trim();
  if (configured) {
    return [configured];
  }
  if (process.platform === "win32") {
    return ["py", "python"];
  }
  return ["python3", "python"];
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
  if (!ffmpegPath) {
    return;
  }

  const executableName = basename(ffmpegPath).toLowerCase();
  const expectedName = process.platform === "win32" ? "ffmpeg.exe" : "ffmpeg";
  if (executableName !== expectedName || !existsSync(ffmpegPath) || !isExecutable(ffmpegPath)) {
    console.error("KINOCUT_MCPB_FFMPEG must point to an executable named ffmpeg.");
    process.exit(126);
  }

  const ffprobePath = join(dirname(ffmpegPath), process.platform === "win32" ? "ffprobe.exe" : "ffprobe");
  if (!existsSync(ffprobePath) || !isExecutable(ffprobePath)) {
    console.error("KINOCUT_MCPB_FFMPEG requires an adjacent executable named ffprobe.");
    process.exit(126);
  }

  env.KINOCUT_FFMPEG_EXECUTABLE = ffmpegPath;
  env.KINOCUT_FFPROBE_EXECUTABLE = ffprobePath;
}

function buildEnv() {
  const env = { ...process.env };
  configureFfmpeg(env);
  return env;
}

function launch(command, env) {
  const args = command === "py" ? ["-3", "-m", "kinocut", "--mcp"] : ["-m", "kinocut", "--mcp"];
  return spawn(command, args, {
    stdio: "inherit",
    env,
    shell: false,
  });
}

async function main() {
  const env = buildEnv();
  const commands = pythonCandidates().flatMap(splitCommands);
  let child = null;
  let lastError = null;

  for (const command of commands) {
    child = launch(command, env);
    const started = await new Promise((resolve) => {
      child.once("spawn", () => resolve(true));
      child.once("error", (error) => {
        lastError = error;
        resolve(false);
      });
    });
    if (started) {
      break;
    }
  }

  if (!child || child.exitCode !== null) {
    const detail = lastError ? ` (${lastError.message})` : "";
    console.error(
      "Unable to start Kinocut MCPB. Install Python 3.11+, install kinocut==1.8.0 in that environment, "
        + `or configure pythonExecutable.${detail}`,
    );
    process.exit(127);
  }

  child.on("exit", (code, signal) => {
    if (signal) {
      process.kill(process.pid, signal);
      return;
    }
    process.exit(code ?? 1);
  });
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
