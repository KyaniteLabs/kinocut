from pathlib import Path


THREAT_MODEL = Path(__file__).parents[1] / "docs/security/PROJECTSTORE_THREAT_MODEL.md"


def test_projectstore_threat_model_covers_required_attack_surface():
    text = THREAT_MODEL.read_text(encoding="utf-8")

    for required in (
        "Job-store record tampering",
        "PID reuse",
        "path traversal",
        "CAS digest",
        "Resource URI cross-project access",
        "Detached runner privilege",
        "not an authentication or OS sandbox",
    ):
        assert required.lower() in text.lower()


def test_projectstore_threat_model_keeps_future_resource_authorization_fail_closed():
    text = THREAT_MODEL.read_text(encoding="utf-8")

    assert "No `kinocut://jobs/...` resource handler is shipped" in text
    assert "cross-project denial tests" in text
