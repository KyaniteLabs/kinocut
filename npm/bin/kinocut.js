#!/usr/bin/env node

import { spawnSync } from "node:child_process";

const args = ["--from", "kinocut==1.7.0", "kino", ...process.argv.slice(2)];
const result = spawnSync("uvx", args, { stdio: "inherit" });

if (result.error?.code === "ENOENT") {
  console.error("Kinocut requires uv. Install it from https://docs.astral.sh/uv/getting-started/installation/");
  process.exit(127);
}

if (result.error) {
  console.error(`Unable to start Kinocut: ${result.error.message}`);
  process.exit(1);
}

process.exit(result.status ?? 1);
