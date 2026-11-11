"""Agent and application homes Kinocut must never write into.

Hermes passes ``PLUGIN_ROOT`` to plugin MCP servers but not ``HERMES_HOME``,
and starts them with the plugin's install folder as the working directory, so
those two facts are what locate a Hermes home that is not ``~/.hermes``.
"""

from __future__ import annotations

import os
import tempfile

from .errors import MCPVideoError

_HOME_ENV_VARS = ("HERMES_HOME", "CODEX_HOME", "CLAUDE_CONFIG_DIR", "XDG_CONFIG_HOME")


def hermes_plugin_homes() -> list[str]:
    """The plugin's install folder and, when found, the Hermes home around it.

    On a non-default home (such as ``~/.hermes-org``) the home is found from
    the plugin folder: ``<home>/plugins/<name>`` next to ``<home>/config.yaml``.
    """
    root = os.environ.get("PLUGIN_ROOT")
    if not root:
        return []
    root = os.path.realpath(os.path.expanduser(root))
    homes = [root]
    plugins_dir = os.path.dirname(root)
    hermes_home = os.path.dirname(plugins_dir)
    if os.path.basename(plugins_dir) == "plugins" and os.path.isfile(os.path.join(hermes_home, "config.yaml")):
        homes.append(hermes_home)
    return homes


def require_absolute_under_hermes(path: str, label: str) -> None:
    """Refuse a relative path under Hermes: it would land inside the plugin package."""
    if os.environ.get("PLUGIN_ROOT") and not os.path.isabs(os.path.expanduser(path)):
        raise MCPVideoError(
            f"{label} must be an absolute path",
            error_type="validation_error",
            code="invalid_output_path",
            suggested_action={
                "auto_fix": False,
                "description": "Pass the full path, for example next to the input file.",
            },
        )


def inside_agent_scratch_or_refuse(resolved: str, label: str) -> bool:
    """True for the agent's own temp folder; raise for anything else in an agent home."""
    homes = [
        os.path.realpath(os.path.expanduser(os.environ[name])) for name in _HOME_ENV_VARS if os.environ.get(name)
    ] + hermes_plugin_homes()
    # Hermes puts TMPDIR inside its home; flows write intermediates there.
    scratch = os.path.realpath(tempfile.gettempdir())
    if resolved.startswith(scratch + os.sep) and any(scratch.startswith(h + os.sep) for h in homes):
        return True
    for home in homes:
        if resolved == home or resolved.startswith(home + os.sep):
            raise MCPVideoError(
                f"{label} targets a configured agent or application home",
                error_type="validation_error",
                code="unsafe_path",
            )
    return False
