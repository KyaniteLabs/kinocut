"""Thin public adapters for sound leaves (S12).

This package exposes flat and namespaced discovery without importing
``kinocut.*`` runtime. Host CLI/MCP registration may bind these descriptors
in a later controller-owned change; this leaf freezes the adapter contracts.
"""

from __future__ import annotations
from kinocut_sound.public.discovery import (
    SoundCapabilityManifest,
    discover_sound_capabilities,
    list_flat_commands,
    list_namespaced_commands,
)
from kinocut_sound.public.adapters import (
    SoundPythonAdapter,
    invoke_sound_operation,
)

__all__ = [
    "SoundCapabilityManifest",
    "SoundPythonAdapter",
    "discover_sound_capabilities",
    "invoke_sound_operation",
    "list_flat_commands",
    "list_namespaced_commands",
]
