/**
 * Kinocut Companion popup controller.
 * Renders all host output exclusively via textContent and DOM nodes (no HTML injection).
 */

import {
  basenameFromPath,
  buildNativeRequest,
  createInitialState,
  formatBytes,
  formatDuration,
  formatErrorDisplay,
  planHasUnresolvedQuestion,
  reduceCompanionState,
} from "./popup_logic.js";

const STORAGE_KEYS = ["inputPath", "qualityProfile"];

const el = {
  hostMeta: document.getElementById("host-meta"),
  pillHost: document.getElementById("pill-host"),
  pillFfmpeg: document.getElementById("pill-ffmpeg"),
  pillOffline: document.getElementById("pill-offline"),
  setupBanner: document.getElementById("setup-banner"),
  setupCmd: document.getElementById("setup-cmd"),
  btnCopySetup: document.getElementById("btn-copy-setup"),
  btnReconnect: document.getElementById("btn-reconnect"),
  btnRefreshDownloads: document.getElementById("btn-refresh-downloads"),
  downloadSelect: document.getElementById("download-select"),
  inputPath: document.getElementById("input-path"),
  darkGradeToggle: document.getElementById("dark-grade-toggle"),
  profileSelect: document.getElementById("profile-select"),
  btnInspect: document.getElementById("btn-inspect"),
  btnQuality: document.getElementById("btn-quality"),
  btnReviewCard: document.getElementById("btn-review-card"),
  directionInput: document.getElementById("direction-input"),
  btnDirectPlan: document.getElementById("btn-direct-plan"),
  btnDoctor: document.getElementById("btn-doctor"),
  planBox: document.getElementById("plan-box"),
  planIdBadge: document.getElementById("plan-id-badge"),
  planQuestion: document.getElementById("plan-question"),
  planSteps: document.getElementById("plan-steps"),
  planAssumptions: document.getElementById("plan-assumptions"),
  overwriteToggle: document.getElementById("overwrite-toggle"),
  btnDirectApply: document.getElementById("btn-direct-apply"),
  btnCancelPlan: document.getElementById("btn-cancel-plan"),
  btnCopyPath: document.getElementById("btn-copy-path"),
  statusLine: document.getElementById("status-line"),
  resultBody: document.getElementById("result-body"),
  copyFeedback: document.getElementById("copy-feedback"),
};

let state = createInitialState();

function dispatch(event) {
  state = reduceCompanionState(state, event);
  render();
}

function addKvRow(container, key, value, mono = false) {
  const row = document.createElement("div");
  row.className = "kv-row";
  const k = document.createElement("span");
  k.className = "kv-key";
  k.textContent = key;
  const v = document.createElement("span");
  v.className = mono ? "kv-val mono" : "kv-val";
  v.textContent = String(value ?? "—");
  row.append(k, v);
  container.append(row);
}

function renderPills() {
  if (state.status === "disconnected") {
    el.pillHost.textContent = "Disconnected";
    el.pillHost.dataset.state = "error";
    el.hostMeta.textContent = "Native host unreachable";
  } else if (state.hostVersion) {
    el.pillHost.textContent = `v${state.hostVersion}`;
    el.pillHost.dataset.state = "ok";
    el.hostMeta.textContent = state.protocol || "kinocut-native-v1";
  } else {
    el.pillHost.textContent = state.status === "connecting" ? "Connecting…" : "Idle";
    el.pillHost.dataset.state = "neutral";
  }

  if (state.ffmpegOk === true) {
    el.pillFfmpeg.textContent = "FFmpeg OK";
    el.pillFfmpeg.dataset.state = "ok";
  } else if (state.ffmpegOk === false) {
    el.pillFfmpeg.textContent = "FFmpeg missing";
    el.pillFfmpeg.dataset.state = "error";
  } else {
    el.pillFfmpeg.textContent = "FFmpeg";
    el.pillFfmpeg.dataset.state = "neutral";
  }

  el.pillOffline.textContent = state.offline ? "Offline" : "Local";
  el.pillOffline.dataset.state = state.offline ? "warn" : "ok";
}

function renderDownloads() {
  const current = el.downloadSelect.value;
  el.downloadSelect.replaceChildren();
  const placeholder = document.createElement("option");
  placeholder.value = "";
  placeholder.textContent =
    state.recentDownloads.length > 0
      ? "Select a downloaded clip…"
      : "No recent local video downloads found";
  el.downloadSelect.append(placeholder);

  for (const item of state.recentDownloads) {
    const opt = document.createElement("option");
    opt.value = item.filename;
    const sizeText = item.fileSize !== null ? ` (${formatBytes(item.fileSize)})` : "";
    opt.textContent = `${item.basename}${sizeText}`;
    el.downloadSelect.append(opt);
  }
  if (current) {
    el.downloadSelect.value = current;
  }
}

function renderPlanBox() {
  const hasPlan = Boolean(state.pendingPlan);
  el.planBox.hidden = !hasPlan;
  if (!hasPlan) {
    return;
  }
  el.planIdBadge.textContent = state.planId ? state.planId.slice(0, 12) : "";
  const unresolved = planHasUnresolvedQuestion(state.pendingPlan) || Boolean(state.question);
  if (unresolved) {
    el.planQuestion.hidden = false;
    el.planQuestion.textContent = `Clarification needed before render: ${state.question || "Resolve plan ambiguity."}`;
  } else {
    el.planQuestion.hidden = true;
    el.planQuestion.textContent = "";
  }

  el.planSteps.replaceChildren();
  const steps = Array.isArray(state.pendingPlan.steps) ? state.pendingPlan.steps : [];
  for (const step of steps) {
    const li = document.createElement("li");
    li.textContent = `${step.tool || "step"} → ${basenameFromPath(step.args?.output_path || state.pendingPlan.output_path || "")}`;
    el.planSteps.append(li);
  }

  el.planAssumptions.replaceChildren();
  for (const note of state.assumptions) {
    const li = document.createElement("li");
    li.textContent = String(note);
    el.planAssumptions.append(li);
  }

  el.btnDirectApply.disabled = state.status === "running" || unresolved;
}

function renderResultBody() {
  el.resultBody.replaceChildren();
  const busy = state.status === "running" || state.status === "connecting";

  if (state.error) {
    el.statusLine.textContent = formatErrorDisplay(state.error);
    el.statusLine.dataset.state = "error";
  } else if (busy) {
    el.statusLine.textContent = `Running ${state.lastAction || "request"}…`;
    el.statusLine.dataset.state = "neutral";
  } else if (state.status === "plan_ready") {
    el.statusLine.textContent = "Plan ready. Review steps above, then click Confirm & Render.";
    el.statusLine.dataset.state = "ok";
  } else if (state.status === "done") {
    el.statusLine.textContent = `Completed ${state.lastAction || "action"}.`;
    el.statusLine.dataset.state = "ok";
  } else {
    el.statusLine.textContent = "Ready.";
    el.statusLine.dataset.state = "neutral";
  }

  if (state.lastAction === "info" && state.info) {
    addKvRow(el.resultBody, "File", basenameFromPath(state.info.path || state.inputPath));
    addKvRow(el.resultBody, "Resolution", state.info.resolution || `${state.info.width}x${state.info.height}`);
    addKvRow(el.resultBody, "Duration", formatDuration(state.info.duration));
    addKvRow(el.resultBody, "FPS", state.info.fps ? `${state.info.fps}` : "—");
    addKvRow(el.resultBody, "Codec", state.info.codec || "—");
    addKvRow(el.resultBody, "Size", formatBytes(state.info.size_bytes));
  } else if (state.lastAction === "quality_check" && state.qualityReport) {
    const rep = state.qualityReport;
    addKvRow(el.resultBody, "Score", rep.overall_score !== undefined ? `${rep.overall_score}/100` : "—");
    addKvRow(el.resultBody, "Passed", rep.all_passed ? "Yes" : "No");
    addKvRow(el.resultBody, "Profile", rep.profile?.name || state.qualityProfile);
  } else if (state.lastAction === "review_card" && state.reviewCard) {
    addKvRow(el.resultBody, "Review card", state.reviewCard.output_path, true);
    addKvRow(el.resultBody, "SHA-256", (state.inputSha256 || "").slice(0, 16), true);
    addKvRow(el.resultBody, "Frames", state.reviewCard.frame_count);
  } else if (state.lastAction === "direct_apply" && state.outputPath) {
    addKvRow(el.resultBody, "Output", state.outputPath, true);
    addKvRow(el.resultBody, "Steps run", state.receipts.length);
  } else if (state.lastAction === "doctor") {
    addKvRow(el.resultBody, "Required OK", state.requiredOk ? "Yes" : "No");
    addKvRow(el.resultBody, "FFmpeg", state.ffmpegVersion || (state.ffmpegOk ? "Available" : "Missing"));
    addKvRow(el.resultBody, "Offline ready", state.offlineReadinessOk ? "Yes" : "Partial");
  }
}

function render() {
  renderPills();
  renderDownloads();
  renderPlanBox();
  renderResultBody();

  const busy = state.status === "running" || state.status === "connecting";
  const disconnected = state.status === "disconnected";
  el.setupBanner.hidden = !disconnected;
  if (disconnected) {
    const extId = chrome.runtime?.id || "<32-CHAR-EXTENSION-ID>";
    el.setupCmd.textContent = `python -m kinocut.native_messaging --install --extension-id ${extId}`;
  }

  el.inputPath.value = state.inputPath;
  el.profileSelect.value = state.qualityProfile;
  el.darkGradeToggle.checked = state.qualityProfile === "dark-grade";
  el.overwriteToggle.checked = state.overwrite;

  const hasInput = state.inputPath.trim().length > 0;
  el.btnInspect.disabled = busy || disconnected || !hasInput;
  el.btnQuality.disabled = busy || disconnected || !hasInput;
  el.btnReviewCard.disabled = busy || disconnected || !hasInput;
  el.btnDirectPlan.disabled =
    busy || disconnected || !hasInput || state.direction.trim().length === 0;
  el.btnDoctor.disabled = busy || disconnected;
  el.btnCopyPath.disabled = !state.outputPath && !hasInput;
}

function persistSettings() {
  chrome.storage.local.set({
    inputPath: state.inputPath,
    qualityProfile: state.qualityProfile,
  });
}

async function runNativeAction(action, params = {}) {
  let payload;
  try {
    payload = buildNativeRequest(action, params);
  } catch (err) {
    dispatch({
      type: "ACTION_ERROR",
      action,
      error: { code: "validation_error", message: err.message },
    });
    return null;
  }

  dispatch({ type: "RUNNING", action });
  const response = await chrome.runtime.sendMessage({
    type: "native_request",
    payload,
  });

  if (response?.disconnected) {
    dispatch({ type: "DISCONNECTED", error: response.error });
    return null;
  }
  dispatch({ type: "ACTION_SUCCESS", action, payload: response });
  return response;
}

async function refreshDownloads() {
  const response = await chrome.runtime.sendMessage({
    type: "list_downloads",
    limit: 15,
  });
  if (response?.success && Array.isArray(response.downloads)) {
    dispatch({ type: "SET_RECENT_DOWNLOADS", downloads: response.downloads });
  }
}

async function bootstrap() {
  const stored = await chrome.storage.local.get(STORAGE_KEYS);
  if (typeof stored.inputPath === "string") {
    dispatch({ type: "SET_INPUT_PATH", value: stored.inputPath });
  }
  if (typeof stored.qualityProfile === "string") {
    dispatch({ type: "SET_QUALITY_PROFILE", value: stored.qualityProfile });
  }
  await refreshDownloads();
  dispatch({ type: "CONNECTING" });
  const ping = await runNativeAction("ping");
  if (ping?.success) {
    await runNativeAction("doctor");
  }
}

async function copyText(text, label) {
  try {
    await navigator.clipboard.writeText(text);
    el.copyFeedback.textContent = `${label} copied.`;
    setTimeout(() => {
      el.copyFeedback.textContent = "";
    }, 2000);
  } catch (_err) {
    el.copyFeedback.textContent = "Clipboard unavailable.";
  }
}

el.downloadSelect.addEventListener("change", (ev) => {
  const chosen = ev.target.value;
  if (chosen) {
    dispatch({ type: "SET_INPUT_PATH", value: chosen });
    persistSettings();
  }
});

el.inputPath.addEventListener("input", (ev) => {
  dispatch({ type: "SET_INPUT_PATH", value: ev.target.value });
  persistSettings();
});

el.profileSelect.addEventListener("change", (ev) => {
  dispatch({ type: "SET_QUALITY_PROFILE", value: ev.target.value });
  persistSettings();
});

el.darkGradeToggle.addEventListener("change", (ev) => {
  dispatch({
    type: "SET_QUALITY_PROFILE",
    value: ev.target.checked ? "dark-grade" : "default",
  });
  persistSettings();
});

el.directionInput.addEventListener("input", (ev) => {
  dispatch({ type: "SET_DIRECTION", value: ev.target.value });
});

el.overwriteToggle.addEventListener("change", (ev) => {
  dispatch({ type: "SET_OVERWRITE", value: ev.target.checked });
});

el.btnRefreshDownloads.addEventListener("click", refreshDownloads);
el.btnReconnect.addEventListener("click", bootstrap);
el.btnCopySetup.addEventListener("click", () => copyText(el.setupCmd.textContent, "Command"));
el.btnInspect.addEventListener("click", () =>
  runNativeAction("info", { input_path: state.inputPath })
);
el.btnQuality.addEventListener("click", () =>
  runNativeAction("quality_check", {
    input_path: state.inputPath,
    profile: state.qualityProfile,
  })
);
el.btnReviewCard.addEventListener("click", () =>
  runNativeAction("review_card", {
    input_path: state.inputPath,
    overwrite: state.overwrite,
  })
);
el.btnDoctor.addEventListener("click", () => runNativeAction("doctor"));
el.btnDirectPlan.addEventListener("click", () =>
  runNativeAction("direct_plan", {
    input_path: state.inputPath,
    direction: state.direction,
  })
);
el.btnDirectApply.addEventListener("click", () =>
  runNativeAction("direct_apply", {
    plan: state.pendingPlan,
    confirm: true,
    overwrite: state.overwrite,
  })
);
el.btnCancelPlan.addEventListener("click", () => dispatch({ type: "CLEAR_PLAN" }));
el.btnCopyPath.addEventListener("click", () =>
  copyText(state.outputPath || state.inputPath, "Path")
);

bootstrap();
