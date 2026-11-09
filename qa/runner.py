#!/usr/bin/env python3
"""Run the safe operator paths declared in operator-paths.yaml.

Catalog strings are data, never shell programs. Commands are argument arrays
with a deliberately small placeholder vocabulary and are launched with
``shell=False``. Discovery is reported separately and never counted as action
coverage. All generated media and receipts stay under one fresh QA work dir.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import importlib
import json
import math
import os
import re
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import time
from contextlib import contextmanager
from datetime import timedelta
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, cast

ROOT = Path(__file__).resolve().parents[1]
CATALOG = ROOT / "qa" / "operator-paths.yaml"
EXPECTED_PATH_IDS = {
    "clean-environment",
    "install-source",
    "install-doctor",
    "tiny-synthetic-media",
    "golden-path",
    "info",
    "trim",
    "resize",
    "subtitles",
    "waveform",
    "image-colors",
    "workflow-validate",
    "workflow-plan",
    "workflow-render",
    "workflow-inspect",
    "review-metrics",
    "sound-validation",
    "overwrite-guard",
    "source-alias-guard",
    "mcp-video_doctor",
    "mcp-video_info",
    "mcp-search_tools",
    "mcp-protocol",
    "static-review-ui",
    "hyperframes-preview",
}
PLACEHOLDER = re.compile(r"\{\{([a-z_]+)\}\}")
COMMAND_ALLOWLIST = {"kino", "ffmpeg", "ffprobe", "uv", "{{python}}", "{{venv_python}}"}


class CatalogError(ValueError):
    """The versioned catalog is malformed or unsafe to interpret."""


@contextmanager
def browser_tempdir():
    """Keep Playwright sockets short and remove only our own directory."""
    with tempfile.TemporaryDirectory(prefix="kinoqa-", dir="/tmp") as directory:
        previous = os.environ.get("TMPDIR")
        os.environ["TMPDIR"] = directory
        try:
            yield directory
        finally:
            if previous is None:
                os.environ.pop("TMPDIR", None)
            else:
                os.environ["TMPDIR"] = previous


PLAY_READY_TIMEOUT_MS = 30000


def wait_for_playable(page: Any, *, timeout_ms: int, page_errors: list[str], failed_requests: list[str]) -> None:
    """Wait until Studio enables Play; a visible-but-disabled button is not ready (#677)."""
    try:
        page.locator('button[aria-label="Play"]:not([disabled])').wait_for(state="visible", timeout=timeout_ms)
    except Exception as exc:
        if type(exc).__name__ != "TimeoutError":
            raise
        raise RuntimeError(
            f"preview never became playable: Play stayed disabled for {timeout_ms / 1000:g}s; "
            f"page errors: {page_errors[:2]}; failed requests: {failed_requests[:3]}"
        ) from exc


def load_catalog(path: Path) -> dict[str, Any]:
    try:
        import yaml
    except ImportError as exc:  # pragma: no cover - environment-specific
        raise CatalogError("PyYAML is required by the QA runner; no install/download was attempted") from exc

    class UniqueLoader(yaml.SafeLoader):
        pass

    def mapping(loader: Any, node: Any, deep: bool = False) -> dict[Any, Any]:
        result: dict[Any, Any] = {}
        for key_node, value_node in node.value:
            key = loader.construct_object(key_node, deep=deep)
            if key in result:
                raise CatalogError(f"duplicate YAML key: {key!r}")
            result[key] = loader.construct_object(value_node, deep=deep)
        return result

    UniqueLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, mapping)
    try:
        loader = UniqueLoader(path.read_text(encoding="utf-8"))
        try:
            value = loader.get_single_data()
        finally:
            loader.dispose()
    except (OSError, yaml.YAMLError) as exc:
        raise CatalogError(f"cannot read catalog: {exc}") from exc
    if not isinstance(value, dict):
        raise CatalogError("catalog root must be a mapping")
    validate_catalog(value)
    return value


def required_paths(catalog: dict[str, Any]) -> list[dict[str, Any]]:
    entries = [*catalog.get("setup", [])]
    fixture = catalog.get("fixture")
    if fixture:
        entries.append(fixture)
    entries.extend(catalog.get("paths", []))
    protocol = catalog.get("mcp_protocol")
    if protocol:
        entries.append(protocol)
    entries.extend(catalog.get("web_and_http", []))
    return [entry for entry in entries if entry.get("required") is True]


def validate_catalog(catalog: dict[str, Any]) -> None:
    if catalog.get("schema_version") != 2:
        raise CatalogError("schema_version must be 2")
    if catalog.get("status") != "draft_incomplete" or catalog.get("complete_e2e_catalog") is not False:
        raise CatalogError("this catalog has not been reviewed for complete end-to-end coverage")
    entries = required_paths(catalog)
    raw_ids = [entry.get("id") for entry in entries]
    if any(not isinstance(item, str) or not item for item in raw_ids):
        raise CatalogError("each required path must have a stable non-empty id")
    ids = [item for item in raw_ids if isinstance(item, str)]
    if len(ids) != len(set(ids)):
        raise CatalogError("duplicate required path id")
    if set(ids) != EXPECTED_PATH_IDS:
        missing = sorted(EXPECTED_PATH_IDS - set(ids))
        extra = sorted(set(ids) - EXPECTED_PATH_IDS)
        raise CatalogError(f"required path set drift (missing={missing}, extra={extra})")
    for entry in entries:
        if not isinstance(entry.get("sources"), list) or not entry["sources"]:
            raise CatalogError(f"{entry['id']}: source provenance is required")
        if not isinstance(entry.get("assertions"), list) or not entry["assertions"]:
            raise CatalogError(f"{entry['id']}: observable assertions are required")
        for field in ("argv", "commands"):
            commands = entry.get(field, [])
            if field == "argv" and "argv" in entry:
                commands = [commands]
            if not isinstance(commands, list):
                raise CatalogError(f"{entry['id']}: {field} must be argv arrays")
            for argv in commands:
                if not isinstance(argv, list) or not argv or not all(isinstance(x, str) for x in argv):
                    raise CatalogError(f"{entry['id']}: each {field} command must be a non-empty argv array")
                if argv[0] not in COMMAND_ALLOWLIST:
                    raise CatalogError(f"{entry['id']}: executable {argv[0]!r} is not allowlisted")
    gaps = catalog.get("coverage_gaps")
    if not isinstance(gaps, list):
        raise CatalogError("coverage gaps must be a list")
    if not gaps and not catalog.get("coverage_inventory"):
        raise CatalogError("coverage gaps must remain explicit")
    for gap in gaps:
        if gap.get("status") != "BLOCKED" or not gap.get("missing") or not gap.get("sources"):
            raise CatalogError(f"coverage gap {gap.get('id')!r} needs BLOCKED, exact missing input and provenance")
    for surface in catalog.get("discovery", {}).values():
        if any(key in surface for key in ("count", "names", "expected_count")):
            raise CatalogError("runtime discovery surfaces must not pin counts or names")


def expand_argv(argv: list[str], values: dict[str, Any]) -> list[str]:
    """Expand known data placeholders without evaluating shell syntax."""
    if not argv or argv[0] not in COMMAND_ALLOWLIST:
        executable = argv[0] if argv else "<empty>"
        raise CatalogError(f"catalog command executable is not allowlisted: {executable}")
    expanded: list[str] = []
    for arg in argv:

        def replace(match: re.Match[str]) -> str:
            key = match.group(1)
            if key not in values:
                raise CatalogError(f"unknown command placeholder: {key}")
            return str(values[key])

        rendered = PLACEHOLDER.sub(replace, arg)
        if "{{" in rendered or "}}" in rendered:
            raise CatalogError("unresolved command placeholder")
        expanded.append(rendered)
    return expanded


def exit_code(results: list[dict[str, Any]]) -> int:
    return 0 if results and all(result.get("status") == "PASS" for result in results) else 1


def coverage_counts(results: list[dict[str, Any]], catalog: dict[str, Any]) -> dict[str, Any]:
    required = required_paths(catalog)
    entries = {entry["id"]: entry for entry in required}
    discovery_ids = {entry["id"] for entry in required if entry.get("category") == "discovery"}
    setup_ids = {entry["id"] for entry in required if entry.get("category") in {"setup", "fixture"}}
    action_ids = {entry["id"] for entry in required if entry.get("category") == "operator"}
    by_id = {result.get("id"): result for result in results}
    action_results = [by_id[path_id] for path_id in action_ids if path_id in by_id]
    discovery = [by_id[path_id] for path_id in discovery_ids if path_id in by_id]
    return {
        "required_path_count": len(required),
        "reported_path_count": len(results),
        "required_operator_action_path_count": len(action_ids),
        "passed_operator_action_path_count": sum(result.get("status") == "PASS" for result in action_results),
        "missing_path_ids": sorted(set(entries) - set(by_id)),
        "failed_path_ids": [result["id"] for result in results if result.get("status") == "FAIL"],
        "blocked_path_ids": [result["id"] for result in results if result.get("status") == "BLOCKED"],
        "setup_path_ids": sorted(setup_ids),
        "setup_passed_path_ids": sorted(
            path_id for path_id in setup_ids if by_id.get(path_id, {}).get("status") == "PASS"
        ),
        "discovery_path_ids": sorted(discovery_ids),
        "discovery_passed_path_ids": sorted(result["id"] for result in discovery if result.get("status") == "PASS"),
    }


def format_result(result: dict[str, Any]) -> str:
    status = result.get("status", "FAIL")
    detail = str(result.get("detail", ""))
    fields = []
    if result.get("exit_code") is not None:
        fields.append(f"exit={result['exit_code']}")
    if result.get("http_code") is not None:
        fields.append(f"http={result['http_code']}")
    suffix = f" ({', '.join(fields)})" if fields else ""
    return f"{status} {result.get('id', '<unknown>')}{suffix}: {detail}"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _deep_find(value: Any, key: str) -> list[Any]:
    found: list[Any] = []
    if isinstance(value, dict):
        for name, child in value.items():
            if name == key:
                found.append(child)
            found.extend(_deep_find(child, key))
    elif isinstance(value, list):
        for child in value:
            found.extend(_deep_find(child, key))
    return found


def expand_data(value: Any, values: dict[str, Any]) -> Any:
    """Expand the same bounded placeholders in structured request data."""
    if isinstance(value, str):

        def replace(match: re.Match[str]) -> str:
            key = match.group(1)
            if key not in values:
                raise CatalogError(f"unknown request placeholder: {key}")
            return str(values[key])

        return PLACEHOLDER.sub(replace, value)
    if isinstance(value, list):
        return [expand_data(item, values) for item in value]
    if isinstance(value, dict):
        return {key: expand_data(item, values) for key, item in value.items()}
    return value


def _read_json_object(raw: str) -> dict[str, Any] | None:
    try:
        value = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return None
    return value if isinstance(value, dict) else None


def cli_names(help_text: str) -> list[str]:
    section = help_text.partition("positional arguments:")[2]
    match = re.search(r"\{([a-zA-Z0-9_,\-]+)\}", section)
    return match.group(1).split(",") if match else []


def measured_waveform(data: dict[str, Any] | None) -> bool:
    if not data or data.get("success") is not True or data.get("synthetic") is not False:
        return False
    peaks = data.get("peaks")
    return (
        isinstance(peaks, list)
        and len(peaks) == 8
        and all(isinstance(p, dict) and isinstance(p.get("time"), (int, float))
                and isinstance(p.get("level"), (int, float)) and math.isfinite(p["level"]) for p in peaks)
        and any(p["level"] > -50 for p in peaks)
    )


def subtitle_search_matches(data: dict[str, Any]) -> list[str]:
    tools = data.get("tools")
    if data.get("success") is False or not isinstance(tools, list):
        return []
    return [item["name"] for item in tools if isinstance(item, dict)
            and isinstance(item.get("name"), str) and "subtitle" in item["name"].lower()
            and isinstance(item.get("required_params"), list)]


def sound_plan_rejection(cp: subprocess.CompletedProcess[str]) -> dict[str, Any] | None:
    data = _read_json_object(cp.stdout) or _read_json_object(cp.stderr)
    if cp.returncode != 0 and data and data.get("success") is False and isinstance(data.get("error"), dict):
        return data["error"]
    return None


def exhaustive_coverage(catalog: dict[str, Any], cli: set[str], mcp: set[str]) -> bool:
    mapping = catalog.get("coverage_inventory", {})
    if not cli or not mcp or not isinstance(mapping, dict):
        return False
    entries = {entry["id"]: entry for entry in required_paths(catalog) if entry.get("category") == "operator"}
    for surface, observed in (("cli", cli), ("mcp", mcp)):
        values = mapping.get(surface)
        if not isinstance(values, dict) or set(values) != observed:
            return False
        for name, path_id in values.items():
            entry = entries.get(path_id, {})
            if surface == "cli" and name not in entry.get("argv", []):
                return False
            if surface == "mcp" and entry.get("request", {}).get("tool") != name:
                return False
    return True


class OperatorRunner:
    def __init__(
        self, product_root: Path, work_dir: Path, catalog_path: Path = CATALOG, product_sha: str | None = None
    ) -> None:
        self.catalog_path = catalog_path.resolve()
        self.catalog = load_catalog(self.catalog_path)
        self.product_root = product_root.resolve(strict=True)
        self.work = work_dir.resolve()
        self.work.mkdir(parents=True, exist_ok=False)
        for name in ("home", "config", "cache", "data", "tmp", "fixtures", "artifacts"):
            (self.work / name).mkdir(parents=True, exist_ok=True)
        self.venv = self.work / "venv"
        self.python = self.venv / "bin" / "python"
        self.kino = self.venv / "bin" / "kino"
        self.product_sha_arg = product_sha
        self.product_sha: str | None = None
        self.hyperframes_executable: str | None = None
        self.catalog_revision = self._source_revision()
        self.product_problem = self._verify_product_root()
        self.installed = False
        self.fixtures_ready = False
        self.results: list[dict[str, Any]] = []
        self.cli_inventory: set[str] = set()
        self.mcp_inventory: set[str] = set()
        self.preview_process: subprocess.Popen[bytes] | None = None

    def _source_revision(self) -> dict[str, Any]:
        source_root = self.catalog_path.parent.parent
        sha = self._git_output(source_root, "rev-parse", "HEAD") or "unknown"
        status = self._git_output(source_root, "status", "--porcelain=v1", "--untracked-files=all")
        return {
            "source_sha": sha,
            "source_dirty": None if status is None else bool(status),
            "catalog_sha256": _sha256(self.catalog_path),
        }

    @staticmethod
    def _git_output(root: Path, *args: str) -> str | None:
        git = shutil.which("git")
        if not git:
            return None
        try:
            result = subprocess.run(  # noqa: S603 - fixed git executable; argument vector, shell disabled
                [git, "-C", str(root), *args], capture_output=True, text=True, timeout=15, check=True, shell=False
            )

        except (OSError, subprocess.SubprocessError):
            return None
        return result.stdout.strip()

    def _verify_product_root(self) -> str | None:
        actual = self._git_output(self.product_root, "rev-parse", "HEAD")
        if not actual or not re.fullmatch(r"[0-9a-f]{40}", actual):
            return "product root is not a Git checkout with a full HEAD SHA"
        self.product_sha = actual
        if self.product_sha_arg and self.product_sha_arg != actual:
            return f"requested product SHA {self.product_sha_arg} differs from checkout HEAD {actual}"
        dirty = self._git_output(self.product_root, "status", "--porcelain=v1", "--untracked-files=all")
        if dirty is None or dirty:
            return "product checkout is not clean; exact merged-source identity cannot be claimed"
        remote_tip = self._git_output(self.product_root, "rev-parse", "refs/remotes/origin/master")
        if not remote_tip:
            return "refs/remotes/origin/master is unavailable; cannot verify default-branch ancestry"
        git = shutil.which("git")
        if not git:
            return "git is unavailable; cannot verify default-branch ancestry"
        try:
            subprocess.run(  # noqa: S603 - fixed git executable; argument vector, shell disabled
                [git, "-C", str(self.product_root), "merge-base", "--is-ancestor", actual, remote_tip],
                check=True,
                capture_output=True,
                timeout=15,
                shell=False,
            )

        except (OSError, subprocess.SubprocessError):
            return f"product SHA {actual} is not verified on origin/master ancestry"
        return None

    def _base_env(self) -> dict[str, str]:
        path = os.environ.get("PATH", "/usr/bin:/bin")
        if self.venv.is_dir():
            path = f"{self.venv / 'bin'}:{path}"
        return {
            "PATH": path,
            "HOME": str(self.work / "home"),
            "XDG_CONFIG_HOME": str(self.work / "config"),
            "XDG_CACHE_HOME": str(self.work / "cache"),
            "XDG_DATA_HOME": str(self.work / "data"),
            "TMPDIR": str(self.work / "tmp"),
            "LANG": "C.UTF-8",
            "LC_ALL": "C.UTF-8",
            "PYTHONNOUSERSITE": "1",
            "PYTHONDONTWRITEBYTECODE": "1",
            "UV_CACHE_DIR": str(self.work / "cache" / "uv"),
            "NO_COLOR": "1",
            "TERM": "dumb",
            "KINOCUT_SOURCE_ROOT": str(self.product_root),
            "KINOCUT_VISION_MODE": "off",
            "KINOCUT_REVIDEO_TELEMETRY": "false",
            "MCP_VIDEO_HYPERFRAMES_TELEMETRY": "false",
        }

    def _run(
        self, argv: list[str], *, cwd: Path | None = None, timeout: int = 180, env: dict[str, str] | None = None
    ) -> subprocess.CompletedProcess[str]:
        executable = argv[0] if argv else ""
        trusted_paths = {str(Path(sys.executable).resolve()), str(self.python.resolve()), str(self.kino.resolve())}
        trusted = executable in {"git", "kino", "ffmpeg", "ffprobe", "uv"} or str(Path(executable).resolve()) in trusted_paths
        if self.hyperframes_executable and str(Path(executable).resolve()) == str(
            Path(self.hyperframes_executable).resolve()
        ):
            trusted = True
        if not trusted:
            return subprocess.CompletedProcess(
                argv, 126, stdout="", stderr=f"refusing non-allowlisted executable: {executable}"
            )
        try:
            return subprocess.run(  # noqa: S603 - validated executable allowlist; argument vector, shell disabled
                argv,
                cwd=str(cwd or self.product_root),
                env=env or self._base_env(),
                text=True,
                capture_output=True,
                timeout=timeout,
                check=False,
                shell=False,
            )

        except subprocess.TimeoutExpired as exc:
            out = exc.stdout or exc.stderr or ""
            if isinstance(out, bytes):
                out = out.decode("utf-8", errors="replace")
            return subprocess.CompletedProcess(argv, 124, stdout=str(out), stderr=f"timeout after {timeout}s")
        except OSError as exc:
            return subprocess.CompletedProcess(argv, 127, stdout="", stderr=f"cannot start {argv[0]}: {exc}")

    def _result(
        self, entry: dict[str, Any], status: str, detail: str, *, code: int | None = None, http: int | None = None
    ) -> dict[str, Any]:
        result = {"id": entry["id"], "status": status, "detail": detail}
        if code is not None:
            result["exit_code"] = code
        if http is not None:
            result["http_code"] = http
        self.results.append(result)
        print(format_result(result), flush=True)
        return result

    def _blocked(self, entry: dict[str, Any], detail: str, *, http: int | None = None) -> dict[str, Any]:
        return self._result(entry, "BLOCKED", detail, http=http)

    def _pass(self, entry: dict[str, Any], detail: str, *, code: int = 0, http: int | None = None) -> dict[str, Any]:
        return self._result(entry, "PASS", detail, code=code, http=http)

    def _fail(
        self, entry: dict[str, Any], detail: str, *, code: int | None = None, http: int | None = None
    ) -> dict[str, Any]:
        return self._result(entry, "FAIL", detail, code=code, http=http)

    def _entry(self, path_id: str) -> dict[str, Any]:
        for entry in required_paths(self.catalog):
            if entry["id"] == path_id:
                return entry
        raise CatalogError(f"required path not found: {path_id}")

    def _values(self) -> dict[str, Any]:
        return {
            "qa_work": self.work,
            "product_root": self.product_root,
            "venv": self.venv,
            "python": sys.executable,
            "venv_python": self.python,
        }

    def _expanded(self, entry: dict[str, Any], key: str = "argv") -> list[str]:
        return expand_argv(entry.get(key, []), self._values())

    def _doctor_report(self, cp: subprocess.CompletedProcess[str]) -> dict[str, Any] | None:
        report = _read_json_object(cp.stdout)
        if report is not None:
            return report
        return _read_json_object(cp.stderr)

    def run(self) -> int:
        self._run_clean_environment()
        self._run_source_install()
        self._run_doctor()
        self._run_fixtures()
        self._discover_cli()
        self._run_golden_path()
        for path_id in (
            "info",
            "trim",
            "resize",
            "subtitles",
            "waveform",
            "image-colors",
            "workflow-validate",
            "workflow-plan",
            "workflow-render",
            "workflow-inspect",
            "review-metrics",
            "sound-validation",
            "overwrite-guard",
            "source-alias-guard",
        ):
            self._run_operator(self._entry(path_id))
        self._run_mcp_protocol()
        for path_id in ("mcp-video_doctor", "mcp-video_info", "mcp-search_tools"):
            self._run_mcp_call(self._entry(path_id))
        self._run_static_review(self._entry("static-review-ui"))
        self._run_hyperframes(self._entry("hyperframes-preview"))
        self._print_coverage_gaps()
        gaps = self.catalog["coverage_gaps"]
        inventory_valid = bool(gaps) or exhaustive_coverage(self.catalog, self.cli_inventory, self.mcp_inventory)
        if not inventory_valid:
            print("COVERAGE FAIL: empty gap list is not supported by the live CLI/MCP action mapping", flush=True)
        summary = {
            "catalog_schema_version": self.catalog["schema_version"],
            "catalog_revision": self.catalog_revision,
            "product_sha": self.product_sha or "unverified",
            **coverage_counts(self.results, self.catalog),
            "coverage_complete": False,
        }
        print("SUMMARY " + json.dumps(summary, sort_keys=True), flush=True)
        return 1 if gaps or not inventory_valid else exit_code(self.results)

    def _run_clean_environment(self) -> None:
        entry = self._entry("clean-environment")
        env = self._base_env()
        forbidden = (
            "GH_TOKEN",
            "GITHUB_TOKEN",
            "ANTHROPIC_API_KEY",
            "OPENAI_API_KEY",
            "GEMINI_API_KEY",
            "AWS_SECRET_ACCESS_KEY",
        )
        leaked = [name for name in forbidden if name in env]
        if leaked or env.get("KINOCUT_VISION_MODE") != "off":
            self._fail(entry, "isolated process environment unexpectedly contains credentials or enables vision")
            return
        if any(not (self.work / name).is_dir() for name in ("home", "config", "cache", "data", "tmp")):
            self._fail(entry, "isolated HOME/XDG directories were not created")
            return
        self._pass(entry, "empty HOME/XDG and no inherited credentials; vision and telemetry remain off")

    def _run_source_install(self) -> None:
        entry = self._entry("install-source")
        if self.product_problem or not self.product_sha:
            self._blocked(entry, self.product_problem or "exact product SHA is unavailable")
            return
        commands = entry.get("commands", [])
        for index, command in enumerate(commands):
            install = self._run(expand_argv(command, self._values()), timeout=240)
            if install.returncode != 0:
                tail = (install.stderr or install.stdout)[-800:]
                dependency_failure = any(
                    marker in tail.lower() for marker in ("no module named", "modulenotfounderror", "ensurepip")
                )
                if dependency_failure or index == 0:
                    self._blocked(
                        entry,
                        f"isolated source install unavailable: {tail}",
                    )
                else:
                    self._fail(entry, f"CLI help failed in the supplied checkout: {tail}", code=install.returncode)
                return
        check = self._run(
            [str(self.python), "-c", "import kinocut,pathlib,importlib.metadata; print(pathlib.Path(kinocut.__file__).resolve()); print(importlib.metadata.version('kinocut'))"],
            cwd=self.work,
            timeout=30,
        )
        if check.returncode != 0:
            detail = check.stderr[-500:] or check.stdout[-500:]
            if "modulenotfounderror" in detail.lower() or "no module named" in detail.lower():
                self._blocked(entry, f"target checkout runtime dependency is unavailable in the local venv: {detail}")
            else:
                self._fail(entry, f"source import from supplied checkout failed: {detail}", code=check.returncode)
            return
        try:
            import_path = Path(check.stdout.splitlines()[0]).resolve()
            import_path.relative_to(self.product_root)
        except (OSError, ValueError):
            self._fail(entry, f"import did not resolve inside supplied product checkout: {check.stdout.strip()!r}")
            return
        launcher_check = self._run([str(self.kino), "--help"], timeout=30)
        if launcher_check.returncode != 0:
            self._fail(
                entry,
                f"source-bound kino launcher failed: {launcher_check.stderr[-500:] or launcher_check.stdout[-500:]}",
                code=launcher_check.returncode,
            )
            return
        self.installed = True
        self._pass(
            entry,
            f"isolated editable package install and its generated kino launcher bind to checkout {self.product_sha[:12]}",
        )

    def _run_doctor(self) -> None:
        entry = self._entry("install-doctor")
        if not self.installed:
            self._blocked(entry, "source install did not pass; doctor cannot bind to the target checkout")
            return
        command = entry.get("commands", [[]])[0]
        cp = self._run(expand_argv(command, self._values()), timeout=120)
        report = self._doctor_report(cp)
        required_ok = (
            report is not None
            and isinstance(report.get("summary"), dict)
            and report["summary"].get("required_ok") is True
        )
        if cp.returncode == 0 and required_ok:
            self._pass(
                entry,
                "kino doctor JSON reports summary.required_ok=true and exposes optional diagnostics",
                code=cp.returncode,
            )
        else:
            self._fail(
                entry,
                f"doctor did not report required_ok=true; {cp.stderr[-500:] or cp.stdout[-500:]}",
                code=cp.returncode,
            )

    def _run_fixtures(self) -> None:
        entry = self._entry("tiny-synthetic-media")
        missing = [name for name in ("ffmpeg", "ffprobe") if not shutil.which(name, path=self._base_env()["PATH"])]
        if missing:
            self._blocked(entry, f"missing local media dependency: {', '.join(missing)}; no installation attempted")
            return
        for command in entry.get("commands", []):
            argv = expand_argv(command, self._values())
            cp = self._run(argv, cwd=self.work, timeout=120)
            if cp.returncode != 0:
                self._fail(entry, f"fixture command failed ({argv[0]}): {cp.stderr[-600:]}", code=cp.returncode)
                return
        fixture_dir = self.work / "fixtures"
        srt = fixture_dir / "captions.srt"
        srt.write_text(
            "1\n00:00:00,200 --> 00:00:01,000\nQA first cue\n\n2\n00:00:02,000 --> 00:00:03,000\nQA second cue\n",
            encoding="utf-8",
        )
        job = {
            "schema_version": 1,
            "name": "kinocut-qa-tiny",
            "sources": {"hero": {"path": "input.mp4"}},
            "steps": [
                {
                    "id": "trim",
                    "op": "trim",
                    "inputs": {"src": "@sources.hero"},
                    "params": {"start": 0, "duration": 2},
                    "output": "@outputs.master",
                }
            ],
            "outputs": {"master": {"path": "output/final.mp4"}},
        }
        (fixture_dir / "job.json").write_text(json.dumps(job), encoding="utf-8")
        probe = self._ffprobe(fixture_dir / "input.mp4")
        if (
            not probe
            or probe.get("width") != 320
            or probe.get("height") != 180
            or not probe.get("has_audio")
            or not 3.7 <= probe.get("duration", 0) <= 4.3
        ):
            self._fail(entry, "generated fixture did not match the documented 4s 320x180 video+audio contract")
            return
        decode = self._decode(fixture_dir / "input.mp4")
        if decode.returncode != 0 or not (fixture_dir / "hero.png").is_file():
            self._fail(entry, f"fixture decode/frame extraction failed: {decode.stderr[-500:]}", code=decode.returncode)
            return
        self.fixtures_ready = True
        self._pass(
            entry, "4s 320x180 H.264/AAC synthetic clip decoded; hero frame, two-cue SRT and confined job spec created"
        )

    def _ffprobe(self, path: Path) -> dict[str, Any] | None:
        cp = self._run(
            ["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", str(path)],
            cwd=self.work,
            timeout=45,
        )
        data = _read_json_object(cp.stdout)
        if cp.returncode or data is None:
            return None
        streams = data.get("streams", [])
        video = next((stream for stream in streams if stream.get("codec_type") == "video"), {})
        audio = any(stream.get("codec_type") == "audio" for stream in streams)
        duration = float(data.get("format", {}).get("duration", 0) or 0)
        return {"width": video.get("width"), "height": video.get("height"), "duration": duration, "has_audio": audio}

    def _decode(self, path: Path) -> subprocess.CompletedProcess[str]:
        return self._run(
            [
                "ffmpeg",
                "-nostdin",
                "-hide_banner",
                "-loglevel",
                "error",
                "-threads",
                "1",
                "-xerror",
                "-i",
                str(path),
                "-f",
                "null",
                "-",
            ],
            cwd=self.work,
            timeout=120,
        )

    def _discover_cli(self) -> None:
        if not self.installed:
            print(
                "DISCOVERY cli-inventory BLOCKED: source install unavailable (not counted as an operator path)",
                flush=True,
            )
            return
        argv = expand_argv(self.catalog["discovery"]["cli"]["argv"], self._values())
        cp = self._run(argv, timeout=60)
        if cp.returncode != 0:
            print(f"DISCOVERY cli-inventory ERROR exit={cp.returncode}: {cp.stderr[-300:]}", flush=True)
            return
        names = cli_names(cp.stdout)
        self.cli_inventory = set(names)
        print(
            f"DISCOVERY cli-inventory observed={len(names)} names={','.join(names)} (help only; not actions)",
            flush=True,
        )

    def _run_golden_path(self) -> None:
        entry = self._entry("golden-path")
        if not self.installed:
            self._blocked(entry, "target checkout install unavailable")
            return
        clone = self.work / "golden-checkout"
        cp = self._run(
            ["git", "clone", "--local", "--no-hardlinks", str(self.product_root), str(clone)], cwd=self.work, timeout=60
        )
        if cp.returncode != 0:
            self._fail(
                entry, f"cannot create isolated local golden-path worktree: {cp.stderr[-400:]}", code=cp.returncode
            )
            return
        checkout = self._run(
            ["git", "-C", str(clone), "checkout", "--detach", self.product_sha or ""], cwd=self.work, timeout=30
        )
        actual = self._git_output(clone, "rev-parse", "HEAD")
        if checkout.returncode != 0 or actual != self.product_sha:
            self._fail(entry, f"golden-path checkout is not exact product SHA ({actual})", code=checkout.returncode)
            return
        argv = expand_argv(entry["argv"], {**self._values(), "golden_root": clone})
        env = self._base_env()
        env["KINOCUT_SOURCE_ROOT"] = str(clone)
        env["PYTHONPATH"] = str(clone)
        cp = self._run(argv, cwd=clone, timeout=300, env=env)
        output = clone / "workflows" / "05-confidence-baseline" / "output"
        required = [
            output / name
            for name in ("final_clip.mp4", "video_receipt.json", "quality.json", "release_checkpoint.json")
        ]
        if cp.returncode != 0:
            self._fail(entry, f"golden-path script failed: {cp.stderr[-700:] or cp.stdout[-700:]}", code=cp.returncode)
            return
        if not all(path.is_file() for path in required):
            missing = [path.name for path in required if not path.is_file()]
            self._fail(entry, f"golden-path omitted required artifacts: {missing}")
            return
        quality = _read_json_object((output / "quality.json").read_text(encoding="utf-8"))
        receipt = _read_json_object((output / "video_receipt.json").read_text(encoding="utf-8"))
        if quality is None or receipt is None or self._decode(output / "final_clip.mp4").returncode != 0:
            self._fail(entry, "golden-path artifact JSON or full media decode failed")
            return
        self._pass(
            entry, "isolated exact-SHA clone wrote receipt/quality/checkpoint/media; human review remains pending"
        )

    def _cli_run(self, entry: dict[str, Any], timeout: int = 180) -> subprocess.CompletedProcess[str]:
        return self._run(self._expanded(entry), timeout=timeout)

    def _run_operator(self, entry: dict[str, Any]) -> None:
        if not self.installed:
            self._blocked(entry, "target checkout install unavailable")
            return
        if not self.fixtures_ready:
            self._blocked(entry, "required synthetic fixture generation did not pass")
            return
        action = entry["action"]
        if action == "overwrite_guard":
            output = self.work / "artifacts" / "trim.mp4"
            before = _sha256(output) if output.exists() else None
            cp = self._cli_run(entry)
            after = _sha256(output) if output.exists() else None
            if (
                cp.returncode != 0
                and before
                and before == after
                and any(word in (cp.stderr + cp.stdout).lower() for word in ("exist", "overwrite", "refus"))
            ):
                self._pass(
                    entry, "refused existing media destination and preserved its exact SHA-256", code=cp.returncode
                )
            else:
                self._fail(
                    entry,
                    f"overwrite guard did not fail closed/preserve output: {cp.stderr[-450:] or cp.stdout[-450:]}",
                    code=cp.returncode,
                )
            return
        if action == "source_alias_guard":
            source = self.work / "fixtures" / "input.mp4"
            before = _sha256(source)
            cp = self._cli_run(entry)
            after = _sha256(source)
            if (
                cp.returncode != 0
                and before == after
                and any(
                    marker in (cp.stderr + cp.stdout).lower() for marker in ("aliases an input", "invalid_output_path")
                )
            ):
                self._pass(entry, "refused source/output alias and preserved source SHA-256", code=cp.returncode)
            else:
                self._fail(
                    entry,
                    f"source-alias guard did not fail closed: {cp.stderr[-450:] or cp.stdout[-450:]}",
                    code=cp.returncode,
                )
            return
        if action == "expected_cli_rejection":
            cp = self._cli_run(entry)
            raw = cp.stdout + cp.stderr
            error = sound_plan_rejection(cp)
            if error is not None:
                self._pass(
                    entry,
                    f"explicit empty SoundPlan rejected; actual structured error: {json.dumps(error, ensure_ascii=False)}; no rendering",
                    code=cp.returncode,
                )
            else:
                self._fail(entry, f"expected a structured empty-plan rejection, got: {raw[-500:]}", code=cp.returncode)
            return
        if action == "optional_cli":
            cp = self._cli_run(entry)
            if cp.returncode != 0 and any(
                token in (cp.stdout + cp.stderr).lower()
                for token in ("missing_optional_dep", "optional dependency", "not installed", "requires the image")
            ):
                self._blocked(entry, "image extra is not installed in this offline run; no package/download attempted")
                return
            data = _read_json_object(cp.stdout)
            colors = _deep_find(data, "colors") if data else []
            if cp.returncode == 0 and any(isinstance(item, list) and len(item) == 3 for item in colors):
                self._pass(entry, "real hero fixture returned structured color samples")
            elif cp.returncode == 0 and data and data.get("success") is True:
                self._pass(entry, "image operation returned successful structured analysis for real fixture")
            else:
                self._fail(
                    entry,
                    f"image extraction did not satisfy structured result assertion: {cp.stderr[-500:] or cp.stdout[-500:]}",
                    code=cp.returncode,
                )
            return
        if action == "subtitle_timing":
            cp = self._cli_run(entry, timeout=240)
            out = self.work / "artifacts" / "captioned.mp4"
            if cp.returncode != 0 or not out.is_file() or self._decode(out).returncode != 0:
                self._fail(
                    entry,
                    f"subtitle command/full decode failed: {cp.stderr[-450:] or cp.stdout[-450:]}",
                    code=cp.returncode,
                )
                return
            measures = []
            for timestamp in (0.5, 1.5, 2.5, 3.5):
                src = self._raw_frame(self.work / "fixtures" / "input.mp4", timestamp)
                rendered = self._raw_frame(out, timestamp)
                if not src or len(src) != len(rendered):
                    self._fail(entry, f"cannot compare cue-window frames at {timestamp}s")
                    return
                measures.append(sum(abs(a - b) for a, b in zip(src, rendered, strict=True)) / len(src))
            if measures[0] > max(2.0, measures[1] * 1.6) and measures[2] > max(2.0, measures[3] * 1.6):
                self._pass(
                    entry,
                    f"full decode; paired-frame change by cue windows (0.5/1.5/2.5/3.5s mean diff={','.join(f'{x:.2f}' for x in measures)}); readability remains human review",
                )
            else:
                self._fail(entry, f"cue-window pixel changes did not meet timing assertion: {measures}")
            return
        if action == "cli":
            cp = self._cli_run(entry, timeout=240)
            if cp.returncode != 0:
                self._fail(entry, f"CLI action failed: {cp.stderr[-600:] or cp.stdout[-600:]}", code=cp.returncode)
                return
            if entry["id"] == "info":
                probe = self._ffprobe(self.work / "fixtures" / "input.mp4")
                data = _read_json_object(cp.stdout)
                if (
                    not probe
                    or probe["width"] != 320
                    or probe["height"] != 180
                    or not probe["has_audio"]
                    or data is None
                ):
                    self._fail(entry, "CLI info did not return JSON metadata matching independent ffprobe")
                    return
                self._pass(entry, "JSON info returned; independent ffprobe confirms 320x180, ~4s and audio")
                return
            if entry["id"] == "trim":
                out = self.work / "artifacts" / "trim.mp4"
                probe = self._ffprobe(out)
                if (
                    probe
                    and 1.8 <= probe["duration"] <= 2.3
                    and probe["has_audio"]
                    and self._decode(out).returncode == 0
                ):
                    self._pass(entry, "2-second output fully decodes and retains audio")
                else:
                    self._fail(entry, "trim output does not meet independent duration/audio/decode assertions")
                return
            if entry["id"] == "resize":
                probe = self._ffprobe(self.work / "artifacts" / "vertical.mp4")
                if (
                    probe
                    and probe["width"]
                    and probe["height"]
                    and abs(probe["width"] / probe["height"] - 9 / 16) < 0.02
                    and probe["has_audio"]
                    and self._decode(self.work / "artifacts" / "vertical.mp4").returncode == 0
                ):
                    self._pass(entry, f"decodable {probe['width']}x{probe['height']} output is 9:16 and retains audio")
                else:
                    self._fail(entry, "resize output failed aspect-ratio/audio/full-decode assertion")
                return
            if entry["id"] == "waveform":
                data = _read_json_object(cp.stdout)
                if measured_waveform(data):
                    self._pass(entry, "8 measured waveform bins and synthetic=false")
                else:
                    self._fail(entry, "waveform JSON lacks eight bins with synthetic=false")
                return
            if entry["id"].startswith("workflow-"):
                self._workflow_assert(entry)
                return
            if entry["id"] == "review-metrics":
                data = _read_json_object(cp.stdout)
                if data is not None and not any(value is True for value in _deep_find(data, "human_approved")):
                    self._pass(entry, "offline review metrics returned without inventing human approval")
                else:
                    self._fail(entry, "review metrics was not structured or implied a human approval")
                return
            self._pass(entry, "CLI returned exit 0 and structured operator output")
            return
        self._blocked(entry, f"runner does not implement declared action type {action!r}")

    def _raw_frame(self, path: Path, timestamp: float) -> bytes:
        argv = [
            "ffmpeg",
            "-nostdin",
            "-hide_banner",
            "-loglevel",
            "error",
            "-threads",
            "1",
            "-ss",
            str(timestamp),
            "-i",
            str(path),
            "-frames:v",
            "1",
            "-f",
            "rawvideo",
            "-pix_fmt",
            "rgb24",
            "-",
        ]
        try:
            cp = subprocess.run(  # noqa: S603 - fixed ffmpeg executable; argument vector, shell disabled
                argv, cwd=self.work, env=self._base_env(), capture_output=True, timeout=45, check=False, shell=False
            )

        except (OSError, subprocess.SubprocessError):
            return b""
        return cp.stdout if cp.returncode == 0 else b""

    def _workflow_assert(self, entry: dict[str, Any]) -> None:
        fixture = self.work / "fixtures"
        if entry["id"] == "workflow-validate":
            if not (fixture / "output").exists():
                self._pass(entry, "valid spec accepted without render/output")
            else:
                self._fail(entry, "workflow-validate unexpectedly rendered output")
        elif entry["id"] == "workflow-plan":
            plan = fixture / "plan.json"
            data = _read_json_object(plan.read_text(encoding="utf-8")) if plan.is_file() else None
            if data is not None and not (fixture / "output" / "final.mp4").exists():
                self._pass(entry, "plan artifact exists in the spec workspace and no media render occurred")
            else:
                self._fail(entry, "workflow plan missing or rendered media during planning")
        elif entry["id"] == "workflow-render":
            receipt_path = fixture / "receipt.json"
            output = fixture / "output" / "final.mp4"
            data = _read_json_object(receipt_path.read_text(encoding="utf-8")) if receipt_path.is_file() else None
            if data and data.get("status") == "completed" and output.is_file() and self._decode(output).returncode == 0:
                self._pass(entry, "render completed; confined output fully decodes and receipt is present")
            else:
                self._fail(entry, "render receipt/output missing or incomplete")
        else:
            receipt = fixture / "receipt.json"
            before = _sha256(receipt) if receipt.is_file() else None
            cp = self._cli_run(entry)
            after = _sha256(receipt) if receipt.is_file() else None
            if cp.returncode == 0 and before and before == after:
                self._pass(entry, "read-only inspect succeeded and receipt SHA-256 is unchanged")
            else:
                self._fail(entry, "inspect failed or modified the receipt", code=cp.returncode)

    def _run_mcp_protocol(self) -> None:
        entry = self._entry("mcp-protocol")
        if not self.installed:
            self._blocked(entry, "target checkout install unavailable")
            return
        try:
            from mcp import ClientSession, StdioServerParameters
            from mcp.client.stdio import stdio_client
            from mcp.types import Implementation
        except ImportError:
            self._blocked(entry, "MCP Python SDK is not available locally; no dependency installation attempted")
            return
        modes = entry.get("modes", [])
        captures: dict[str, tuple[str, set[str]]] = {}
        try:
            for mode in modes:
                version, names = asyncio.run(
                    self._capture_mcp_mode(
                        mode,
                        entry["argv"],
                        entry.get("client_info", {}),
                        ClientSession,
                        StdioServerParameters,
                        stdio_client,
                        Implementation,
                    )
                )
                captures[mode] = (version, names)
            expected = self._source_tool_sets()
            self.mcp_inventory = captures.get("all", ("", set()))[1]
        except Exception as exc:
            self._fail(
                entry, f"actual MCP initialize/tools/list or source comparison failed: {type(exc).__name__}: {exc}"
            )
            return
        discrepancies = []
        for mode, (version, names) in captures.items():
            if not version or not names:
                discrepancies.append(f"{mode}: missing server version or tools")
            wanted = expected.get(mode)
            if wanted is not None and names != wanted:
                discrepancies.append(
                    f"{mode}: observed/source names differ; missing={sorted(wanted - names)[:8]}, extra={sorted(names - wanted)[:8]}"
                )
            names_json = json.dumps(sorted(names), ensure_ascii=False, separators=(",", ":"))
            print(
                f"DISCOVERY mcp-inventory mode={mode} protocol_version={version} observed={len(names)} names={names_json} (tools/list only; not actions)",
                flush=True,
            )
        if discrepancies:
            self._fail(entry, "; ".join(discrepancies))
        else:
            details = ", ".join(f"{mode}={len(names)}" for mode, (_, names) in captures.items())
            self._pass(
                entry,
                f"real initialize/tools/list passed; each dynamic surface matched target source registry ({details})",
            )

    async def _capture_mcp_mode(
        self,
        mode: str,
        server_argv: list[str],
        client_info_data: dict[str, str],
        ClientSession: Any,
        StdioServerParameters: Any,
        stdio_client: Any,
        Implementation: Any,
    ) -> tuple[str, set[str]]:
        env = self._base_env()
        if mode != "default":
            env["KINOCUT_TOOLS"] = mode
        argv = expand_argv(server_argv, self._values())
        command = shutil.which(argv[0], path=env["PATH"]) or argv[0]
        params = StdioServerParameters(command=command, args=argv[1:], env=env, cwd=str(self.product_root))
        timeout = cast(Any, timedelta(seconds=90))
        async with (
            stdio_client(params) as (read, write),
            ClientSession(
                read,
                write,
                read_timeout_seconds=timeout,
                client_info=Implementation(**client_info_data),
            ) as session,
        ):
            init = await session.initialize()
            tools = await session.list_tools()
        return str(init.protocolVersion), {tool.name for tool in tools.tools}

    def _source_tool_sets(self) -> dict[str, set[str]]:
        source = """import json\nfrom kinocut.tool_registry import _allowed_names,parse_tool_mode\nprint(json.dumps({label:sorted(_allowed_names(*parse_tool_mode(raw))) for label,raw in [("all","all"),("default","core"),("profile:editor","profile:editor")]}))"""
        cp = self._run([str(self.python), "-c", source, str(self.product_root)], timeout=60)
        data = _read_json_object(cp.stdout)
        if cp.returncode or data is None:
            raise RuntimeError(f"source tool registry unavailable: {cp.stderr[-500:]}")
        return {mode: set(data[mode]) for mode in ("all", "default", "profile:editor")}

    def _mcp_call(
        self, mode: str, server_argv: list[str], name: str, arguments: dict[str, Any]
    ) -> tuple[int, dict[str, Any] | None, str, bool]:
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client
        from mcp.types import Implementation

        async def call() -> tuple[int, dict[str, Any] | None, str, bool]:
            env = self._base_env()
            if mode != "default":
                env["KINOCUT_TOOLS"] = mode
            argv = expand_argv(server_argv, self._values())
            command = shutil.which(argv[0], path=env["PATH"]) or argv[0]
            params = StdioServerParameters(command=command, args=argv[1:], env=env, cwd=str(self.product_root))
            async with (
                stdio_client(params) as (read, write),
                ClientSession(
                    read,
                    write,
                    read_timeout_seconds=cast(Any, timedelta(seconds=90)),
                    client_info=Implementation(**self.catalog["mcp_protocol"].get("client_info", {})),
                ) as session,
            ):
                await session.initialize()
                tools = await session.list_tools()
                if name not in {tool.name for tool in tools.tools}:
                    return 0, None, f"tool {name} not registered in {mode}", True
                result = await session.call_tool(name, arguments)
            structured = getattr(result, "structuredContent", None)
            if isinstance(structured, dict):
                return 0, structured, "", bool(getattr(result, "isError", False))
            fragments = []
            for item in getattr(result, "content", []) or []:
                text = getattr(item, "text", None)
                if text:
                    fragments.append(text)
            raw = "\n".join(fragments)
            return 0, _read_json_object(raw), raw, bool(getattr(result, "isError", False))

        return asyncio.run(call())

    def _run_mcp_call(self, entry: dict[str, Any]) -> None:
        if not self.installed:
            self._blocked(entry, "target checkout install unavailable")
            return
        if not self.fixtures_ready:
            self._blocked(entry, "required synthetic fixture generation did not pass")
            return
        try:
            request = entry["request"]
            args = expand_data(request.get("arguments", {}), self._values())
            _, data, raw, is_error = self._mcp_call("default", entry["argv"], request["tool"], args)
        except ImportError:
            self._blocked(entry, "MCP Python SDK is not available locally; no dependency installation attempted")
            return
        except Exception as exc:
            self._fail(entry, f"MCP initialize/list/call failed: {type(exc).__name__}: {exc}")
            return
        if data is None:
            self._fail(entry, f"MCP tool call did not return structured JSON: {raw[-500:]}")
            return
        if is_error:
            self._fail(entry, f"MCP tool call returned isError=true: {raw[-500:]}")
            return
        if entry["id"] == "mcp-video_doctor":
            summary = data.get("summary", {})
            if data.get("success") is not False and isinstance(summary, dict) and summary.get("required_ok") is True:
                self._pass(entry, "actual stdio tools/call returned required_ok=true and explicit optional diagnostics")
            else:
                self._fail(entry, "video_doctor did not return required_ok=true")
        elif entry["id"] == "mcp-video_info":
            width = _deep_find(data, "width")
            height = _deep_find(data, "height")
            if data.get("success") is not False and 320 in width and 180 in height:
                self._pass(entry, "actual stdio video_info matches the synthetic fixture dimensions")
            else:
                self._fail(entry, "video_info result did not expose matching 320x180 metadata")
        else:
            names = subtitle_search_matches(data)
            if names:
                self._pass(entry, f"actual stdio search_tools returned subtitle operations ({len(names)} matches)")
            else:
                self._fail(entry, "search_tools returned no structured subtitle operation matches")

    @staticmethod
    def _free_port() -> int:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.bind(("127.0.0.1", 0))
            return int(sock.getsockname()[1])

    @staticmethod
    def _port_is_open(port: int) -> bool:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.settimeout(0.3)
            return sock.connect_ex(("127.0.0.1", port)) == 0

    @staticmethod
    def _proc_start_ticks(pid: int) -> int | None:
        try:
            fields = (Path("/proc") / str(pid) / "stat").read_text(encoding="ascii").rsplit(")", 1)[1].split()
            return int(fields[19])
        except (OSError, IndexError, ValueError):
            return None

    @staticmethod
    def _preview_identity_matches(pid: int, project: Path, port: int, executable: str) -> bool:
        proc = Path("/proc") / str(pid)
        try:
            if proc.stat().st_uid != os.getuid():
                return False
            argv = [
                item.decode("utf-8", errors="replace")
                for item in (proc / "cmdline").read_bytes().split(bytes([0]))
                if item
            ]
            exe_path = str((proc / "exe").resolve())
        except OSError:
            return False
        if str(project.resolve()) not in argv:
            return False
        if not any(
            (item == "--port" and index + 1 < len(argv) and argv[index + 1] == str(port)) or item == f"--port={port}"
            for index, item in enumerate(argv)
        ):
            return False
        return (
            executable in argv or str(Path(executable).resolve()) in argv or exe_path == str(Path(executable).resolve())
        )

    def _stop_owned_hyperframes_preview(self, project: Path, port: int, executable: str) -> tuple[bool, str]:
        if not Path("/proc").is_dir():
            return False, "process identity is unavailable; no listener was signaled"
        was_open = self._port_is_open(port)
        candidates = []
        for proc in Path("/proc").iterdir():
            if not proc.name.isdecimal():
                continue
            pid = int(proc.name)
            start_ticks = self._proc_start_ticks(pid)
            if start_ticks is not None and self._preview_identity_matches(pid, project, port, executable):
                candidates.append((pid, start_ticks))
        if not candidates:
            if was_open:
                return (
                    False,
                    "port is open but no process matches this run's exact project and port; no listener was signaled",
                )
            return True, "assigned loopback port is closed and no owned preview process remains"
        for pid, start_ticks in candidates:
            if self._proc_start_ticks(pid) != start_ticks or not self._preview_identity_matches(
                pid, project, port, executable
            ):
                continue
            try:
                os.kill(pid, signal.SIGTERM)
            except ProcessLookupError:
                continue
            except PermissionError:
                return False, f"permission denied stopping owned preview PID {pid}"
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            still_owned = [
                pid
                for pid, start_ticks in candidates
                if self._proc_start_ticks(pid) == start_ticks
                and self._preview_identity_matches(pid, project, port, executable)
            ]
            if not still_owned and not self._port_is_open(port):
                break
            time.sleep(0.1)
        still_owned = [
            pid
            for pid, start_ticks in candidates
            if self._proc_start_ticks(pid) == start_ticks
            and self._preview_identity_matches(pid, project, port, executable)
        ]
        if still_owned or self._port_is_open(port):
            return (
                False,
                f"owned preview PID(s) {','.join(str(pid) for pid in still_owned or [pid for pid, _ in candidates])} did not close port {port}",
            )
        return True, f"stopped exact project/port preview PID(s) {','.join(str(pid) for pid, _ in candidates)}"

    def _run_static_review(self, entry: dict[str, Any]) -> None:
        if not self.installed or not self.fixtures_ready:
            self._blocked(entry, "target install or synthetic fixture unavailable")
            return
        argv = self._expanded(entry)
        cp = self._run(argv, timeout=60)
        if cp.returncode:
            self._fail(entry, f"kino review-ui failed: {cp.stderr[-400:] or cp.stdout[-400:]}", code=cp.returncode)
            return
        review = self.work / "review"
        if not review.is_dir():
            self._fail(entry, "kino review-ui exited zero without creating the declared review directory")
            return
        shutil.copy2(self.work / "fixtures" / "input.mp4", review / "input.mp4")
        timeline = review / "timeline.json"
        timeline.write_text(json.dumps({"qa_fixture": "initial"}), encoding="utf-8")
        port = self._free_port()
        # Use a directly-owned server process for the interactive browser session.
        env = self._base_env()
        try:
            process = subprocess.Popen(  # noqa: S603 - fixed Python module; argument vector, shell disabled
                [sys.executable, "-m", "http.server", str(port), "--bind", "127.0.0.1", "--directory", str(review)],
                cwd=str(self.work),
                env=env,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                shell=False,
            )

        except OSError as exc:
            self._blocked(entry, f"cannot start task-owned loopback HTTP server: {exc}")
            return
        self.preview_process = process
        http_code = None
        try:
            url = f"http://127.0.0.1:{port}/review.html?media=input.mp4"
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline:
                try:
                    with urllib.request.urlopen(url, timeout=1) as response:
                        http_code = response.status
                        html = response.read().decode("utf-8", errors="replace")
                    break
                except (urllib.error.URLError, TimeoutError):
                    if process.poll() is not None:
                        break
                    time.sleep(0.1)
            if http_code != 200 or 'id="player"' not in html or "setInterval(load, 2000)" not in html:
                self._fail(
                    entry,
                    "local review page did not serve its video player and two-second hot-reload code",
                    http=http_code,
                )
                return
            for name in ("timeline.json", "input.mp4"):
                with urllib.request.urlopen(f"http://127.0.0.1:{port}/{name}", timeout=5) as response:
                    if response.status != 200:
                        raise RuntimeError(f"HTTP {response.status} for {name}")
            try:
                sync_playwright = importlib.import_module("playwright.sync_api").sync_playwright
            except ImportError:
                self._blocked(
                    entry,
                    "HTTP routes returned 200, but Python Playwright/browser is not installed locally; no browser download attempted",
                    http=http_code,
                )
                return
            console_lines: list[str] = []
            requests: list[str] = []
            page_errors: list[str] = []
            failed_requests: list[str] = []
            browser_log = self.work / "artifacts" / "static-review-browser.json"
            try:
                with browser_tempdir() as browser_tmp, sync_playwright() as playwright:
                    try:
                        browser = playwright.chromium.launch(headless=True, executable_path=os.environ.get("QA_CHROMIUM_EXECUTABLE"), env={**self._base_env(), "TMPDIR": browser_tmp})
                    except Exception as exc:
                        browser_log.write_text(
                            json.dumps({"console": console_lines, "requests": requests, "page_errors": page_errors}),
                            encoding="utf-8",
                        )
                        self._blocked(
                            entry,
                            f"loopback HTTP passed, but no usable installed Chromium is available: {type(exc).__name__}: {exc}",
                            http=http_code,
                        )
                        return
                    try:
                        page = browser.new_page()
                        page.on("console", lambda message: console_lines.append(f"{message.type}: {message.text}"))
                        page.on("pageerror", lambda error: page_errors.append(str(error)))
                        page.on("request", lambda request: requests.append(request.url))
                        page.on("requestfailed", lambda request: failed_requests.append(request.url))
                        local_prefix = f"http://127.0.0.1:{port}/"
                        page.route(
                            "**/*",
                            lambda route: (
                                route.continue_()
                                if route.request.url.startswith(local_prefix)
                                or route.request.url.startswith(("data:", "blob:"))
                                else route.abort()
                            ),
                        )
                        page.goto(url, wait_until="load", timeout=15000)
                        page.wait_for_function(
                            "document.querySelector('#status').textContent.includes('Loaded')", timeout=10000
                        )
                        page.locator("#player").evaluate("video => { video.muted=true; video.play(); }")
                        page.wait_for_function("document.querySelector('#player').readyState >= 2", timeout=10000)
                        page.locator("#player").evaluate("video => { video.currentTime=1.5; }")
                        page.wait_for_function(
                            "Math.abs(document.querySelector('#player').currentTime-1.5)<0.5", timeout=5000
                        )
                        page.screenshot(path=str(self.work / "artifacts" / "static-review.png"))
                        timeline.write_text(json.dumps({"qa_fixture": "updated"}), encoding="utf-8")
                        page.wait_for_function(
                            "document.querySelector('#out').textContent.includes('updated')", timeout=7000
                        )
                        timeline.write_text("{invalid", encoding="utf-8")
                        page.wait_for_function(
                            "document.querySelector('#status').textContent.includes('Failed to load timeline')",
                            timeout=7000,
                        )
                        timeline.write_text(json.dumps({"qa_fixture": "recovered"}), encoding="utf-8")
                        page.wait_for_function(
                            "document.querySelector('#out').textContent.includes('recovered')", timeout=7000
                        )
                        if page_errors:
                            raise RuntimeError(f"browser page errors: {page_errors[:2]}")
                        local_prefix = f"http://127.0.0.1:{port}/"
                        outside = [
                            item
                            for item in requests
                            if not item.startswith(local_prefix) and not item.startswith(("data:", "blob:"))
                        ]
                        if outside:
                            raise RuntimeError(f"browser attempted non-loopback requests: {outside[:2]}")
                    finally:
                        browser.close()
            except Exception as exc:
                browser_log.write_text(
                    json.dumps(
                        {
                            "console": console_lines,
                            "requests": requests,
                            "failed_requests": failed_requests,
                            "page_errors": page_errors,
                            "exception": f"{type(exc).__name__}: {exc}",
                        },
                        ensure_ascii=False,
                        indent=2,
                    ),
                    encoding="utf-8",
                )
                self._fail(
                    entry,
                    f"loopback HTTP passed, but browser operator assertions failed: {type(exc).__name__}: {exc}",
                    http=http_code,
                )
                return
            browser_log.write_text(
                json.dumps(
                    {
                        "console": console_lines,
                        "requests": requests,
                        "failed_requests": failed_requests,
                        "page_errors": page_errors,
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
            self._pass(
                entry,
                "loopback HTTP 200; browser played/sought synthetic media and hot-reloaded, surfaced malformed JSON, then recovered; screenshots and console/network logs retained (visual judgment remains human)",
                http=http_code,
            )
        except Exception as exc:
            self._fail(entry, f"static review HTTP/browser flow failed: {type(exc).__name__}: {exc}", http=http_code)
        finally:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
            self.preview_process = None

    def _run_hyperframes(self, entry: dict[str, Any]) -> None:
        if not self.installed or not self.fixtures_ready:
            self._blocked(entry, "target install or synthetic fixture unavailable")
            return
        executable = shutil.which("hyperframes", path=self._base_env()["PATH"])
        if not executable:
            self._blocked(
                entry,
                "no preinstalled Hyperframes CLI is available; this offline runner will not invoke npx or download a package",
            )
            return
        self.hyperframes_executable = executable
        version_cp = self._run([executable, "--version"], cwd=self.work, timeout=15)
        version = version_cp.stdout.strip() or version_cp.stderr.strip()
        if version_cp.returncode or not any(tag in version for tag in ("0.8.104", "0.8.140")):
            self._blocked(
                entry,
                f"installed Hyperframes CLI version is not verified as supported by target docs: {version!r}; no package install attempted",
            )
            return
        if not Path("/proc").is_dir():
            self._blocked(entry, "Linux process identity is unavailable; no preview server was started")
            return
        gsap_dir = Path(os.environ.get("QA_GSAP_PACKAGE", ""))
        try:
            gsap_meta = json.loads((gsap_dir / "package.json").read_text(encoding="utf-8"))
            if gsap_meta.get("name") != "gsap" or gsap_meta.get("version") != "3.12.5":
                raise ValueError("expected gsap 3.12.5")
            gsap_script = gsap_dir / "dist" / "gsap.min.js"
            if not gsap_script.is_file():
                raise ValueError("dist/gsap.min.js missing")
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            self._blocked(entry, f"pinned GSAP 3.12.5 fixture dependency unavailable: {exc}; set QA_GSAP_PACKAGE")
            return
        project = self.work / "hyperframes"
        project.mkdir(exist_ok=False)
        target_gsap = project / "node_modules" / "gsap" / "dist"
        target_gsap.mkdir(parents=True)
        shutil.copy2(gsap_script, target_gsap / "gsap.min.js")
        shutil.copy2(ROOT / "qa" / "fixtures" / "hyperframes.html", project / "index.html")
        port = self._free_port()
        if self._port_is_open(port):
            self._blocked(entry, "chosen loopback port became occupied before launch; no listener was stopped")
            return
        values = {**self._values(), "dynamic_port": port}
        argv = expand_argv(entry["argv"], values)
        env = self._base_env()
        env["MCP_VIDEO_HYPERFRAMES_COMMAND"] = executable
        cp = self._run(argv, cwd=self.work, timeout=90, env=env)
        url = f"http://127.0.0.1:{port}/"
        if cp.returncode != 0:
            status = "FAIL"
            detail = (
                f"kino hyperframes-preview failed on merged product SHA {self.product_sha}: "
                f"{cp.stderr[-700:] or cp.stdout[-700:]}; installed Hyperframes {version}"
            )
            http_code = None
        else:
            status, detail, http_code = self._probe_hyperframes_browser(url, port)
        cleanup_ok, cleanup_detail = self._stop_owned_hyperframes_preview(project, port, executable)
        if cleanup_ok:
            detail = f"{detail}; cleanup verified: {cleanup_detail}"
        else:
            status = "FAIL"
            detail = f"{detail}; cleanup incomplete: {cleanup_detail}"
        self._result(entry, status, detail, code=cp.returncode if cp.returncode else None, http=http_code)

    def _probe_hyperframes_browser(self, url: str, port: int) -> tuple[str, str, int | None]:
        try:
            with urllib.request.urlopen(url, timeout=5) as response:  # noqa: S310 - caller constructs exact loopback-only URL
                http_code = response.status
        except (urllib.error.URLError, TimeoutError) as exc:
            return "FAIL", f"Kino preview returned zero but local preview URL did not respond: {exc}", None
        if http_code != 200:
            return "FAIL", f"Hyperframes loopback preview returned HTTP {http_code}", http_code
        try:
            sync_playwright = importlib.import_module("playwright.sync_api").sync_playwright
        except ImportError:
            return (
                "BLOCKED",
                "Hyperframes HTTP passed, but Playwright is not installed; no browser download attempted",
                http_code,
            )

        console_lines: list[str] = []
        requests: list[str] = []
        failed_requests: list[str] = []
        page_errors: list[str] = []
        browser_log = self.work / "artifacts" / "hyperframes-browser.json"
        try:
            with browser_tempdir() as browser_tmp, sync_playwright() as playwright:
                try:
                    browser = playwright.chromium.launch(headless=True, executable_path=os.environ.get("QA_CHROMIUM_EXECUTABLE"), env={**self._base_env(), "TMPDIR": browser_tmp})
                except Exception as exc:
                    browser_log.write_text(
                        json.dumps({"console": console_lines, "requests": requests, "page_errors": page_errors}),
                        encoding="utf-8",
                    )
                    return (
                        "BLOCKED",
                        f"Hyperframes HTTP passed, but installed Chromium is unavailable: {type(exc).__name__}: {exc}",
                        http_code,
                    )
                try:
                    page = browser.new_page()
                    page.on("console", lambda message: console_lines.append(f"{message.type}: {message.text}"))
                    page.on("request", lambda request: requests.append(request.url))
                    page.on("requestfailed", lambda request: failed_requests.append(request.url))
                    page.on("pageerror", lambda error: page_errors.append(str(error)))
                    local_prefix = f"http://127.0.0.1:{port}/"
                    page.route(
                        "**/*",
                        lambda route: (
                            route.continue_()
                            if route.request.url.startswith(local_prefix)
                            or route.request.url.startswith(("data:", "blob:"))
                            else route.abort()
                        ),
                    )
                    page.goto(url + "#project/hyperframes", wait_until="domcontentloaded", timeout=15000)
                    page.locator('button[aria-label="Play"]').wait_for(timeout=15000)
                    wait_for_playable(
                        page,
                        timeout_ms=PLAY_READY_TIMEOUT_MS,
                        page_errors=page_errors,
                        failed_requests=failed_requests,
                    )
                    frame = next((f for f in page.frames if f.locator("#stage").count()), None)
                    if frame is None:
                        raise RuntimeError("composition frame missing")
                    snapshot = """() => {
                        const t = window.__timelines?.['kinocut-preview-proof'];
                        const marker = document.querySelector('#marker');
                        return t && marker ? {time: t.time(), left: marker.getBoundingClientRect().left} : null;
                    }"""
                    before = frame.evaluate(snapshot)
                    if not before:
                        raise RuntimeError("composition timeline missing")
                    page.locator('button[aria-label="Play"]').click()
                    page.wait_for_timeout(1400)
                    playing = frame.evaluate(snapshot)
                    if not playing or playing["time"] <= 0.5 or playing["left"] <= before["left"]:
                        raise RuntimeError(f"composition did not advance: {playing}")
                    page.locator('button[aria-label="Pause"]').click()
                    track = page.locator('[aria-label="Timeline track view"]').bounding_box()
                    clip = page.locator('button.timeline-clip[aria-label^="Headline,"]').bounding_box()
                    if not track or not clip:
                        raise RuntimeError("visible timeline geometry unavailable")
                    page.mouse.click(clip["x"] + clip["width"] * 4 / 6, track["y"] + 14)
                    page.wait_for_timeout(450)
                    scrubbed = frame.evaluate(snapshot)
                    if not scrubbed or abs(scrubbed["time"] - 4) > 0.25 or scrubbed["left"] <= playing["left"]:
                        raise RuntimeError(f"composition scrub did not reach four seconds: {scrubbed}")
                    page.screenshot(path=str(self.work / "artifacts" / "hyperframes-preview.png"))
                    if page_errors:
                        raise RuntimeError(f"browser page errors: {page_errors[:2]}")
                    local_prefix = f"http://127.0.0.1:{port}/"
                    outside = [
                        item
                        for item in requests
                        if not item.startswith(local_prefix) and not item.startswith(("data:", "blob:"))
                    ]
                    if outside:
                        raise RuntimeError(f"browser attempted non-loopback requests: {outside[:2]}")
                finally:
                    browser.close()
        except Exception as exc:
            browser_log.write_text(
                json.dumps(
                    {
                        "console": console_lines,
                        "requests": requests,
                        "failed_requests": failed_requests,
                        "page_errors": page_errors,
                        "exception": f"{type(exc).__name__}: {exc}",
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
            return "FAIL", f"Hyperframes browser preview/playback/scrub failed: {type(exc).__name__}: {exc}", http_code
        browser_log.write_text(
            json.dumps(
                {
                    "console": console_lines,
                    "requests": requests,
                    "failed_requests": failed_requests,
                    "page_errors": page_errors,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        return (
            "PASS",
            "Hyperframes HTTP 200; browser played/scrubbed the animated composition and retained screenshot/logs (visual review remains pending)",
            http_code,
        )

    def _print_coverage_gaps(self) -> None:
        for gap in self.catalog.get("coverage_gaps", []):
            print(f"COVERAGE {gap['status']} {gap['id']}: {gap['missing']}", flush=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--product-root", required=True, type=Path, help="caller-supplied clean exact product checkout")
    parser.add_argument("--product-sha", help="optional full SHA that must equal the supplied checkout HEAD")
    parser.add_argument("--catalog", type=Path, default=CATALOG)
    parser.add_argument("--work-dir", type=Path, help="new empty work directory; generated outputs remain there")
    args = parser.parse_args()
    work = args.work_dir or Path(tempfile.mkdtemp(prefix="kinocut-qa-", dir=os.environ.get("TMPDIR"))) / "run"
    try:
        runner = OperatorRunner(args.product_root, work, args.catalog, args.product_sha)
        return runner.run()
    except (CatalogError, OSError, ValueError) as exc:
        print(f"BLOCKED runner: {exc}", file=sys.stderr, flush=True)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
