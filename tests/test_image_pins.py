"""Public base images are pinned by digest, so a moved tag cannot change CI or the release image."""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PUBLIC = re.compile(r"^\s*(?:FROM|image:)\s+(?:--\S+\s+)?((?:ubuntu|python):\S+)", re.M)


def test_public_base_images_carry_a_sha256_digest():
    seen = 0
    for rel in ("Dockerfile", "Dockerfile.ci", ".forgejo/workflows/ci.yml"):
        for ref in PUBLIC.findall((ROOT / rel).read_text()):
            seen += 1
            assert re.search(r"@sha256:[0-9a-f]{64}$", ref), f"{rel}: {ref} is not digest-pinned"
    assert seen == 4
