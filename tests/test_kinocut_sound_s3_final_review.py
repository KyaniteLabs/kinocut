"""Static adapter registry rejects import-shaped identifiers."""

from __future__ import annotations

import pytest

from kinocut_sound.registry import AdapterRegistry, RegistryError
from tests.test_kinocut_sound_s3_policy import _Adapter, _local


@pytest.mark.parametrize("adapter_id", ("pkg.module.Adapter", "pkg.module:Adapter", "AdapterClass"))
def test_registry_rejects_import_shaped_ids_without_side_effects(adapter_id: str) -> None:
    calls = 0

    def constructor() -> _Adapter:
        nonlocal calls
        calls += 1
        return _local()

    with pytest.raises(RegistryError) as exc_info:
        AdapterRegistry({adapter_id: constructor})
    assert exc_info.value.code == "invalid_registry"
    assert calls == 0
