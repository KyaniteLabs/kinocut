from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_ci_runner_image_pins_bases_and_preinstalls_required_tools():
    dockerfile = (ROOT / "containers" / "ci" / "Dockerfile").read_text(encoding="utf-8")

    assert dockerfile.count("FROM ") == 2
    assert dockerfile.count("@sha256:") == 2
    for tool in ("ffmpeg", "git", "python3", "node"):
        assert tool in dockerfile
    assert "rm -rf /var/lib/apt/lists/*" in dockerfile


def test_runner_topology_keeps_heavy_work_off_forgejo_host():
    topology = (ROOT / "docs" / "CI_RUNNER_TOPOLOGY.md").read_text(encoding="utf-8")

    assert "do not execute on the Forgejo application" in topology
    assert "docker://REGISTRY/kinocut-ci@sha256:DIGEST" in topology
    assert "require an authorized human" in topology
