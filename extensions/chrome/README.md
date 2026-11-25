# Kinocut Chrome Companion Extension

A local-first Chrome Manifest V3 extension that talks exclusively to your local Kinocut installation over Chrome's Native Messaging binary stdio protocol (`tech.kyanitelabs.kinocut`).

## Setup

### 1. Install Kinocut

Ensure Python 3.11+, FFmpeg, and Kinocut are installed in the Python environment you want Chrome to launch:

```bash
pip install kinocut==2.0.1
```

(When testing from a local checkout, use that checkout's virtual environment Python executable in step 4.)

### 2. Load the Unpacked Extension in Chrome

1. Open `chrome://extensions` (or `brave://extensions`, `edge://extensions`).
2. Enable **Developer mode** in the top-right corner.
3. Click **Load unpacked** and select this `extensions/chrome/` directory.
4. Copy the generated **32-character Extension ID** (lowercase letters `a`–`p`).

### 3. Register the Local Native Messaging Host

Run the installer with the Python interpreter that has `kinocut` installed:

```bash
python -m kinocut.native_messaging --install --extension-id <32-CHAR-EXTENSION-ID>
```

Optional flags:

- `--browser chrome|chromium|brave|edge` (default: `chrome`)
- `--target-dir <dir>` (write manifest and launcher to a custom directory)

### 4. Reload and Verify

1. Return to `chrome://extensions` and click **Reload** on **Kinocut Companion**.
2. Open the **Kinocut Companion** popup from the browser toolbar.
3. Confirm the **Host** and **FFmpeg** pills show green, select a recent local video download or paste a local file path, and run **Inspect**, **Quality Check** (`dark-grade` supported), **Review Card**, or **Preview Plan -> Confirm & Render**.

### Uninstall the Native Host

```bash
python -m kinocut.native_messaging --uninstall --browser chrome
```

## Security Model

- **Minimal MV3 permissions**: Requests only `nativeMessaging`, `downloads`, and `storage`. No `<all_urls>`, no `host_permissions`, no `content_scripts`, and no `externally_connectable`, so websites cannot message or probe the extension.
- **Strict sender verification**: The MV3 service worker rejects any runtime message whose `sender.id !== chrome.runtime.id`.
- **Single-origin host manifest**: `--install` strictly validates `--extension-id` against `^[a-p]{32}$` and pins `allowed_origins` to that single `chrome-extension://<id>/` origin.
- **Framed stdio with hard cap**: `kinocut.native_messaging` enforces Chrome's 4-byte little-endian framing with a 1 MiB (`1_048_576` byte) ceiling and fails closed on truncated, oversized, or malformed JSON frames.
- **Strict action allowlist**: Only `ping`, `doctor`, `info`, `quality_check`, `direct_plan`, `direct_apply`, and `review_card` are accepted. Unknown actions fail closed without echoing caller-supplied strings.
- **Explicit render & overwrite gates**: `direct_plan` is strictly read-only. `direct_apply` requires explicit `confirm: true`, refuses plans with unresolved questions, and keeps `overwrite: false` by default inside `output_operation(overwrite)`.
- **Redacted, value-free errors**: Native host errors use `MCPVideoError.to_dict()`, `redact_text`, and `exception_kind` so raw host paths and caller-controlled tokens are never leaked back to the browser.
