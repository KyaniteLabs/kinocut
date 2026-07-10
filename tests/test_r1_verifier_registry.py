from __future__ import annotations

import pytest

from mcp_video.rescue.models import VerificationCheck
from mcp_video.rescue.verifier import CHECK_IDS
from mcp_video.rescue.r1.verifier_registry import VerifierDefinition, VerifierRegistry


def _toy_check(_: object) -> VerificationCheck:
    return VerificationCheck(id="toy_crop_bounds", passed=False, message="Crop exceeds bounds.")


def test_feature_verifier_is_additive_to_mandatory_rescue_checks() -> None:
    registry = VerifierRegistry((VerifierDefinition(id="toy_crop_bounds", run=_toy_check),))

    resolved = registry.resolve_with_mandatory(("toy_crop_bounds",))

    assert tuple(item.id for item in resolved[: len(CHECK_IDS)]) == CHECK_IDS
    assert resolved[-1].run(None).passed is False


def test_feature_verifier_cannot_override_mandatory_check() -> None:
    with pytest.raises(ValueError, match="mandatory rescue verifier"):
        VerifierRegistry((VerifierDefinition(id=CHECK_IDS[0], run=_toy_check),))
