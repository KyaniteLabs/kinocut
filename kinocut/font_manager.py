"""Font management — download Google Fonts for use in video overlays."""

from __future__ import annotations

import os
import urllib.request
import urllib.error

from .errors import MCPVideoError

_FONT_CACHE_DIR = os.path.expanduser("~/.cache/mcp-video/fonts")

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


def resolve_font(font_name: str) -> str:
    """Return a local path to a font, downloading from Google Fonts if needed.

    Args:
        font_name: Font family name (e.g. "Roboto", "Open Sans").

    Returns:
        Absolute path to the local TTF file.

    Raises:
        MCPVideoError: If the font cannot be downloaded or found.
    """
    normalized = font_name.lower().replace(" ", "").replace("-", "")

    # Already a local file path?
    if os.path.isfile(font_name):
        return os.path.abspath(font_name)

    url = _GOOGLE_FONT_URLS.get(normalized)
    if url is None:
        raise MCPVideoError(
            f"Unknown font: '{font_name}'. Available: {list(_GOOGLE_FONT_URLS.keys())}",
            error_type="validation_error",
            code="unknown_font",
        )

    os.makedirs(_FONT_CACHE_DIR, exist_ok=True)
    local_path = os.path.join(_FONT_CACHE_DIR, f"{normalized}.ttf")

    if os.path.isfile(local_path):
        return local_path

    try:
        urllib.request.urlretrieve(url, local_path)  # noqa: S310
    except urllib.error.URLError as exc:
        raise MCPVideoError(
            f"Failed to download font '{font_name}': {exc}",
            error_type="processing_error",
            code="font_download_failed",
        ) from exc

    return local_path


def list_available_fonts() -> list[str]:
    """Return the list of built-in downloadable font names."""
    return list(_GOOGLE_FONT_URLS.keys())
