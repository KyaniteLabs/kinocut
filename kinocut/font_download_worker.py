"""Isolated font downloader: an allowed catalog key in, bounded bytes out.

The parent owns the elapsed deadline, process cleanup, cache descriptor and SFNT
validation. This worker has no cache paths or caller-supplied URL options.
"""

from __future__ import annotations

import logging
import sys
import time
import urllib.error
import urllib.request
from typing import BinaryIO

from .defaults import DEFAULT_FONT_DOWNLOAD_DEADLINE, DEFAULT_FONT_DOWNLOAD_TIMEOUT
from .errors import MCPVideoError
from .limits import MAX_FONT_DOWNLOAD_BYTES, MAX_FONT_DOWNLOAD_READ_BYTES

DOWNLOAD_OVER_LIMIT = 10
DOWNLOAD_INVALID = 11
DOWNLOAD_FAILED = 12

# Map of common Google Fonts names to their direct TTF URLs
_GOOGLE_FONT_URLS: dict[str, str] = {
    # Sans-serif — clean, modern
    "roboto": "https://raw.githubusercontent.com/google/fonts/main/ofl/roboto/Roboto%5Bwdth,wght%5D.ttf",
    "opensans": "https://raw.githubusercontent.com/google/fonts/main/ofl/opensans/OpenSans%5Bwdth,wght%5D.ttf",
    "lato": "https://raw.githubusercontent.com/google/fonts/main/ofl/lato/Lato-Regular.ttf",
    "montserrat": "https://raw.githubusercontent.com/google/fonts/main/ofl/montserrat/Montserrat%5Bwght%5D.ttf",
    "poppins": "https://raw.githubusercontent.com/google/fonts/main/ofl/poppins/Poppins-Regular.ttf",
    "inter": "https://raw.githubusercontent.com/google/fonts/main/ofl/inter/Inter%5Bopsz,wght%5D.ttf",
    "oswald": "https://raw.githubusercontent.com/google/fonts/main/ofl/oswald/Oswald%5Bwght%5D.ttf",
    "raleway": "https://raw.githubusercontent.com/google/fonts/main/ofl/raleway/Raleway%5Bwght%5D.ttf",
    "ubuntu": "https://raw.githubusercontent.com/google/fonts/main/ufl/ubuntu/Ubuntu-Regular.ttf",
    # Serif — editorial, magazine, book
    "playfairdisplay": "https://raw.githubusercontent.com/google/fonts/main/ofl/playfairdisplay/PlayfairDisplay%5Bwght%5D.ttf",
    "playfairdisplay-italic": "https://raw.githubusercontent.com/google/fonts/main/ofl/playfairdisplay/PlayfairDisplay-Italic%5Bwght%5D.ttf",
    "cormorant": "https://raw.githubusercontent.com/google/fonts/main/ofl/cormorant/Cormorant%5Bwght%5D.ttf",
    "cormorant-italic": "https://raw.githubusercontent.com/google/fonts/main/ofl/cormorant/Cormorant-Italic%5Bwght%5D.ttf",
    "librebaskerville": "https://raw.githubusercontent.com/google/fonts/main/ofl/librebaskerville/LibreBaskerville%5Bwght%5D.ttf",
    "librebaskerville-italic": "https://raw.githubusercontent.com/google/fonts/main/ofl/librebaskerville/LibreBaskerville-Italic%5Bwght%5D.ttf",
    "librebaskerville-bold": "https://raw.githubusercontent.com/google/fonts/main/ofl/librebaskerville/LibreBaskerville%5Bwght%5D.ttf",
    "sourceserif4": "https://raw.githubusercontent.com/google/fonts/main/ofl/sourceserif4/SourceSerif4%5Bopsz,wght%5D.ttf",
    "sourceserif4-italic": "https://raw.githubusercontent.com/google/fonts/main/ofl/sourceserif4/SourceSerif4-Italic%5Bopsz,wght%5D.ttf",
    "ebgaramond": "https://raw.githubusercontent.com/google/fonts/main/ofl/ebgaramond/EBGaramond%5Bwght%5D.ttf",
    "ebgaramond-italic": "https://raw.githubusercontent.com/google/fonts/main/ofl/ebgaramond/EBGaramond-Italic%5Bwght%5D.ttf",
    "lora": "https://raw.githubusercontent.com/google/fonts/main/ofl/lora/Lora%5Bwght%5D.ttf",
    "lora-italic": "https://raw.githubusercontent.com/google/fonts/main/ofl/lora/Lora-Italic%5Bwght%5D.ttf",
    "merriweather": "https://raw.githubusercontent.com/google/fonts/main/ofl/merriweather/Merriweather%5Bopsz,wdth,wght%5D.ttf",
    "merriweather-italic": "https://raw.githubusercontent.com/google/fonts/main/ofl/merriweather/Merriweather-Italic%5Bopsz,wdth,wght%5D.ttf",
    "cinzel": "https://raw.githubusercontent.com/google/fonts/main/ofl/cinzel/Cinzel%5Bwght%5D.ttf",
    "crimsontext": "https://raw.githubusercontent.com/google/fonts/main/ofl/crimsontext/CrimsonText-Regular.ttf",
    "crimsontext-italic": "https://raw.githubusercontent.com/google/fonts/main/ofl/crimsontext/CrimsonText-Italic.ttf",
    "crimsontext-bold": "https://raw.githubusercontent.com/google/fonts/main/ofl/crimsontext/CrimsonText-Bold.ttf",
    "fanwoodtext": "https://raw.githubusercontent.com/google/fonts/main/ofl/fanwoodtext/FanwoodText-Regular.ttf",
    "fanwoodtext-italic": "https://raw.githubusercontent.com/google/fonts/main/ofl/fanwoodtext/FanwoodText-Italic.ttf",
}
_GOOGLE_FONT_URLS = {k.lower().replace(" ", "").replace("-", ""): v for k, v in _GOOGLE_FONT_URLS.items()}


def _stream_font(key: str, output: BinaryIO) -> None:
    url = _GOOGLE_FONT_URLS.get(key)
    if url is None:
        raise MCPVideoError("Unknown font catalog key", code="font_download_invalid")
    deadline = time.monotonic() + DEFAULT_FONT_DOWNLOAD_DEADLINE
    total = 0
    with urllib.request.urlopen(url, timeout=DEFAULT_FONT_DOWNLOAD_TIMEOUT) as response:  # noqa: S310 — static HTTPS allowlist
        expected = _declared_font_size(response)
        while True:
            if time.monotonic() >= deadline:
                raise TimeoutError("Font download deadline exceeded")
            chunk = _read_font_chunk(
                response, min(MAX_FONT_DOWNLOAD_READ_BYTES, MAX_FONT_DOWNLOAD_BYTES - total + 1), deadline
            )
            if time.monotonic() >= deadline:
                raise TimeoutError("Font download deadline exceeded")
            if not chunk:
                break
            total += len(chunk)
            if total > MAX_FONT_DOWNLOAD_BYTES:
                raise MCPVideoError("Font download exceeds byte limit", code="font_download_over_limit")
            output.write(chunk)
        if expected is not None and total != expected:
            raise MCPVideoError("Font download was incomplete", code="font_download_invalid")
        output.flush()


def _read_font_chunk(response, size: int, deadline: float) -> bytes:
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise TimeoutError("Font download deadline exceeded")
    # read1 performs one underlying read; the parent deadline also covers DNS,
    # connecting, TLS and any reader implementation that ignores this timeout.
    sock = getattr(getattr(getattr(response, "fp", None), "raw", None), "_sock", None)
    if sock is not None:
        sock.settimeout(min(DEFAULT_FONT_DOWNLOAD_TIMEOUT, remaining))
    return response.read1(size)


def _declared_font_size(response) -> int | None:
    headers = getattr(response, "headers", None)
    raw = headers.get("Content-Length") if headers is not None else None
    if raw is None:
        return None
    if not isinstance(raw, str) or not raw.isascii() or not raw.isdigit() or len(raw) > 20:
        raise MCPVideoError("Font response has an invalid size", code="font_download_invalid")
    size = int(raw)
    if size > MAX_FONT_DOWNLOAD_BYTES:
        raise MCPVideoError("Font download exceeds byte limit", code="font_download_over_limit")
    return size


def main(argv: list[str]) -> int:
    if len(argv) != 1 or argv[0] not in _GOOGLE_FONT_URLS:
        sys.stderr.write("font_download_invalid\n")
        return DOWNLOAD_INVALID
    try:
        _stream_font(argv[0], sys.stdout.buffer)
        return 0
    except MCPVideoError as exc:
        code = DOWNLOAD_OVER_LIMIT if exc.code == "font_download_over_limit" else DOWNLOAD_INVALID
        sys.stderr.write("font_download_over_limit\n" if code == DOWNLOAD_OVER_LIMIT else "font_download_invalid\n")
        return code
    except (urllib.error.URLError, OSError, TimeoutError):
        sys.stderr.write("font_download_failed\n")
        return DOWNLOAD_FAILED
    except Exception as exc:  # keep network response content and tracebacks off stderr
        logging.getLogger(__name__).warning("Font download worker failed unexpectedly (%s)", type(exc).__name__[:64])
        sys.stderr.write("font_download_failed\n")
        return DOWNLOAD_FAILED


if __name__ == "__main__":  # pragma: no cover - real process entry
    raise SystemExit(main(sys.argv[1:]))
