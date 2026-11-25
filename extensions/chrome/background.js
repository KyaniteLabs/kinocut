/**
 * Kinocut Companion MV3 Service Worker.
 * Bridges internal extension popup messages to the local Chrome Native Messaging host
 * ("tech.kyanitelabs.kinocut") with strict sender validation and action allowlisting.
 */

import {
  ALLOWED_ACTIONS,
  NATIVE_HOST_NAME,
  filterMediaDownloads,
} from "./popup_logic.js";

const ALLOWED_ACTION_SET = new Set(ALLOWED_ACTIONS);
const REQUEST_TIMEOUT_MS = 120_000;

let nativePort = null;
let requestCounter = 0;
const pendingRequests = new Map();

function rejectAllPending(message, code = "host_disconnected") {
  for (const [id, entry] of pendingRequests.entries()) {
    clearTimeout(entry.timer);
    pendingRequests.delete(id);
    entry.resolve({
      success: false,
      disconnected: true,
      error: { code, message },
    });
  }
}

function handlePortMessage(message) {
  if (!message || typeof message !== "object") {
    return;
  }
  const id = message.id;
  if (id !== undefined && pendingRequests.has(id)) {
    const entry = pendingRequests.get(id);
    clearTimeout(entry.timer);
    pendingRequests.delete(id);
    entry.resolve(message);
    return;
  }
  if (pendingRequests.size === 1) {
    const [onlyId, entry] = pendingRequests.entries().next().value;
    clearTimeout(entry.timer);
    pendingRequests.delete(onlyId);
    entry.resolve(message);
  }
}

function ensureNativePort() {
  if (nativePort !== null) {
    return nativePort;
  }
  const port = chrome.runtime.connectNative(NATIVE_HOST_NAME);
  port.onMessage.addListener(handlePortMessage);
  port.onDisconnect.addListener(() => {
    const lastError = chrome.runtime.lastError?.message;
    nativePort = null;
    rejectAllPending(
      lastError ||
        "Local Kinocut Native Messaging host disconnected. Verify installation with python -m kinocut.native_messaging --install.",
      "host_disconnected"
    );
  });
  nativePort = port;
  return nativePort;
}

function sendNativePayload(payload) {
  if (
    !payload ||
    typeof payload !== "object" ||
    typeof payload.action !== "string" ||
    !ALLOWED_ACTION_SET.has(payload.action)
  ) {
    return Promise.resolve({
      success: false,
      error: {
        code: "unsupported_action",
        message: "Unsupported Native Messaging action.",
      },
    });
  }

  return new Promise((resolve) => {
    let port;
    try {
      port = ensureNativePort();
    } catch (_err) {
      resolve({
        success: false,
        disconnected: true,
        error: {
          code: "host_connect_failed",
          message: "Could not connect to the local Kinocut Native Messaging host.",
        },
      });
      return;
    }

    requestCounter += 1;
    const id = `kc-${Date.now()}-${requestCounter}`;
    const timer = setTimeout(() => {
      pendingRequests.delete(id);
      resolve({
        success: false,
        error: {
          code: "request_timeout",
          message: "Native Messaging request timed out.",
        },
      });
    }, REQUEST_TIMEOUT_MS);

    pendingRequests.set(id, { resolve, timer });
    try {
      port.postMessage({
        action: payload.action,
        params: payload.params && typeof payload.params === "object" ? payload.params : {},
        id,
      });
    } catch (_err) {
      clearTimeout(timer);
      pendingRequests.delete(id);
      nativePort = null;
      resolve({
        success: false,
        disconnected: true,
        error: {
          code: "host_post_failed",
          message: "Failed to post message to the local Kinocut Native Messaging host.",
        },
      });
    }
  });
}

async function listRecentMediaDownloads(limit = 15) {
  const safeLimit = Number.isInteger(limit) && limit > 0 && limit <= 50 ? limit : 15;
  const items = await chrome.downloads.search({
    state: "complete",
    orderBy: ["-startTime"],
    limit: 50,
  });
  return {
    success: true,
    downloads: filterMediaDownloads(items, safeLimit),
  };
}

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (!sender || sender.id !== chrome.runtime.id) {
    sendResponse({
      success: false,
      error: {
        code: "unauthorized_sender",
        message: "Messages from external senders are not permitted.",
      },
    });
    return false;
  }

  if (!message || typeof message !== "object") {
    sendResponse({
      success: false,
      error: {
        code: "invalid_message",
        message: "Invalid internal extension message.",
      },
    });
    return false;
  }

  if (message.type === "native_request") {
    sendNativePayload(message.payload).then(sendResponse);
    return true;
  }

  if (message.type === "list_downloads") {
    listRecentMediaDownloads(message.limit)
      .then(sendResponse)
      .catch(() =>
        sendResponse({
          success: false,
          error: {
            code: "downloads_unavailable",
            message: "Unable to read recent Chrome downloads.",
          },
        })
      );
    return true;
  }

  if (message.type === "disconnect_host") {
    if (nativePort) {
      nativePort.disconnect();
      nativePort = null;
    }
    rejectAllPending("Disconnected by user.", "host_disconnected");
    sendResponse({ success: true });
    return false;
  }

  sendResponse({
    success: false,
    error: {
      code: "unsupported_message_type",
      message: "Unsupported internal message type.",
    },
  });
  return false;
});
