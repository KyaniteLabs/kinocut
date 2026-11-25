"""Image analysis engine — color extraction, palette generation, product analysis.

Pure Python (no FFmpeg). Requires optional deps: Pillow, scikit-learn, webcolors.
The pinned install command for the ``image`` extra comes from
``kinocut._install_hints.pip_install_hint("image")``.
"""

from __future__ import annotations

import colorsys
import contextlib
import ipaddress
import socket
from typing import Any
import os
from urllib.parse import urlsplit

from ._install_hints import pip_install_hint, pinned_requirement
from .defaults import (
    DEFAULT_PRODUCT_DESCRIPTION_MAX_TOKENS,
    ENV_PRODUCT_DESCRIPTION_MAX_TOKENS,
    token_budget,
    DEFAULT_VISION_BASE_URL,
    DEFAULT_VISION_MODEL,
    DEFAULT_VISION_PROVIDER_TIMEOUT,
)
from .errors import MCPVideoError
from .image_models import (
    ColorExtractionResult,
    DominantColor,
    PaletteColor,
    PaletteResult,
    ProductAnalysisResult,
)
from .validation_errors import rejected_value
from .offline import is_loopback_url, require_offline_allowed_url
from .openai_compat import chat_completion, completions_url

SUPPORTED_EXTENSIONS = frozenset({".jpg", ".jpeg", ".png", ".bmp", ".gif", ".tiff", ".tif", ".webp"})
MAX_IMAGE_PIXELS = 50_000_000  # ~50 MP (e.g. 7168x7168); guards against decompression bombs (H5)

# Legacy Anthropic-compatible description adapter. Permission is independent
# of endpoint configuration and credentials; host image inspection needs neither.
ENV_VISION_BASE_URL = "KINOCUT_VISION_BASE_URL"
ENV_VISION_MODEL = "KINOCUT_VISION_MODEL"
VISION_LOCAL_HINT = "Set KINOCUT_VISION_BASE_URL to your loopback LFM3-VL-2B server."


def resolve_vision_endpoint(
    base_url: str | None = None,
    model: str | None = None,
    *,
    environ=None,
) -> dict[str, Any]:
    """Resolve the AI-description endpoint (param > env). No network call.

    Returns base_url (None = Anthropic cloud default), model id, and the
    endpoint kind ("local" / "custom" / None when no endpoint override is set).
    Remote non-Anthropic endpoints must use HTTPS; raises MCPVideoError otherwise.
    """
    env = os.environ if environ is None else environ
    resolved_url = (base_url or env.get(ENV_VISION_BASE_URL) or env.get("LFM3_VL_URL") or "").strip() or None
    resolved_model = (model or env.get(ENV_VISION_MODEL) or "").strip() or None
    style = env.get("KINOCUT_VISION_API_STYLE", "").strip().lower()
    if style not in {"", "openai", "anthropic"}:
        raise MCPVideoError("KINOCUT_VISION_API_STYLE must be openai or anthropic", code="invalid_parameter")
    kind = None
    if resolved_url:
        try:
            parsed = urlsplit(resolved_url)
            if (
                not parsed.hostname
                or parsed.scheme not in {"http", "https"}
                or parsed.username is not None
                or parsed.password is not None
                or parsed.fragment
                or parsed.query
                or parsed.port == 0
                or any(char.isspace() for char in resolved_url)
                or "\\" in resolved_url
            ):
                raise ValueError
        except ValueError:
            raise MCPVideoError(
                "Vision endpoint must be an HTTP(S) URL without credentials", error_type="validation_error"
            ) from None
        if not is_loopback_url(resolved_url):
            if parsed.scheme != "https":
                raise MCPVideoError(
                    "Remote vision endpoints must use HTTPS. Use a local loopback endpoint for HTTP.",
                    error_type="validation_error",
                    code="insecure_endpoint",
                )
            kind = "custom"
        else:
            kind = "local"
            path = parsed.path.rstrip("/")
            if not style:
                # A loopback base URL names an OpenAI-compatible server unless
                # its path says otherwise; a bare host keeps the legacy
                # Anthropic-compatible Messages route.
                if path.endswith("/v1/messages"):
                    style = "anthropic"
                elif (
                    path.endswith("/v1")
                    or path.endswith("/v1/chat/completions")
                    or (not base_url and not env.get(ENV_VISION_BASE_URL) and env.get("LFM3_VL_URL"))
                ):
                    style = "openai"
    if style == "openai" and not resolved_url:
        raise MCPVideoError("OpenAI-compatible vision requires KINOCUT_VISION_BASE_URL", code="invalid_parameter")
    return {
        "base_url": resolved_url,
        "model": resolved_model or ("LFM3-VL-2B" if style == "openai" else DEFAULT_VISION_MODEL),
        "endpoint_kind": kind,
        **({"api_style": style} if style else {}),
    }


def _resolve_vision_api_key(endpoint: dict[str, Any]) -> str:
    """API key for the vision call. Local endpoints need no cloud credential.

    Custom remote endpoints use KINOCUT_VISION_API_KEY (separate from Anthropic's
    cloud key) to prevent credential leakage to arbitrary destinations.
    """
    if endpoint["endpoint_kind"] == "local":
        # No cloud auth exists to fail; the SDK merely requires a non-empty key.
        return "local-endpoint"
    if endpoint["endpoint_kind"] == "custom":
        custom_key = os.environ.get("KINOCUT_VISION_API_KEY")
        if custom_key:
            return custom_key
        raise MCPVideoError(
            "KINOCUT_VISION_API_KEY environment variable is required for custom "
            "remote vision endpoints. Do not use ANTHROPIC_API_KEY for non-Anthropic endpoints.",
            error_type="auth_error",
            code="missing_custom_api_key",
        )
    # Cloud (Anthropic official): use ANTHROPIC_API_KEY
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if api_key:
        return api_key
    raise MCPVideoError(
        "ANTHROPIC_API_KEY environment variable is required for AI descriptions "
        "(or point KINOCUT_VISION_BASE_URL at a local endpoint).",
        error_type="auth_error",
        code="missing_api_key",
    )


def _require_public_vision_endpoint(url: str) -> None:
    """Refuse to send KINOCUT_VISION_API_KEY to a host that resolves off the public internet.

    The endpoint was already checked for an HTTPS scheme; this closes the
    DNS-rebinding case where a public-looking name resolves to a loopback,
    link-local, private or otherwise non-global address.
    """
    host = urlsplit(url).hostname or ""
    try:
        infos = socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)
        addresses = [_public_address(info[4][0]) for info in infos]
    except (OSError, ValueError) as exc:
        raise MCPVideoError(
            "Remote vision endpoint host could not be resolved to a public address",
            error_type="validation_error",
            code="unsafe_endpoint",
        ) from exc
    if not addresses or any(address is None for address in addresses):
        raise MCPVideoError(
            "Remote vision endpoints must resolve to public addresses; private, loopback and "
            "link-local destinations are refused",
            error_type="validation_error",
            code="ssrf_blocked",
        )


def _public_address(value: str) -> str | None:
    try:
        address = ipaddress.ip_address(value)
    except ValueError:
        return None
    for candidate in (address.ipv4_mapped if address.version == 6 else None, address):
        if candidate is None:
            continue
        if candidate.version == 6 and candidate.sixtofour is not None:
            candidate = candidate.sixtofour
        if candidate.version == 6 and candidate.teredo is not None:
            candidate = candidate.teredo[1]
        if not candidate.is_global or candidate.is_multicast:
            return None
    return value


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _require_image_deps() -> None:
    """Raise a helpful error if optional image deps are not installed."""
    try:
        import PIL.Image  # noqa: F401
    except ImportError:
        hint = pip_install_hint("image")
        raise MCPVideoError(
            f"Image analysis requires optional dependencies. Install with: {hint}"
            f" (under the Hermes plugin's uvx launcher, start the server with"
            f" uvx --from '{pinned_requirement('image')}' kinocut instead)",
            error_type="dependency_error",
            code="missing_optional_dep",
            suggested_action={
                "auto_fix": False,
                "description": f"Run: {hint}, or for the uvx launcher: uvx --from '{pinned_requirement('image')}' kinocut",
            },
        ) from None


VIDEO_EXTENSIONS = frozenset({".mp4", ".mov", ".webm", ".m4v", ".mkv", ".avi"})


def _validate_image(path: str) -> None:
    """Check file exists and is a supported image or video format."""
    if not os.path.isfile(path):
        raise MCPVideoError(
            "File not found",
            error_type="input_error",
            code="file_not_found",
        )
    ext = os.path.splitext(path)[1].lower()
    if ext not in SUPPORTED_EXTENSIONS and ext not in VIDEO_EXTENSIONS:
        raise MCPVideoError(
            (
                f"Unsupported format: {ext}. "
                f"Supported images: {', '.join(sorted(SUPPORTED_EXTENSIONS))}. "
                f"Supported videos: {', '.join(sorted(VIDEO_EXTENSIONS))}"
            ),
            error_type="validation_error",
            code="unsupported_format",
        )


def _extract_frame_if_video(path: str) -> str:
    """If path is a video, extract a frame and return the temp frame path."""
    ext = os.path.splitext(path)[1].lower()
    if ext not in VIDEO_EXTENSIONS:
        return path
    from .engine_thumbnail import thumbnail
    import secrets
    import tempfile

    frame_path = os.path.join(tempfile.gettempdir(), f"mcp_video_frame_{secrets.token_hex(16)}.jpg")
    try:
        result = thumbnail(path, output_path=frame_path)
    except BaseException:
        _remove_quietly(frame_path)
        raise
    return result.frame_path


def _remove_quietly(path: str) -> None:
    with contextlib.suppress(OSError):
        os.remove(path)


@contextlib.contextmanager
def _analysis_image(path: str):
    """Yield the image to analyze, always removing a frame extracted from a video."""
    frame_path = _extract_frame_if_video(path)
    try:
        yield frame_path
    finally:
        if frame_path != path:
            _remove_quietly(frame_path)


def _open_image_safe(path: str) -> Any:
    """Open an image with Pillow, rejecting decompression bombs up front (H5).

    Pillow reads image dimensions lazily from the header, so the decoded pixel
    count can be vetted before the full RGB buffer is allocated.
    """
    from PIL import Image

    # Cap decoded image size process-wide; Pillow raises DecompressionBombError
    # for images far exceeding this ceiling.
    Image.MAX_IMAGE_PIXELS = MAX_IMAGE_PIXELS

    try:
        img = Image.open(path)
    except Image.DecompressionBombError as exc:
        raise MCPVideoError(
            f"Image {rejected_value(path)} exceeds the {MAX_IMAGE_PIXELS:,}-pixel decompression-bomb ceiling.",
            error_type="validation_error",
            code="image_too_large",
        ) from exc

    pixels = img.width * img.height
    if pixels > MAX_IMAGE_PIXELS:
        raise MCPVideoError(
            f"Image {rejected_value(path)} is {img.width}x{img.height} ({pixels:,} pixels), exceeding the "
            f"{MAX_IMAGE_PIXELS:,}-pixel ceiling. Use a smaller image.",
            error_type="validation_error",
            code="image_too_large",
        )
    return img


def _rgb_to_hex(r: int, g: int, b: int) -> str:
    """Convert RGB (0-255) to hex string like '#8B4513'."""
    return f"#{r:02X}{g:02X}{b:02X}"


def _rgb_to_hsl(r: int, g: int, b: int) -> tuple[float, float, float]:
    """Convert RGB (0-255) to HSL (0-1 range)."""
    return colorsys.rgb_to_hls(r / 255.0, g / 255.0, b / 255.0)


def _hsl_to_rgb(h: float, s: float, lightness: float) -> tuple[int, int, int]:
    """Convert HSL (0-1 range) to RGB (0-255)."""
    r, g, b = colorsys.hls_to_rgb(h, lightness, s)
    return (round(r * 255), round(g * 255), round(b * 255))


def _closest_color_name(r: int, g: int, b: int) -> str:
    """Find the nearest CSS color name for an RGB value using webcolors."""
    try:
        import webcolors
    except ImportError:
        return _rgb_to_hex(r, g, b)

    try:
        return webcolors.hex_to_name(_rgb_to_hex(r, g, b))
    except ValueError:
        pass

    # Find closest by Euclidean distance
    best_name = ""
    best_dist = float("inf")
    for name in webcolors.names(webcolors.CSS3):
        try:
            hex_val = webcolors.name_to_hex(name)
        except ValueError:
            continue
        cr = int(hex_val[1:3], 16)
        cg = int(hex_val[3:5], 16)
        cb = int(hex_val[5:7], 16)
        dist = (r - cr) ** 2 + (g - cg) ** 2 + (b - cb) ** 2
        if dist < best_dist:
            best_dist = dist
            best_name = name
    return best_name


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def extract_colors(
    image_path: str,
    n_colors: int = 5,
) -> ColorExtractionResult:
    """Extract dominant colors from an image using K-means clustering."""
    _require_image_deps()
    _validate_image(image_path)

    if n_colors < 1 or n_colors > 20:
        raise MCPVideoError(
            "n_colors must be between 1 and 20",
            error_type="validation_error",
            code="invalid_n_colors",
        )

    import numpy as np
    from sklearn.cluster import MiniBatchKMeans

    # A video input is analyzed through a representative frame that is
    # removed afterwards; the result keeps the path the caller supplied.
    with _analysis_image(image_path) as frame_path:
        img = _open_image_safe(frame_path).convert("RGB")
        # Resize for speed — max 200px on the longest side
        img.thumbnail((200, 200))
        pixels = np.array(img).reshape(-1, 3).astype(float)
        if len(pixels) > 50000:
            pixels = pixels[:50000]

        kmeans = MiniBatchKMeans(n_clusters=n_colors, random_state=42, n_init=3)
        labels = kmeans.fit_predict(pixels)

        # Count pixels per cluster
        histogram = np.bincount(labels)
        counts = {label: int(histogram[label]) for label in dict.fromkeys(labels.tolist())}
        total = len(labels)

        # Sort by pixel count descending
        sorted_clusters = sorted(counts.items(), key=lambda x: x[1], reverse=True)

        colors: list[DominantColor] = []
        for cluster_id, count in sorted_clusters:
            center = kmeans.cluster_centers_[cluster_id]
            r, g, b = round(center[0]), round(center[1]), round(center[2])
            r = max(0, min(255, r))
            g = max(0, min(255, g))
            b = max(0, min(255, b))
            colors.append(
                DominantColor(
                    hex=_rgb_to_hex(r, g, b),
                    rgb=(r, g, b),
                    name=_closest_color_name(r, g, b),
                    percentage=round(count / total * 100, 1),
                )
            )

        return ColorExtractionResult(
            image_path=image_path,
            colors=colors,
            n_colors=n_colors,
        )


def generate_palette(
    image_path: str,
    harmony: str = "complementary",
    n_colors: int = 5,
) -> PaletteResult:
    """Generate a color harmony palette from an image's dominant color."""
    _require_image_deps()
    _validate_image(image_path)

    valid_harmonies = {"complementary", "analogous", "triadic", "split_complementary"}
    if harmony not in valid_harmonies:
        raise MCPVideoError(
            f"Invalid harmony '{rejected_value(harmony)}'. Valid options: {', '.join(sorted(valid_harmonies))}",
            error_type="validation_error",
            code="invalid_harmony",
        )

    with _analysis_image(image_path) as frame_path:
        # Get dominant color
        extraction = extract_colors(frame_path, n_colors=n_colors)
        source = extraction.colors[0]
        r, g, b = source.rgb

        # Convert to HSL for harmony math
        h, lightness, s = _rgb_to_hsl(r, g, b)

        # Harmony rotation rules
        harmony_offsets: dict[str, list[float]] = {
            "complementary": [0.0, 0.5],
            "analogous": [0.0, 1 / 12, -1 / 12, 2 / 12, -2 / 12],
            "triadic": [0.0, 1 / 3, 2 / 3],
            "split_complementary": [0.0, 150 / 360, 210 / 360],
        }
        offsets = harmony_offsets[harmony]

        role_names: dict[str, list[str]] = {
            "complementary": ["base", "complement"],
            "analogous": ["base", "analogous1", "analogous2", "analogous3", "analogous4"],
            "triadic": ["base", "triadic1", "triadic2"],
            "split_complementary": ["base", "split1", "split2"],
        }

        palette: list[PaletteColor] = []
        for i, offset in enumerate(offsets):
            new_h = (h + offset) % 1.0
            nr, ng, nb = _hsl_to_rgb(new_h, s, lightness)
            role = role_names[harmony][i] if i < len(role_names[harmony]) else f"accent{i}"
            palette.append(
                PaletteColor(
                    hex=_rgb_to_hex(nr, ng, nb),
                    rgb=(nr, ng, nb),
                    role=role,
                )
            )

        return PaletteResult(
            image_path=image_path,
            harmony=harmony,
            palette=palette,
            source_color=source,
        )


def _strip_vision_bearer_auth(request: Any) -> None:
    """This API-key adapter must never send an SDK-discovered bearer credential."""
    request.headers.pop("Authorization", None)


def _describe_product_with_vision(
    image_path: str,
    base_url: str | None = None,
    model: str | None = None,
) -> str:
    """Return an AI text description of ``image_path`` (opt-in vision call).

    KINOCUT_VISION_MODE must explicitly permit this route.
    """
    from .vision_policy import require_vision_provider, strip_think_blocks

    require_offline_allowed_url(
        (
            base_url or os.environ.get(ENV_VISION_BASE_URL) or os.environ.get("LFM3_VL_URL") or DEFAULT_VISION_BASE_URL
        ).strip(),
        feature="Vision",
        local_alternative=VISION_LOCAL_HINT,
    )
    endpoint = resolve_vision_endpoint(base_url, model)
    require_vision_provider(endpoint["endpoint_kind"])
    if endpoint.get("api_style") == "openai":
        if endpoint["endpoint_kind"] == "custom":
            _require_public_vision_endpoint(endpoint["base_url"])
        mime_type, img_data = _encoded_vision_image(image_path)
        text = chat_completion(
            completions_url(endpoint["base_url"]),
            {
                "model": endpoint["model"],
                "max_tokens": token_budget(ENV_PRODUCT_DESCRIPTION_MAX_TOKENS, DEFAULT_PRODUCT_DESCRIPTION_MAX_TOKENS),
                "messages": [
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": _PRODUCT_PROMPT},
                            _openai_image(mime_type, img_data),
                        ],
                    }
                ],
            },
            feature="Vision",
            local_alternative=VISION_LOCAL_HINT,
            key=_openai_vision_key(endpoint),
        )
        return strip_think_blocks(text)
    return _describe_anthropic(endpoint, image_path)


def _openai_vision_key(endpoint: dict[str, Any]) -> str | None:
    """Bearer key for the OpenAI-compatible route; loopback servers may require one."""
    if endpoint["endpoint_kind"] == "custom":
        return _resolve_vision_api_key(endpoint)
    return os.environ.get("KINOCUT_VISION_API_KEY") or None


_PRODUCT_PROMPT = (
    "Describe this product image concisely in 2-3 sentences. "
    "Focus on the product type, colors, and key visual features."
)


def _openai_image(mime_type: str, data: str) -> dict:
    return {"type": "image_url", "image_url": {"url": f"data:{mime_type};base64,{data}"}}


def _encoded_vision_image(image_path: str) -> tuple[str, str]:
    import base64
    import mimetypes

    with open(image_path, "rb") as source:
        return mimetypes.guess_type(image_path)[0] or "image/jpeg", base64.b64encode(source.read()).decode()


def _describe_anthropic(endpoint: dict, image_path: str) -> str:
    if os.environ.get("ANTHROPIC_CUSTOM_HEADERS", "").strip():
        raise MCPVideoError(
            "The vision adapter does not accept ANTHROPIC_CUSTOM_HEADERS; unset it to prevent inherited "
            "credentials or headers from reaching a different endpoint.",
            error_type="validation_error",
            code="unsafe_vision_headers",
        )
    if endpoint["endpoint_kind"] == "custom":
        _require_public_vision_endpoint(endpoint["base_url"])
    try:
        import anthropic
    except ImportError:
        hint = pip_install_hint("image-ai")
        raise MCPVideoError(
            f"AI description requires the anthropic package. Install with: {hint}",
            error_type="dependency_error",
            code="missing_ai_dep",
            suggested_action={
                "auto_fix": False,
                "description": f"Run: {hint}",
            },
        ) from None

    import httpx

    api_key = _resolve_vision_api_key(endpoint)
    mime_type, img_data = _encoded_vision_image(image_path)

    with httpx.Client(
        trust_env=endpoint["endpoint_kind"] != "local",
        follow_redirects=False,
        event_hooks={"request": [_strip_vision_bearer_auth]},
    ) as transport:
        client = anthropic.Anthropic(
            api_key=api_key,
            auth_token="",
            base_url=endpoint["base_url"] or DEFAULT_VISION_BASE_URL,
            http_client=transport,
            max_retries=0,
            timeout=DEFAULT_VISION_PROVIDER_TIMEOUT,
        )
        return _request_product_description(client, endpoint["model"], mime_type, img_data)


def _request_product_description(client: Any, model: str, mime_type: str, img_data: str) -> str:
    """One bounded description request; never select a fallback provider."""
    response = client.messages.create(
        model=model,
        max_tokens=token_budget(ENV_PRODUCT_DESCRIPTION_MAX_TOKENS, DEFAULT_PRODUCT_DESCRIPTION_MAX_TOKENS),
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": mime_type,
                            "data": img_data,
                        },
                    },
                    {
                        "type": "text",
                        "text": _PRODUCT_PROMPT,
                    },
                ],
            }
        ],
    )
    from .vision_policy import strip_think_blocks

    text = next(
        (b.text for b in response.content if getattr(b, "type", "text") == "text" and getattr(b, "text", None)), ""
    )
    return strip_think_blocks(text)


def analyze_product(
    image_path: str,
    use_ai: bool = False,
    n_colors: int = 5,
    base_url: str | None = None,
    model: str | None = None,
) -> ProductAnalysisResult:
    """Analyze a product image — colors + optional AI description.

    ``base_url``/``model`` (or ``KINOCUT_VISION_BASE_URL``/``KINOCUT_VISION_MODEL``)
    configure the legacy Anthropic-compatible adapter. Provider execution is off
    unless KINOCUT_VISION_MODE explicitly permits the selected route.
    """
    _require_image_deps()
    _validate_image(image_path)

    with _analysis_image(image_path) as frame_path:
        colors_result = extract_colors(frame_path, n_colors=n_colors)

        description: str | None = None
        if use_ai:
            description = _describe_product_with_vision(frame_path, base_url, model)

    return ProductAnalysisResult(
        image_path=image_path,
        colors=colors_result.colors,
        description=description,
        ai_description=use_ai,
    )
