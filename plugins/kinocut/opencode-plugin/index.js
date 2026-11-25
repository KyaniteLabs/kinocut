"use strict";

const path = require("node:path");
const baseConfig = require("./opencode.json");

const PLUGIN_NAME = "kinocut";
const RUNTIME_VERSION = "2.2.0";
const SKILLS_DIR = path.resolve(__dirname, "..", "skills");

/**
 * Build a minimal OpenCode MCP config block for Kinocut.
 * Keeps the default 18-tool environment-unset surface unless `toolsProfile` is passed.
 *
 * @param {{ toolsProfile?: string, enabled?: boolean }} [options]
 * @returns {{ $schema: string, mcp: { kinocut: { type: string, command: string[], enabled: boolean, environment?: Record<string, string> } } }}
 */
function createOpenCodeConfig(options = {}) {
  const server = {
    type: baseConfig.mcp.kinocut.type,
    command: [...baseConfig.mcp.kinocut.command],
    enabled: options.enabled !== undefined ? Boolean(options.enabled) : baseConfig.mcp.kinocut.enabled,
  };
  if (typeof options.toolsProfile === "string" && options.toolsProfile.trim()) {
    server.environment = { KINOCUT_TOOLS: options.toolsProfile.trim() };
  }
  return {
    $schema: baseConfig.$schema,
    mcp: {
      kinocut: server,
    },
  };
}

/**
 * Minimal OpenCode plugin descriptor exporting Kinocut MCP metadata and bundled skills path.
 *
 * @param {{ toolsProfile?: string, enabled?: boolean }} [options]
 */
function kinocutOpenCodePlugin(options = {}) {
  return {
    name: PLUGIN_NAME,
    version: RUNTIME_VERSION,
    skillsDir: SKILLS_DIR,
    config: createOpenCodeConfig(options),
  };
}

module.exports = {
  PLUGIN_NAME,
  RUNTIME_VERSION,
  SKILLS_DIR,
  baseConfig,
  createOpenCodeConfig,
  kinocutOpenCodePlugin,
  default: kinocutOpenCodePlugin,
};
