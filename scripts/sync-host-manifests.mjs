#!/usr/bin/env node
// Keeps host manifests in step with the portable Agent Plugins source.
//
// Source of truth (per plugin directory):
//   plugin.json  - Agent Plugins 1.0 manifest
//   mcp.json     - Agent Plugins MCP config (typed transports)
// Generated / synced:
//   .claude-plugin/plugin.json - shared fields copied; Claude-only fields kept
//   .mcp.json                  - mcp.json without $schema
//
// Usage:
//   node scripts/sync-host-manifests.mjs          # write
//   node scripts/sync-host-manifests.mjs --check  # exit 1 on drift (CI)

import { readFileSync, writeFileSync, existsSync, mkdirSync, readdirSync } from "node:fs";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const SHARED_FIELDS = ["name", "version", "description", "author", "license"];
const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const check = process.argv.includes("--check");
const problems = [];

const readJson = (p) => JSON.parse(readFileSync(p, "utf8"));
const fmt = (o) => JSON.stringify(o, null, 2) + "\n";

function sync(path, next) {
  const current = existsSync(path) ? readFileSync(path, "utf8") : null;
  if (current === next) return;
  if (check) {
    problems.push(`${path.replace(root + "/", "")} is out of sync`);
    return;
  }
  mkdirSync(dirname(path), { recursive: true });
  writeFileSync(path, next);
  console.log(`wrote ${path.replace(root + "/", "")}`);
}

const pluginsDir = join(root, "plugins");
for (const entry of readdirSync(pluginsDir, { withFileTypes: true })) {
  if (!entry.isDirectory()) continue;
  const dir = join(pluginsDir, entry.name);
  const sourcePath = join(dir, "plugin.json");
  if (!existsSync(sourcePath)) continue;
  const source = readJson(sourcePath);
  if (!String(source.$schema ?? "").includes("agent-plugins.org")) continue;

  // 1. Claude manifest: shared fields from source, host-only fields preserved.
  const claudePath = join(dir, ".claude-plugin", "plugin.json");
  const claude = existsSync(claudePath) ? readJson(claudePath) : {};
  const merged = { ...claude };
  for (const key of SHARED_FIELDS) {
    if (source[key] !== undefined) merged[key] = source[key];
  }
  // Existing files keep their key order; new files lead with shared fields.
  const ordered = {};
  const leading = Object.keys(claude).length ? Object.keys(claude) : ["name", ...SHARED_FIELDS];
  for (const key of leading) {
    if (merged[key] !== undefined) ordered[key] = merged[key];
  }
  for (const [k, v] of Object.entries(merged)) if (!(k in ordered)) ordered[k] = v;
  sync(claudePath, fmt(ordered));

  // 2. Claude .mcp.json from the portable mcp.json.
  const mcpPath = join(dir, "mcp.json");
  if (existsSync(mcpPath)) {
    const { $schema, ...mcp } = readJson(mcpPath);
    // Claude defaults to stdio; omit that type so .mcp.json keeps its plain shape.
    const claudeServers = Object.fromEntries(
      Object.entries(mcp.mcpServers ?? {}).map(([name, { type, ...rest }]) => [
        name,
        type === "stdio" ? rest : { type, ...rest },
      ]),
    );
    sync(join(dir, ".mcp.json"), fmt({ ...mcp, mcpServers: claudeServers }));

    // 3. Every launcher must pin the plugin's own version.
    for (const [name, server] of Object.entries(mcp.mcpServers ?? {})) {
      if (!server.type) problems.push(`${entry.name}: server "${name}" has no transport type`);
      const args = (server.args ?? []).join(" ");
      if (["npx", "uvx", "pnpm"].includes(server.command) && !args.includes(source.version)) {
        problems.push(
          `${entry.name}: server "${name}" launcher (${server.command} ${args}) does not pin version ${source.version}`,
        );
      }
    }
  }
}

if (problems.length) {
  console.error(problems.map((p) => `- ${p}`).join("\n"));
  if (check) console.error("\nRun: node scripts/sync-host-manifests.mjs");
  process.exit(1);
}
console.log(check ? "host manifests in sync" : "done");
