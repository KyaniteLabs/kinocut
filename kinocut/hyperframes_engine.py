"""Compatibility re-exports for the legacy Hyperframes engine (ADR 0001)."""

from .errors import HyperframesNotFoundError as HyperframesNotFoundError
from .errors import HyperframesProjectError as HyperframesProjectError
from .errors import HyperframesRenderError as HyperframesRenderError
from .errors import MCPVideoError as MCPVideoError
from .hyperframes.models import HyperframesPreviewResult as HyperframesPreviewResult
from .hyperframes.models import HyperframesValidationResult as HyperframesValidationResult
from .hyperframes.compositions import compositions as compositions
from .hyperframes.ops import add_block as add_block
from .hyperframes.ops import benchmark as benchmark
from .hyperframes.ops import capture as capture
from .hyperframes.ops import catalog as catalog
from .hyperframes.ops import create_project as create_project
from .hyperframes.ops import doctor as doctor
from .hyperframes.ops import info as info
from .hyperframes.ops import inspect as inspect
from .hyperframes.ops import remove_background as remove_background
from .hyperframes.ops import render as render
from .hyperframes.ops import snapshot as snapshot
from .hyperframes.ops import still as still
from .hyperframes.ops import transcribe as transcribe
from .hyperframes.ops import tts as tts
from .hyperframes.ops import validate as validate
from .hyperframes.pipeline import render_and_post as render_and_post
from .hyperframes.preview import _active_previews as _active_previews
from .hyperframes.preview import _preview_ready as _preview_ready
from .hyperframes.preview import _register_preview as _register_preview
from .hyperframes.preview import _terminate_preview as _terminate_preview
from .hyperframes.preview import preview as preview
from .hyperframes.preview import release_preview as release_preview
from .hyperframes.preview import stop_all_previews as stop_all_previews
from .hyperframes.preview import stop_preview as stop_preview
from .hyperframes.runner import HYPERFRAMES_COMMAND_ENV as HYPERFRAMES_COMMAND_ENV
from .hyperframes.runner import HYPERFRAMES_COMMAND_PREFIX as HYPERFRAMES_COMMAND_PREFIX
from .hyperframes.runner import _SCHEMA as _SCHEMA
from .hyperframes.runner import _find_local_hyperframes_binary as _find_local_hyperframes_binary
from .hyperframes.runner import _format_cli_value as _format_cli_value
from .hyperframes.runner import _hyperframes_command_prefix as _hyperframes_command_prefix
from .hyperframes.runner import _hyperframes_environment as _hyperframes_environment
from .hyperframes.runner import _hyperframes_op as _hyperframes_op
from .hyperframes.runner import _hyperframes_telemetry_allowed as _hyperframes_telemetry_allowed
from .hyperframes.runner import _require_docker_consent as _require_docker_consent
from .hyperframes.runner import _require_hyperframes_deps as _require_hyperframes_deps
from .hyperframes.runner import _require_node as _require_node
from .hyperframes.runner import _require_private_preview as _require_private_preview
from .hyperframes.runner import _run_hyperframes as _run_hyperframes
from .hyperframes.runner import _split_configured_hyperframes_command as _split_configured_hyperframes_command
from .hyperframes.validation import _find_entry_point as _find_entry_point
from .hyperframes.validation import _validate_project as _validate_project
from .hyperframes.validation import _validate_project_name as _validate_project_name
from .defaults import DEFAULT_HYPERFRAMES_TELEMETRY as DEFAULT_HYPERFRAMES_TELEMETRY
from .defaults import DEFAULT_HYPERFRAMES_VERSION_TIMEOUT as DEFAULT_HYPERFRAMES_VERSION_TIMEOUT
from .validation import HYPERFRAMES_PRIVATE_PREVIEW_VERSIONS as HYPERFRAMES_PRIVATE_PREVIEW_VERSIONS

import shutil as shutil
import subprocess as subprocess
