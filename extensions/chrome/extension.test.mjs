import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

import {
  ALLOWED_ACTIONS,
  NATIVE_HOST_NAME,
  QUALITY_PROFILES,
  basenameFromPath,
  buildNativeRequest,
  createInitialState,
  escapeHtml,
  filterMediaDownloads,
  formatBytes,
  formatDuration,
  formatErrorDisplay,
  isMediaFilename,
  planHasUnresolvedQuestion,
  reduceCompanionState,
} from "./popup_logic.js";

const EXT_DIR = path.dirname(fileURLToPath(import.meta.url));
const PNG_SIGNATURE = Buffer.from([137, 80, 78, 71, 13, 10, 26, 10]);

test("manifest.json is valid MV3 with least-privilege permissions", () => {
  const manifestPath = path.join(EXT_DIR, "manifest.json");
  const manifest = JSON.parse(fs.readFileSync(manifestPath, "utf8"));

  assert.equal(manifest.manifest_version, 3);
  assert.equal(manifest.name, "Kinocut Companion");
  assert.equal(manifest.version, "2.2.0");
  assert.deepEqual(manifest.permissions, ["nativeMessaging", "downloads", "storage"]);
  assert.equal(manifest.host_permissions, undefined);
  assert.equal(manifest.externally_connectable, undefined);
  assert.equal(manifest.content_scripts, undefined);
  assert.equal(JSON.stringify(manifest).includes("<all_urls>"), false);
  assert.equal(manifest.background?.service_worker, "background.js");
  assert.equal(manifest.action?.default_popup, "popup.html");
});

test("extension PNG icons exist and have exact PNG dimensions", () => {
  for (const size of [16, 48, 128]) {
    const iconPath = path.join(EXT_DIR, "icons", `icon-${size}.png`);
    assert.equal(fs.existsSync(iconPath), true, `Missing ${iconPath}`);
    const bytes = fs.readFileSync(iconPath);
    assert.equal(bytes.subarray(0, 8).equals(PNG_SIGNATURE), true);
    const width = bytes.readUInt32BE(16);
    const height = bytes.readUInt32BE(20);
    assert.equal(width, size);
    assert.equal(height, size);
  }
});

test("background.js enforces sender.id check and connectNative bridge", () => {
  const bgSource = fs.readFileSync(path.join(EXT_DIR, "background.js"), "utf8");
  assert.equal(bgSource.includes("sender.id !== chrome.runtime.id"), true);
  assert.equal(bgSource.includes("chrome.runtime.connectNative"), true);
  assert.equal(bgSource.includes("chrome.downloads.search"), true);
  assert.equal(NATIVE_HOST_NAME, "tech.kyanitelabs.kinocut");
});

test("popup.js never uses innerHTML or eval", () => {
  const popupSource = fs.readFileSync(path.join(EXT_DIR, "popup.js"), "utf8");
  assert.equal(popupSource.includes("innerHTML"), false);
  assert.equal(popupSource.includes("outerHTML"), false);
  assert.equal(/\beval\s*\(/.test(popupSource), false);
});

test("buildNativeRequest enforces action allowlist without echoing unknown strings", () => {
  assert.deepEqual(ALLOWED_ACTIONS, [
    "ping",
    "doctor",
    "info",
    "quality_check",
    "direct_plan",
    "direct_apply",
    "review_card",
  ]);
  assert.deepEqual(buildNativeRequest("ping"), { action: "ping", params: {} });
  assert.deepEqual(buildNativeRequest("doctor", {}, { id: "req-1" }), {
    action: "doctor",
    params: {},
    id: "req-1",
  });
  assert.deepEqual(buildNativeRequest("info", { input_path: " /tmp/a.mp4 " }), {
    action: "info",
    params: { input_path: "/tmp/a.mp4" },
  });
  assert.deepEqual(
    buildNativeRequest("quality_check", {
      input_path: "/tmp/a.mp4",
      profile: "dark-grade",
    }),
    {
      action: "quality_check",
      params: {
        input_path: "/tmp/a.mp4",
        profile: "dark-grade",
        fail_on_warning: false,
      },
    }
  );

  assert.throws(
    () => buildNativeRequest("run_shell_secret_9f3a7c", {}),
    (err) => {
      assert.equal(err instanceof Error, true);
      assert.equal(err.message.includes("9f3a7c"), false);
      return true;
    }
  );
  assert.throws(
    () =>
      buildNativeRequest("quality_check", {
        input_path: "/tmp/a.mp4",
        profile: "evil-profile-token",
      }),
    (err) => err instanceof Error && !err.message.includes("evil-profile-token")
  );
  assert.deepEqual(QUALITY_PROFILES, [
    "default",
    "dark-grade",
    "ui-capture-dark",
    "ui-capture-light",
  ]);
});

test("buildNativeRequest gates direct_apply on explicit confirm===true and resolved questions", () => {
  const validPlan = {
    input_path: "/tmp/clip.mp4",
    output_path: "/tmp/clip_direct.mp4",
    steps: [{ tool: "video_trim", args: { start: 0, duration: 2 } }],
    assumptions: [],
    question: null,
  };

  for (const badConfirm of [undefined, false, "true", 1, null]) {
    assert.throws(
      () => buildNativeRequest("direct_apply", { plan: validPlan, confirm: badConfirm }),
      /confirm=true/i
    );
  }

  const planWithQuestion = { ...validPlan, question: "Which aspect ratio?" };
  assert.equal(planHasUnresolvedQuestion(planWithQuestion), true);
  assert.throws(
    () => buildNativeRequest("direct_apply", { plan: planWithQuestion, confirm: true }),
    /unresolved question/i
  );

  const req = buildNativeRequest("direct_apply", {
    plan: validPlan,
    confirm: true,
    overwrite: true,
  });
  assert.deepEqual(req, {
    action: "direct_apply",
    params: { plan: validPlan, confirm: true, overwrite: true },
  });
});

test("reduceCompanionState handles full lifecycle and retains artifacts and readiness badges", () => {
  let state = createInitialState();
  assert.equal(state.status, "idle");

  state = reduceCompanionState(state, { type: "CONNECTING" });
  assert.equal(state.status, "connecting");

  state = reduceCompanionState(state, {
    type: "ACTION_SUCCESS",
    action: "ping",
    payload: {
      success: true,
      version: "2.1.0",
      offline: true,
      protocol: "kinocut-native-v1",
    },
  });
  assert.equal(state.status, "ready");
  assert.equal(state.hostVersion, "2.1.0");
  assert.equal(state.offline, true);

  state = reduceCompanionState(state, { type: "RUNNING", action: "doctor" });
  assert.equal(state.status, "running");

  state = reduceCompanionState(state, {
    type: "ACTION_SUCCESS",
    action: "doctor",
    payload: {
      success: true,
      required_ok: true,
      offline: true,
      ffmpeg: { ok: true, version: "ffmpeg 7.1.1" },
      offline_readiness: { ok: true },
    },
  });
  assert.equal(state.status, "ready");
  assert.equal(state.requiredOk, true);
  assert.equal(state.ffmpegOk, true);
  assert.equal(state.offlineReadinessOk, true);

  state = reduceCompanionState(state, { type: "RUNNING", action: "direct_plan" });
  assert.equal(state.status, "running");

  state = reduceCompanionState(state, {
    type: "ACTION_SUCCESS",
    action: "direct_plan",
    payload: {
      success: true,
      plan_id: "abcdef1234567890",
      assumptions: ["Trim from start"],
      question: null,
      plan: {
        output_path: "/tmp/out_direct.mp4",
        steps: [{ tool: "video_trim", args: {} }],
      },
    },
  });
  assert.equal(state.status, "plan_ready");
  assert.equal(state.outputPath, "/tmp/out_direct.mp4");
  assert.equal(state.planId, "abcdef1234567890");

  state = reduceCompanionState(state, {
    type: "ACTION_SUCCESS",
    action: "review_card",
    payload: {
      success: true,
      output_path: "/tmp/out_review_card.html",
      input_sha256: "0123456789abcdef",
      frame_count: 6,
    },
  });
  assert.equal(state.status, "done");
  assert.equal(state.outputPath, "/tmp/out_review_card.html");
  assert.equal(state.inputSha256, "0123456789abcdef");
  assert.equal(state.reviewCard.output_path, "/tmp/out_review_card.html");

  state = reduceCompanionState(state, {
    type: "ACTION_SUCCESS",
    action: "info",
    payload: {
      success: false,
      error: { code: "invalid_input", message: "Input file error" },
    },
  });
  assert.equal(state.status, "error");
  assert.equal(formatErrorDisplay(state.error), "[invalid_input] Input file error");

  state = reduceCompanionState(state, { type: "DISCONNECTED" });
  assert.equal(state.status, "disconnected");
  assert.equal(state.error.code, "host_disconnected");
});

test("display and download helpers sanitize safely", () => {
  assert.equal(basenameFromPath("/Users/demo/clips/demo.mp4"), "demo.mp4");
  assert.equal(basenameFromPath("C:\\Videos\\take1.MOV"), "take1.MOV");
  assert.equal(isMediaFilename("clip.mp4"), true);
  assert.equal(isMediaFilename("notes.pdf"), false);
  assert.equal(formatDuration(12.34), "12.3s");
  assert.equal(formatDuration(75.5), "1:15.5");
  assert.equal(formatBytes(1536), "1.5 KB");
  assert.equal(
    escapeHtml('<script>alert("x")</script>'),
    "&lt;script&gt;alert(&quot;x&quot;)&lt;/script&gt;"
  );

  const filtered = filterMediaDownloads([
    { id: 1, filename: "/tmp/a.mp4", state: "complete", exists: true, fileSize: 1024 },
    { id: 2, filename: "/tmp/a.mp4", state: "complete", exists: true, fileSize: 1024 },
    { id: 3, filename: "/tmp/readme.txt", state: "complete", exists: true },
    { id: 4, filename: "/tmp/incomplete.mp4", state: "in_progress", exists: true },
    { id: 5, filename: "/tmp/deleted.mov", state: "complete", exists: false },
  ]);
  assert.equal(filtered.length, 1);
  assert.equal(filtered[0].basename, "a.mp4");
});
