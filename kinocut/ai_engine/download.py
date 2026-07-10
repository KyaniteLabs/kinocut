"""AI-powered video processing using machine learning models.

Optional dependencies:
    - openai-whisper: For speech-to-text transcription
    - imagehash: For AI-enhanced scene detection
    - Pillow: For image processing in scene detection
"""

from __future__ import annotations

import ipaddress as _ipaddress
import logging
import re
import shutil
import socket as _socket
import tempfile
from pathlib import Path

from ..errors import MCPVideoError, ProcessingError

logger = logging.getLogger(__name__)


def _is_blocked_ip(ip_str: str) -> bool:
    addr = _ipaddress.ip_address(ip_str)
    return addr.is_private or addr.is_loopback or addr.is_link_local or addr.is_reserved


def _response_peer_ip(resp) -> str | None:
    for path in (("fp", "raw", "_sock"), ("fp", "_sock"), ("raw", "_sock"), ("_sock",)):
        obj = resp
        for attr in path:
            obj = getattr(obj, attr, None)
            if obj is None:
                break
        if obj is None or not hasattr(obj, "getpeername"):
            continue
        peer = obj.getpeername()
        if peer:
            return peer[0]
    return None


def _validate_response_peer(resp) -> None:
    peer_ip = _response_peer_ip(resp)
    if peer_ip is None:
        raise MCPVideoError(
            "URL blocked (SSRF protection): could not verify connected peer address",
            error_type="validation_error",
            code="ssrf_peer_unknown",
        )
    try:
        if _is_blocked_ip(peer_ip):
            raise MCPVideoError(
                f"URL blocked (SSRF protection): connected peer {peer_ip}",
                error_type="validation_error",
                code="ssrf_blocked",
            )
    except ValueError:
        raise MCPVideoError(
            f"URL blocked (SSRF protection): invalid connected peer {peer_ip!r}",
            error_type="validation_error",
            code="ssrf_blocked",
        ) from None


def _is_url(s: str) -> bool:
    """Return True if *s* looks like an http/https URL."""
    return s.lower().startswith(("http://", "https://"))


def _is_http_url(s: object) -> bool:
    return isinstance(s, str) and s.lower().startswith(("http://", "https://"))


# --- SSRF protection: block private/reserved IP ranges ---
def _is_safe_url(url: str) -> bool:
    """Reject URLs that resolve to private, loopback, or link-local IPs (SSRF protection)."""
    try:
        from urllib.parse import urlparse

        parsed = urlparse(url)
        hostname = parsed.hostname
        if not hostname:
            return False
        # Resolve hostname to IP addresses (with timeout to prevent hangs).
        previous_timeout = _socket.getdefaulttimeout()
        _socket.setdefaulttimeout(10)
        try:
            addrinfos = _socket.getaddrinfo(hostname, parsed.port or 80, proto=_socket.IPPROTO_TCP)
        finally:
            _socket.setdefaulttimeout(previous_timeout)
        for _family, _type, _proto, _canonname, sockaddr in addrinfos:
            ip_str = sockaddr[0]
            if _is_blocked_ip(ip_str):
                return False
    except (_socket.gaierror, ValueError, OSError):
        return False
    return True


# Video file extensions that can be fetched directly via HTTP.
_DIRECT_VIDEO_EXTENSIONS = {
    ".mp4",
    ".mov",
    ".mkv",
    ".webm",
    ".avi",
    ".m4v",
    ".flv",
    ".wmv",
    ".ts",
    ".m2ts",
    ".mts",
}

# Hostnames that require yt-dlp (streaming platforms).
_PLATFORM_HOSTS = {
    "youtube.com",
    "youtu.be",
    "www.youtube.com",
    "vimeo.com",
    "www.vimeo.com",
    "player.vimeo.com",
    "dailymotion.com",
    "www.dailymotion.com",
    "twitch.tv",
    "www.twitch.tv",
    "clips.twitch.tv",
    "twitter.com",
    "x.com",
    "www.twitter.com",
    "instagram.com",
    "www.instagram.com",
    "tiktok.com",
    "www.tiktok.com",
    "facebook.com",
    "www.facebook.com",
    "reddit.com",
    "v.redd.it",
    "streamable.com",
    "www.streamable.com",
    "rumble.com",
    "www.rumble.com",
    "odysee.com",
    "www.odysee.com",
    "loom.com",
    "www.loom.com",
    "wistia.com",
    "www.wistia.com",
}


def _url_host(url: str) -> str:
    """Extract the hostname from a URL (no stdlib urllib needed for this)."""
    # Strip scheme
    rest = url.split("://", 1)[-1]
    # Strip path/query
    return rest.split("/")[0].split("?")[0].lower()


def _download_direct_url(url: str, dest_dir: str) -> str:
    """Download a direct video URL to *dest_dir* using urllib. Returns local path."""
    if not _is_safe_url(url):
        raise MCPVideoError(f"URL blocked (SSRF protection): {url}", error_type="validation_error", code="ssrf_blocked")

    import urllib.request
    import urllib.parse

    parsed_path = urllib.parse.urlparse(url).path
    filename = Path(parsed_path).name or "video.mp4"
    # Sanitise filename
    filename = re.sub(r"[^\w.\-]", "_", filename)
    dest = str(Path(dest_dir) / filename)

    from .. import __version__

    headers = {"User-Agent": f"mcp-video/{__version__} (+https://git.kyanitelabs.tech/KyaniteLabs/kinocut)"}
    req = urllib.request.Request(url, headers=headers)  # noqa: S310
    max_download_bytes = 2 * (1 << 30)  # 2 GiB limit
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(req, timeout=120) as resp:
        _validate_response_peer(resp)
        with open(dest, "wb") as fh:
            total = 0
            while True:
                chunk = resp.read(1 << 20)  # 1 MiB
                if not chunk:
                    break
                total += len(chunk)
                if total > max_download_bytes:
                    Path(dest).unlink(missing_ok=True)
                    raise MCPVideoError(
                        f"Download exceeded {max_download_bytes >> 30} GiB size limit",
                        error_type="resource_error",
                        code="download_size_limit",
                    )
                fh.write(chunk)
    return dest


def _iter_ytdlp_info_urls(value: object):
    """Yield network URLs from yt-dlp's nested metadata shape."""
    if isinstance(value, dict):
        for key, item in value.items():
            if key in {"url", "webpage_url", "original_url", "manifest_url"} and _is_http_url(item):
                yield item
            elif key in {"formats", "requested_formats", "requested_downloads", "entries", "fragments"}:
                yield from _iter_ytdlp_info_urls(item)
    elif isinstance(value, list | tuple):
        for item in value:
            yield from _iter_ytdlp_info_urls(item)


def _validate_ytdlp_info_urls(info: object) -> None:
    """Reject yt-dlp results that resolve media URLs to blocked networks."""
    for media_url in _iter_ytdlp_info_urls(info):
        if not _is_safe_url(media_url):
            raise MCPVideoError(
                f"URL blocked (SSRF protection): yt-dlp resolved media URL {media_url}",
                error_type="validation_error",
                code="ssrf_blocked",
            )


def _download_with_ytdlp(url: str, dest_dir: str) -> str:
    """Download a platform video URL using yt-dlp. Returns local path.

    Raises RuntimeError if yt-dlp is not installed.
    """
    try:
        import yt_dlp
    except ImportError:
        raise MCPVideoError(
            "yt-dlp is not installed. Install it with: pip install yt-dlp",
            error_type="dependency_error",
            code="missing_ytdlp",
        ) from None

    dest_template = str(Path(dest_dir) / "%(id)s.%(ext)s")
    ydl_opts = {
        "outtmpl": dest_template,
        "format": "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
        "quiet": True,
        "no_warnings": True,
        "merge_output_format": "mp4",
        "socket_timeout": 120,
        "max_filesize": 2 * (1 << 30),  # 2 GiB limit
        "proxy": "",
    }

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=False)
        _validate_ytdlp_info_urls(info)
        info = ydl.extract_info(url, download=True)
        _validate_ytdlp_info_urls(info)
        filename = ydl.prepare_filename(info)
        # yt-dlp may have merged to .mp4 even if template said otherwise
        if not Path(filename).exists():
            # Try .mp4 extension
            filename = str(Path(filename).with_suffix(".mp4"))
        return filename


def _resolve_video_source(video: str) -> tuple[str, str | None, str | None]:
    """Resolve *video* to a local file path, downloading if necessary.

    Returns:
        (local_path, temp_dir_to_cleanup, source_url)
        temp_dir_to_cleanup is None for local files.
    """
    if not _is_url(video):
        return video, None, None

    if not _is_safe_url(video):
        raise MCPVideoError(
            f"URL blocked (SSRF protection): {video}", error_type="validation_error", code="ssrf_blocked"
        )

    source_url = video
    host = _url_host(video)
    is_platform = host in _PLATFORM_HOSTS

    # Decide strategy — defer temp dir creation until download is imminent
    if is_platform:
        # Must use yt-dlp
        tmp = tempfile.mkdtemp(prefix="mcp_video_url_")
        try:
            local = _download_with_ytdlp(video, tmp)
        except MCPVideoError:
            shutil.rmtree(tmp, ignore_errors=True)
            raise  # re-raise "yt-dlp not installed" cleanly
        except Exception as exc:
            shutil.rmtree(tmp, ignore_errors=True)
            raise ProcessingError(str(video), 1, f"Failed to download {video}: {exc}") from exc
    else:
        # Try yt-dlp first (handles edge cases like redirect-to-stream),
        # fall back to direct urllib download.
        try:
            tmp = tempfile.mkdtemp(prefix="mcp_video_url_")
            local = _download_with_ytdlp(video, tmp)
        except MCPVideoError:
            # yt-dlp not installed — fall back to urllib for direct URLs
            shutil.rmtree(tmp, ignore_errors=True)
            url_path = video.split("?")[0]  # strip query string for ext detection
            ext = Path(url_path).suffix.lower()
            if ext not in _DIRECT_VIDEO_EXTENSIONS:
                raise MCPVideoError(
                    f"Cannot download '{video}': not a recognised direct video URL and "
                    "yt-dlp is not installed. Install yt-dlp with: pip install yt-dlp",
                    error_type="dependency_error",
                    code="missing_ytdlp",
                ) from None
            tmp = tempfile.mkdtemp(prefix="mcp_video_url_")
            try:
                local = _download_direct_url(video, tmp)
            except Exception as exc:
                shutil.rmtree(tmp, ignore_errors=True)
                raise ProcessingError(str(video), 1, f"Failed to download {video}: {exc}") from exc
        except Exception as exc:
            # yt-dlp is installed but failed — try urllib as last resort
            shutil.rmtree(tmp, ignore_errors=True)
            url_path = video.split("?")[0]
            ext = Path(url_path).suffix.lower()
            if ext in _DIRECT_VIDEO_EXTENSIONS:
                tmp = tempfile.mkdtemp(prefix="mcp_video_url_")
                try:
                    local = _download_direct_url(video, tmp)
                except Exception as dl_exc:
                    shutil.rmtree(tmp, ignore_errors=True)
                    raise ProcessingError(
                        str(video), 1, f"Download failed (yt-dlp: {exc}; urllib: {dl_exc})"
                    ) from dl_exc
            else:
                raise ProcessingError(str(video), 1, f"Failed to download {video}: {exc}") from exc

    return local, tmp, source_url
