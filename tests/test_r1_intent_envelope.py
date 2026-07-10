from __future__ import annotations

from mcp_video.rescue.models import canonical_payload
from mcp_video.rescue.r1.models import FeatureIntent, IntentPlanEnvelope, PolicyRef


def test_intent_envelope_does_not_change_nested_rescue_plan(rescue_plan) -> None:
    before_json = rescue_plan.model_dump_json()
    before_canonical = canonical_payload(rescue_plan)

    envelope = IntentPlanEnvelope.create(
        base_plan=rescue_plan,
        policy=PolicyRef(id="toy_visual_crop", version=1),
        intent=FeatureIntent(
            feature_id="toy_visual_crop",
            action_ids=("crop:subject",),
            payload={"crop_tracks": [{"start": 0.0, "end": 1.0, "x": 0.1, "y": 0.1}]},
        ),
        verifier_ids=("toy_crop_bounds",),
    )

    assert envelope.intent_sha256.startswith("sha256:")
    assert envelope.base_plan.plan_sha256 == rescue_plan.plan_sha256
    assert envelope.base_plan.model_dump_json() == before_json
    assert canonical_payload(envelope.base_plan) == before_canonical
