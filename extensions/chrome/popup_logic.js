/**
 * Pure ES module logic for Kinocut Chrome Companion.
 * Zero DOM or Chrome API dependencies so all protocol and state logic
 * is directly testable in Node.
 */

export const NATIVE_HOST_NAME = "tech.kyanitelabs.kinocut";

export const ALLOWED_ACTIONS = Object.freeze([
  "ping",
  "doctor",
  "info",
  "quality_check",
  "direct_plan",
  "direct_apply",
  "review_card",
]);

export const QUALITY_PROFILES = Object.freeze([
  "default",
  "dark-grade",
  "ui-capture-dark",
  "ui-capture-light",
]);

export const MEDIA_EXTENSIONS = Object.freeze([
  ".mp4",
  ".mov",
  ".mkv",
  ".webm",
  ".m4v",
  ".avi",
  ".ts",
  ".mts",
]);

const ALLOWED_ACTION_SET = new Set(ALLOWED_ACTIONS);
const QUALITY_PROFILE_SET = new Set(QUALITY_PROFILES);

function requireNonEmptyString(value, fieldName) {
  if (typeof value !== "string" || value.trim().length === 0) {
    throw new Error(`${fieldName} is required and must be a non-empty string.`);
  }
  return value.trim();
}

function optionalNonEmptyString(value, fieldName) {
  if (value === undefined || value === null || value === "") {
    return undefined;
  }
  if (typeof value !== "string" || value.trim().length === 0) {
    throw new Error(`${fieldName} must be a non-empty string when provided.`);
  }
  return value.trim();
}

function requireExplicitBoolean(value, fieldName, fallback = false) {
  if (value === undefined || value === null) {
    return fallback;
  }
  if (typeof value !== "boolean") {
    throw new Error(`${fieldName} must be an explicit boolean.`);
  }
  return value;
}

export function planHasUnresolvedQuestion(plan) {
  if (!plan || typeof plan !== "object") {
    return false;
  }
  const question = plan.question;
  const hasQuestion =
    typeof question === "string" ? question.trim().length > 0 : Boolean(question);
  const ambiguities = plan.ambiguities ?? plan.ambiguity;
  const hasAmbiguity = Array.isArray(ambiguities)
    ? ambiguities.length > 0
    : Boolean(ambiguities);
  return hasQuestion || hasAmbiguity;
}

/**
 * Build a strictly allowlisted Native Messaging request payload.
 * Never interpolates rejected caller strings into thrown error messages.
 */
export function buildNativeRequest(action, params = {}, options = {}) {
  if (typeof action !== "string" || !ALLOWED_ACTION_SET.has(action)) {
    throw new Error("Unsupported Native Messaging action.");
  }
  if (params === null || typeof params !== "object" || Array.isArray(params)) {
    throw new Error("params must be a plain object.");
  }

  let cleanParams = {};

  if (action === "ping" || action === "doctor") {
    cleanParams = {};
  } else if (action === "info") {
    cleanParams = {
      input_path: requireNonEmptyString(params.input_path, "input_path"),
    };
  } else if (action === "quality_check") {
    const profile = params.profile ?? "default";
    if (typeof profile !== "string" || !QUALITY_PROFILE_SET.has(profile)) {
      throw new Error(
        "profile must be one of default, dark-grade, ui-capture-dark, or ui-capture-light."
      );
    }
    cleanParams = {
      input_path: requireNonEmptyString(params.input_path, "input_path"),
      profile,
      fail_on_warning: requireExplicitBoolean(
        params.fail_on_warning,
        "fail_on_warning",
        false
      ),
    };
  } else if (action === "direct_plan") {
    cleanParams = {
      input_path: requireNonEmptyString(params.input_path, "input_path"),
      direction: requireNonEmptyString(params.direction, "direction"),
    };
    const outPath = optionalNonEmptyString(params.output_path, "output_path");
    if (outPath !== undefined) {
      cleanParams.output_path = outPath;
    }
  } else if (action === "direct_apply") {
    if (params.confirm !== true) {
      throw new Error("Explicit confirmation (confirm=true) is required before rendering.");
    }
    if (!params.plan || typeof params.plan !== "object" || Array.isArray(params.plan)) {
      throw new Error("plan must be a valid direct plan object.");
    }
    if (planHasUnresolvedQuestion(params.plan)) {
      throw new Error(
        "Cannot apply a direct plan with an unresolved question or ambiguity."
      );
    }
    cleanParams = {
      plan: params.plan,
      confirm: true,
      overwrite: requireExplicitBoolean(params.overwrite, "overwrite", false),
    };
  } else if (action === "review_card") {
    cleanParams = {
      input_path: requireNonEmptyString(params.input_path, "input_path"),
      overwrite: requireExplicitBoolean(params.overwrite, "overwrite", false),
    };
    const outPath = optionalNonEmptyString(params.output_path, "output_path");
    if (outPath !== undefined) {
      cleanParams.output_path = outPath;
    }
    if (params.frame_count !== undefined) {
      if (
        !Number.isInteger(params.frame_count) ||
        params.frame_count < 1 ||
        params.frame_count > 100
      ) {
        throw new Error("frame_count must be an integer between 1 and 100.");
      }
      cleanParams.frame_count = params.frame_count;
    }
  }

  const envelope = { action, params: cleanParams };
  if (typeof options.id === "string" || Number.isInteger(options.id)) {
    envelope.id = options.id;
  }
  return envelope;
}

export function createInitialState() {
  return {
    status: "idle",
    hostVersion: null,
    protocol: null,
    offline: false,
    requiredOk: null,
    ffmpegOk: null,
    ffmpegVersion: null,
    offlineReadinessOk: null,
    inputPath: "",
    qualityProfile: "default",
    direction: "",
    overwrite: false,
    info: null,
    qualityReport: null,
    pendingPlan: null,
    planId: null,
    assumptions: [],
    question: null,
    outputPath: null,
    reviewCard: null,
    inputSha256: null,
    receipts: [],
    lastAction: null,
    error: null,
    recentDownloads: [],
  };
}

function normalizeError(rawError, fallbackCode = "native_error") {
  if (!rawError) {
    return { code: fallbackCode, message: "An unknown error occurred." };
  }
  if (typeof rawError === "string") {
    return { code: fallbackCode, message: rawError };
  }
  return {
    code: typeof rawError.code === "string" ? rawError.code : fallbackCode,
    message:
      typeof rawError.message === "string" && rawError.message.trim().length > 0
        ? rawError.message
        : "Native host operation failed.",
  };
}

function reduceActionSuccess(state, action, payload) {
  if (!payload || typeof payload !== "object") {
    return {
      ...state,
      status: "error",
      lastAction: action,
      error: normalizeError("Malformed response from native host.", "invalid_response"),
    };
  }
  if (payload.success === false) {
    return {
      ...state,
      status: "error",
      lastAction: action,
      error: normalizeError(payload.error),
    };
  }

  if (action === "ping") {
    return {
      ...state,
      status: "ready",
      lastAction: "ping",
      hostVersion: typeof payload.version === "string" ? payload.version : state.hostVersion,
      protocol: typeof payload.protocol === "string" ? payload.protocol : state.protocol,
      offline: Boolean(payload.offline),
      error: null,
    };
  }

  if (action === "doctor") {
    const ffmpeg = payload.ffmpeg && typeof payload.ffmpeg === "object" ? payload.ffmpeg : {};
    const offlineReadiness =
      payload.offline_readiness && typeof payload.offline_readiness === "object"
        ? payload.offline_readiness
        : {};
    return {
      ...state,
      status: state.status === "idle" || state.status === "connecting" ? "ready" : state.status,
      lastAction: "doctor",
      requiredOk: Boolean(payload.required_ok),
      offline: typeof payload.offline === "boolean" ? payload.offline : state.offline,
      ffmpegOk: typeof ffmpeg.ok === "boolean" ? ffmpeg.ok : state.ffmpegOk,
      ffmpegVersion: typeof ffmpeg.version === "string" ? ffmpeg.version : state.ffmpegVersion,
      offlineReadinessOk:
        typeof offlineReadiness.ok === "boolean"
          ? offlineReadiness.ok
          : state.offlineReadinessOk,
      error: null,
    };
  }

  if (action === "info") {
    return {
      ...state,
      status: "done",
      lastAction: "info",
      info: payload.info && typeof payload.info === "object" ? payload.info : payload,
      error: null,
    };
  }

  if (action === "quality_check") {
    return {
      ...state,
      status: "done",
      lastAction: "quality_check",
      qualityReport:
        payload.report && typeof payload.report === "object" ? payload.report : payload,
      error: null,
    };
  }

  if (action === "direct_plan") {
    const plan = payload.plan && typeof payload.plan === "object" ? payload.plan : null;
    return {
      ...state,
      status: "plan_ready",
      lastAction: "direct_plan",
      pendingPlan: plan,
      planId: typeof payload.plan_id === "string" ? payload.plan_id : null,
      assumptions: Array.isArray(payload.assumptions) ? payload.assumptions : [],
      question: payload.question ?? (plan ? plan.question ?? null : null),
      outputPath: plan && typeof plan.output_path === "string" ? plan.output_path : state.outputPath,
      error: null,
    };
  }

  if (action === "direct_apply") {
    return {
      ...state,
      status: "done",
      lastAction: "direct_apply",
      pendingPlan: null,
      question: null,
      outputPath: typeof payload.output_path === "string" ? payload.output_path : state.outputPath,
      receipts: Array.isArray(payload.receipts) ? payload.receipts : [],
      error: null,
    };
  }

  if (action === "review_card") {
    const sha = typeof payload.input_sha256 === "string" ? payload.input_sha256 : state.inputSha256;
    const outPath = typeof payload.output_path === "string" ? payload.output_path : state.outputPath;
    return {
      ...state,
      status: "done",
      lastAction: "review_card",
      reviewCard: payload,
      outputPath: outPath,
      inputSha256: sha,
      error: null,
    };
  }

  return {
    ...state,
    status: "done",
    lastAction: action,
    error: null,
  };
}

export function reduceCompanionState(state, event) {
  if (!event || typeof event !== "object") {
    return state;
  }
  switch (event.type) {
    case "CONNECTING":
      return { ...state, status: "connecting", error: null };
    case "RUNNING":
      return {
        ...state,
        status: "running",
        lastAction: event.action ?? state.lastAction,
        error: null,
      };
    case "ACTION_SUCCESS":
      return reduceActionSuccess(state, event.action, event.payload);
    case "ACTION_ERROR":
      return {
        ...state,
        status: "error",
        lastAction: event.action ?? state.lastAction,
        error: normalizeError(event.error),
      };
    case "DISCONNECTED":
      return {
        ...state,
        status: "disconnected",
        error: normalizeError(
          event.error ?? "Disconnected from local Kinocut Native Messaging host.",
          "host_disconnected"
        ),
      };
    case "SET_INPUT_PATH":
      return {
        ...state,
        inputPath: typeof event.value === "string" ? event.value : "",
      };
    case "SET_QUALITY_PROFILE":
      return QUALITY_PROFILE_SET.has(event.value)
        ? { ...state, qualityProfile: event.value }
        : state;
    case "SET_DIRECTION":
      return {
        ...state,
        direction: typeof event.value === "string" ? event.value : "",
      };
    case "SET_OVERWRITE":
      return { ...state, overwrite: Boolean(event.value) };
    case "SET_RECENT_DOWNLOADS":
      return {
        ...state,
        recentDownloads: Array.isArray(event.downloads) ? event.downloads : [],
      };
    case "CLEAR_PLAN":
      return {
        ...state,
        status: state.status === "plan_ready" ? "ready" : state.status,
        pendingPlan: null,
        planId: null,
        assumptions: [],
        question: null,
      };
    default:
      return state;
  }
}

export function basenameFromPath(filePath) {
  if (typeof filePath !== "string") {
    return "";
  }
  const trimmed = filePath.trim().replace(/[\\/]+$/, "");
  if (!trimmed) {
    return "";
  }
  const parts = trimmed.split(/[\\/]/);
  return parts[parts.length - 1] || trimmed;
}

export function isMediaFilename(filename) {
  if (typeof filename !== "string") {
    return false;
  }
  const lower = filename.trim().toLowerCase();
  return MEDIA_EXTENSIONS.some((ext) => lower.endsWith(ext));
}

export function filterMediaDownloads(downloads, limit = 15) {
  if (!Array.isArray(downloads)) {
    return [];
  }
  const seen = new Set();
  const results = [];
  for (const item of downloads) {
    if (!item || typeof item !== "object") {
      continue;
    }
    if (item.state && item.state !== "complete") {
      continue;
    }
    if (item.exists === false) {
      continue;
    }
    const filename = typeof item.filename === "string" ? item.filename.trim() : "";
    if (!filename || !isMediaFilename(filename) || seen.has(filename)) {
      continue;
    }
    seen.add(filename);
    results.push({
      id: item.id ?? results.length,
      filename,
      basename: basenameFromPath(filename),
      fileSize: typeof item.fileSize === "number" ? item.fileSize : null,
      endTime: typeof item.endTime === "string" ? item.endTime : null,
    });
    if (results.length >= limit) {
      break;
    }
  }
  return results;
}

export function formatDuration(seconds) {
  if (typeof seconds !== "number" || !Number.isFinite(seconds) || seconds < 0) {
    return "—";
  }
  if (seconds < 60) {
    return `${seconds.toFixed(1)}s`;
  }
  const mins = Math.floor(seconds / 60);
  const rem = seconds - mins * 60;
  return `${mins}:${rem.toFixed(1).padStart(4, "0")}`;
}

export function formatBytes(bytes) {
  if (typeof bytes !== "number" || !Number.isFinite(bytes) || bytes < 0) {
    return "—";
  }
  const units = ["B", "KB", "MB", "GB"];
  let value = bytes;
  let unitIdx = 0;
  while (value >= 1024 && unitIdx < units.length - 1) {
    value /= 1024;
    unitIdx += 1;
  }
  const digits = unitIdx === 0 ? 0 : 1;
  return `${value.toFixed(digits)} ${units[unitIdx]}`;
}

export function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

export function formatErrorDisplay(error) {
  if (!error) {
    return "";
  }
  if (typeof error === "string") {
    return error;
  }
  const code = typeof error.code === "string" && error.code ? `[${error.code}] ` : "";
  const message =
    typeof error.message === "string" && error.message
      ? error.message
      : "Operation failed.";
  return `${code}${message}`;
}
