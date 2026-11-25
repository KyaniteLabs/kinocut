"""AI-powered video processing using machine learning models.

Optional dependencies:
    - openai-whisper: For speech-to-text transcription
    - imagehash: For AI-enhanced scene detection
    - Pillow: For image processing in scene detection
"""

from __future__ import annotations

import http.client
import ipaddress as _ipaddress
import logging
import re
import shutil
import socket as _socket
import tempfile
import urllib.parse
import urllib.request
from pathlib import Path

from ..errors import MCPVideoError, ProcessingError
from ..offline import is_offline_mode
from ..validation_errors import exception_kind, rejected_value

logger = logging.getLogger(__name__)

_CGNAT_NET = _ipaddress.ip_network("100.64.0.0/10")
_NAT64_WELL_KNOWN_NET = _ipaddress.ip_network("64:ff9b::/96")
_NAT64_LOCAL_NET = _ipaddress.ip_network("64:ff9b:1::/48")


def _safe_resolved_addrs(host: str, port: int) -> list[tuple[int, tuple]]:
    """Resolve *host* to validated (family, sockaddr) pairs, filtering blocked IP ranges.

    Returns only addresses that are globally routable (not private, CGNAT,
    loopback, link-local, multicast, unspecified, reserved, or NAT64).
    Raises MCPVideoError if every resolved address is blocked.
    """
    addrinfos = _socket.getaddrinfo(host, port, proto=_socket.IPPROTO_TCP)
    safe: list[tuple[int, tuple]] = []
    for family, _type, _proto, _canon, sockaddr in addrinfos:
        ip_str = sockaddr[0]
        try:
            if _is_blocked_ip(ip_str):
                continue
        except ValueError:
            continue
        safe.append((family, sockaddr))
    if not safe:
        raise MCPVideoError(
            f"URL blocked (SSRF protection): {host} resolves only to blocked addresses",
            error_type="validation_error",
            code="ssrf_blocked",
        )
    return safe


def _create_pinned_socket(family: int, sockaddr: tuple, timeout) -> _socket.socket:
    """Create a TCP socket connected to a pre-validated address."""
    sock = _socket.socket(family, _socket.SOCK_STREAM)
    sock.settimeout(timeout)
    sock.connect(sockaddr)
    return sock


class _PinnedHTTPConnection(http.client.HTTPConnection):
    """HTTPConnection that connects only to a pre-validated IP address.

    The hostname is resolved and validated in :meth:`_pin_address` before any
    network I/O, eliminating the TOCTOU window where DNS could be rebound to a
    private address between validation and connection.
    """

    _pinned_family: int
    _pinned_sockaddr: tuple

    def __init__(self, host: str, **kwargs: object) -> None:
        hostname, port = _split_host_port(host, self.default_port)
        addrs = _safe_resolved_addrs(hostname, port)
        self._pinned_family, self._pinned_sockaddr = addrs[0]
        super().__init__(host, **kwargs)

    def connect(self) -> None:
        self.sock = _create_pinned_socket(self._pinned_family, self._pinned_sockaddr, self.timeout)


class _PinnedHTTPSConnection(http.client.HTTPSConnection):
    """HTTPSConnection that connects only to a pre-validated IP address.

    SNI and certificate verification use the original hostname, not the pinned
    IP, so TLS identity checks remain correct.
    """

    _pinned_family: int
    _pinned_sockaddr: tuple

    def __init__(self, host: str, **kwargs: object) -> None:
        hostname, port = _split_host_port(host, self.default_port)
        addrs = _safe_resolved_addrs(hostname, port)
        self._pinned_family, self._pinned_sockaddr = addrs[0]
        super().__init__(host, **kwargs)

    def connect(self) -> None:
        self.sock = _create_pinned_socket(self._pinned_family, self._pinned_sockaddr, self.timeout)
        self.sock = self._context.wrap_socket(self.sock, server_hostname=self.host)


def _split_host_port(host_str: str, default_port: int) -> tuple[str, int]:
    """Split a 'host:port' or 'host' string into (hostname, port)."""
    if host_str.startswith("["):
        bracket_end = host_str.index("]")
        hostname = host_str[1:bracket_end]
        rest = host_str[bracket_end + 1 :]
        port = int(rest[1:]) if rest.startswith(":") else default_port
        return hostname, port
    parts = host_str.rsplit(":", 1)
    if len(parts) == 2 and parts[1].isdigit():
        return parts[0], int(parts[1])
    return host_str, default_port


class _PinnedHTTPHandler(urllib.request.HTTPHandler):
    """urllib HTTPHandler subclass that connects exclusively via :class:`_PinnedHTTPConnection`."""

    def http_open(self, req):
        return self.do_open(_PinnedHTTPConnection, req)


class _PinnedHTTPSHandler(urllib.request.HTTPSHandler):
    """urllib HTTPSHandler subclass that connects exclusively via :class:`_PinnedHTTPSConnection`."""

    def https_open(self, req):
        return self.do_open(_PinnedHTTPSConnection, req)


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Refuse all HTTP redirects to prevent redirect-based SSRF."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise MCPVideoError(
            "URL blocked (SSRF protection): HTTP redirects are not permitted",
            error_type="validation_error",
            code="ssrf_blocked",
        )


class _SafeRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Reject HTTP redirects to private/blocked addresses (SSRF protection)."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not _is_safe_url(newurl):
            raise MCPVideoError(
                f"URL blocked (SSRF protection): redirect target {rejected_value(newurl)}",
                error_type="validation_error",
                code="ssrf_blocked",
            )
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _build_pinned_opener() -> urllib.request.OpenerDirector:
    """Construct a strict opener with ONLY pinned HTTP/HTTPS, no redirects, and no proxies."""
    handlers = (
        _PinnedHTTPHandler(),
        _PinnedHTTPSHandler(),
        _NoRedirect(),
        urllib.request.ProxyHandler({}),
        urllib.request.HTTPDefaultErrorHandler(),
        urllib.request.HTTPErrorProcessor(),
    )
    opener = urllib.request.build_opener(*handlers)
    if not isinstance(opener, urllib.request.OpenerDirector):
        # Preserve test monkeypatch hooks on urllib.request.build_opener.
        return opener
    # Rebuild strictly without CPython's default FTPHandler/FileHandler/DataHandler/UnknownHandler.
    strict = urllib.request.OpenerDirector()
    for handler in handlers:
        strict.add_handler(handler)
    return strict


def _is_blocked_ip(ip_str: str) -> bool:
    clean = ip_str.split("%", 1)[0]
    addr = _ipaddress.ip_address(clean)
    if isinstance(addr, _ipaddress.IPv6Address):
        if addr.ipv4_mapped is not None:
            return _is_blocked_ip(str(addr.ipv4_mapped))
        if addr.sixtofour is not None and _is_blocked_ip(str(addr.sixtofour)):
            return True
        if addr.teredo is not None and (_is_blocked_ip(str(addr.teredo[0])) or _is_blocked_ip(str(addr.teredo[1]))):
            return True
        if addr in _NAT64_WELL_KNOWN_NET or addr in _NAT64_LOCAL_NET:
            return True
    elif isinstance(addr, _ipaddress.IPv4Address) and addr in _CGNAT_NET:
        return True
    return (
        not addr.is_global
        or addr.is_private
        or addr.is_loopback
        or addr.is_link_local
        or addr.is_reserved
        or addr.is_multicast
        or addr.is_unspecified
    )


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
    """Reject non-http(s) URLs or URLs resolving to non-global/private/loopback/link-local IPs."""
    if not isinstance(url, str) or not url or any(ch.isspace() or ord(ch) < 32 for ch in url):
        return False
    try:
        parsed = urllib.parse.urlsplit(url)
        if parsed.scheme.lower() not in {"http", "https"}:
            return False
        hostname = parsed.hostname
        if not hostname:
            return False
        port = parsed.port or (443 if parsed.scheme.lower() == "https" else 80)
        addrinfos = _socket.getaddrinfo(hostname, port, proto=_socket.IPPROTO_TCP)
        if not addrinfos:
            return False
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
    """Extract normalized host[:port] from a URL (stripping userinfo, path, query, fragment)."""
    try:
        parsed = urllib.parse.urlsplit(url if "://" in url else f"https://{url}")
        return parsed.netloc.rsplit("@", 1)[-1].lower()
    except ValueError:
        return ""


def _download_direct_url(url: str, dest_dir: str) -> str:
    """Download a direct video URL to *dest_dir* using urllib. Returns local path."""
    if not _is_safe_url(url):
        raise MCPVideoError(
            f"URL blocked (SSRF protection): {rejected_value(url)}", error_type="validation_error", code="ssrf_blocked"
        )

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
    opener = _build_pinned_opener()
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
            if key in {"url", "webpage_url", "original_url", "manifest_url", "fragment_base_url"} and _is_http_url(
                item
            ):
                yield item
            elif key in {
                "formats",
                "requested_formats",
                "requested_downloads",
                "entries",
                "fragments",
                "subtitles",
                "automatic_captions",
                "thumbnails",
            }:
                yield from _iter_ytdlp_info_urls(item)
            elif (
                isinstance(item, dict)
                and key not in {"http_headers"}
                and all(isinstance(v, list) for v in item.values())
            ):
                # Inspect nested language-keyed subtitle/caption maps too.
                yield from _iter_ytdlp_info_urls(list(item.values()))
    elif isinstance(value, list | tuple):
        for item in value:
            yield from _iter_ytdlp_info_urls(item)


def _validate_ytdlp_info_urls(info: object) -> None:
    """Reject yt-dlp results that resolve media URLs to blocked networks."""
    for media_url in _iter_ytdlp_info_urls(info):
        if not _is_safe_url(media_url):
            raise MCPVideoError(
                f"URL blocked (SSRF protection): yt-dlp resolved media URL {rejected_value(media_url)}",
                error_type="validation_error",
                code="ssrf_blocked",
            )


def _download_with_ytdlp(url: str, dest_dir: str) -> str:
    """Download a platform video URL using yt-dlp. Returns local path."""
    if not _is_safe_url(url):
        raise MCPVideoError(
            f"URL blocked (SSRF protection): {rejected_value(url)}",
            error_type="validation_error",
            code="ssrf_blocked",
        )
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


def _direct_download_extension(video: str) -> str:
    """The file extension of a direct video URL, query string and fragment stripped."""
    url_path = urllib.parse.urlsplit(video).path
    return Path(url_path).suffix.lower()


def _download_with_urllib(video: str) -> tuple[str, str]:
    """Download a direct URL with urllib, returning (local_path, temp_dir).

    The temporary directory is returned so the caller can remove it when
    the download fails.
    """
    tmp = tempfile.mkdtemp(prefix="mcp_video_url_")
    try:
        local = _download_direct_url(video, tmp)
    except MCPVideoError:
        shutil.rmtree(tmp, ignore_errors=True)
        raise
    except Exception as exc:
        shutil.rmtree(tmp, ignore_errors=True)
        raise ProcessingError(
            str(video), 1, "", reason=f"Failed to download {rejected_value(video)}: {exception_kind(exc)}"
        ) from exc
    return local, tmp


def _download_platform_video(video: str) -> tuple[str, str]:
    tmp = tempfile.mkdtemp(prefix="mcp_video_url_")
    try:
        local = _download_with_ytdlp(video, tmp)
    except MCPVideoError:
        shutil.rmtree(tmp, ignore_errors=True)
        raise  # re-raise "yt-dlp not installed" cleanly
    except Exception as exc:
        shutil.rmtree(tmp, ignore_errors=True)
        raise ProcessingError(
            str(video), 1, "", reason=f"Failed to download {rejected_value(video)}: {exception_kind(exc)}"
        ) from exc
    return local, tmp


def _download_generic_video(video: str) -> tuple[str, str]:
    # Try yt-dlp first (handles edge cases like redirect-to-stream),
    # fall back to direct urllib download.
    tmp = tempfile.mkdtemp(prefix="mcp_video_url_")
    try:
        local = _download_with_ytdlp(video, tmp)
        return local, tmp
    except MCPVideoError as exc:
        shutil.rmtree(tmp, ignore_errors=True)
        # Only fall back to urllib when yt-dlp is missing; NEVER swallow SSRF or policy errors.
        if exc.code != "missing_ytdlp":
            raise
        ext = _direct_download_extension(video)
        if ext not in _DIRECT_VIDEO_EXTENSIONS:
            raise MCPVideoError(
                f"Cannot download '{rejected_value(video)}': not a recognised direct video URL and "
                "yt-dlp is not installed. Install yt-dlp with: pip install yt-dlp",
                error_type="dependency_error",
                code="missing_ytdlp",
            ) from None
        return _download_with_urllib(video)
    except Exception as exc:
        # yt-dlp is installed but failed — try urllib as last resort
        shutil.rmtree(tmp, ignore_errors=True)
        ext = _direct_download_extension(video)
        if ext in _DIRECT_VIDEO_EXTENSIONS:
            fallback_tmp = tempfile.mkdtemp(prefix="mcp_video_url_")
            try:
                local = _download_direct_url(video, fallback_tmp)
            except MCPVideoError:
                shutil.rmtree(fallback_tmp, ignore_errors=True)
                raise
            except Exception as dl_exc:
                shutil.rmtree(fallback_tmp, ignore_errors=True)
                raise ProcessingError(
                    str(video),
                    1,
                    "",
                    reason=f"Download failed (yt-dlp: {exception_kind(exc)}; urllib: {exception_kind(dl_exc)})",
                ) from dl_exc
            return local, fallback_tmp
        raise ProcessingError(
            str(video), 1, "", reason=f"Failed to download {rejected_value(video)}: {exception_kind(exc)}"
        ) from exc


def _resolve_video_source(video: str) -> tuple[str, str | None, str | None]:
    """Resolve *video* to a local file path, downloading if necessary.

    Returns:
        (local_path, temp_dir_to_cleanup, source_url)
        temp_dir_to_cleanup is None for local files.
    """
    if not _is_url(video):
        return video, None, None
    if is_offline_mode():
        raise MCPVideoError(
            "Video URL import is disabled offline. Use a local video file.",
            error_type="offline_error",
            code="offline_network_blocked",
        )

    if not _is_safe_url(video):
        raise MCPVideoError(
            f"URL blocked (SSRF protection): {rejected_value(video)}",
            error_type="validation_error",
            code="ssrf_blocked",
        )

    host_name = (urllib.parse.urlsplit(video).hostname or "").lower()
    if host_name in _PLATFORM_HOSTS:
        local, tmp = _download_platform_video(video)
    else:
        local, tmp = _download_generic_video(video)
    return local, tmp, video
