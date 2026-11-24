"""Small, bounded OpenAI chat-completions transport for configured model servers."""

import json
import urllib.error
import urllib.request
from urllib.parse import urlsplit, urlunsplit

from .defaults import DEFAULT_VISION_PROVIDER_TIMEOUT
from .errors import MCPVideoError
from .limits import MAX_VISION_RESPONSE_BYTES
from .offline import require_offline_allowed_url


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def completions_url(base_url: str) -> str:
    parsed = urlsplit(base_url)
    path = parsed.path.rstrip("/")
    if not path.endswith("/chat/completions"):
        path += "/chat/completions" if path.endswith("/v1") else "/v1/chat/completions"
    return urlunsplit(parsed._replace(path=path))


def chat_completion(url: str, payload: dict, *, feature: str, local_alternative: str, key: str | None = None) -> str:
    require_offline_allowed_url(url, feature=feature, local_alternative=local_alternative)
    headers = {"Content-Type": "application/json", "Accept-Encoding": "identity"}
    if key:
        headers["Authorization"] = f"Bearer {key}"
    request = urllib.request.Request(url, data=json.dumps(payload, allow_nan=False).encode(), headers=headers)  # noqa: S310
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect())
    try:
        with opener.open(request, timeout=DEFAULT_VISION_PROVIDER_TIMEOUT) as response:
            raw = response.read(MAX_VISION_RESPONSE_BYTES + 1)
        if len(raw) > MAX_VISION_RESPONSE_BYTES:
            raise ValueError("Response exceeds byte ceiling")
        text = json.loads(raw)["choices"][0]["message"]["content"]
        if not isinstance(text, str) or not text.strip():
            raise ValueError("Missing message content")
        return text
    except urllib.error.HTTPError as exc:
        exc.close()
        raise MCPVideoError(f"{feature} provider returned an HTTP error", error_type="processing_error") from None
    except (OSError, ValueError, KeyError, TypeError, IndexError):
        raise MCPVideoError(f"{feature} provider returned no usable response", error_type="processing_error") from None
