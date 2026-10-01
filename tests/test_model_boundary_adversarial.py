"""Synthetic learned-output and endpoint-policy tests; no weights or network."""

from types import SimpleNamespace

import numpy as np
from PIL import Image
import pytest

from kinocut.errors import MCPVideoError
from kinocut.object_matte.infer import infer_mask, postprocess
from kinocut.te import sphere_director as director


@pytest.mark.parametrize(
    "logits",
    [
        np.array([[np.nan, 1], [1, 1]]),
        np.array([[np.inf, 0], [0, 0]]),
        np.array([[-np.inf, 0], [0, 0]]),
        np.ones((2, 1, 4, 4)),
        np.ones((1, 3, 4, 4)),
        np.ones((4,)),
        np.ones((0, 4)),
        np.array(1.0),
        np.ones((2, 2), dtype=complex),
        np.array([["not a mask"]]),
        [[1], [1, 2]],
    ],
)
def test_invalid_model_output_fails_before_mask_publication(monkeypatch, logits):
    monkeypatch.setattr(Image, "fromarray", lambda *args, **kwargs: pytest.fail("Invalid masks cannot be published"))
    with pytest.raises(MCPVideoError) as error:
        postprocess(logits, (40, 20))
    assert error.value.code == "invalid_model_output"


@pytest.mark.parametrize("shape", [(2, 2), (1, 2, 2), (1, 1, 2, 2), (1, 1, 1, 2), (1, 1, 2, 1)])
def test_valid_single_mask_layout_and_singleton_spatial_axes_are_preserved(shape):
    logits = np.linspace(-2, 2, np.prod(shape)).reshape(shape)
    mask = postprocess(logits, (40, 20))
    assert mask.mode == "L" and mask.size == (40, 20)
    assert np.asarray(mask).max() > 0


@pytest.mark.parametrize("outputs", [[], None, {"mask": np.ones((2, 2))}, [np.full((2, 2), np.nan)]])
def test_malformed_session_output_is_structured(outputs):
    session = SimpleNamespace(get_inputs=lambda: [SimpleNamespace(name="image")], run=lambda *args: outputs)
    with pytest.raises(MCPVideoError) as error:
        infer_mask(session, Image.new("RGB", (4, 4)))
    assert error.value.code == "invalid_model_output"


def test_finite_float64_extremes_are_clipped_without_float32_overflow():
    mask = postprocess(np.array([[-1e300, 1e300], [0, 1]]), (2, 2))
    assert np.asarray(mask)[0].tolist() == [0, 255]


@pytest.fixture
def isolated_director(monkeypatch):
    for name in (director.ENV_DIRECTOR, director.ENV_MODEL, director.ENV_BASE_URL, director.ENV_ALLOW_CLOUD):
        monkeypatch.delenv(name, raising=False)
    return director


@pytest.mark.parametrize("url", [None, "http://localhost:11434", "https://127.5.6.7:8080", "http://[::1]:1234"])
def test_local_director_default_and_literal_loopback_are_local(isolated_director, url):
    detected = isolated_director.detect_sphere_director(director="ollama", base_url=url)
    assert detected["kind"] == "local"
    isolated_director._assert_cloud_allowed(detected, False)


@pytest.mark.parametrize(
    "url",
    [
        "http://192.168.1.2:11434",
        "http://10.0.0.1:11434",
        "https://api.example.com",
        "http://localhost.evil.example",
        "http://127.0.0.1.evil.example",
        "http://127%2e0%2e0%2e1",
        "http://127.1",
        "http://[2001:db8::1]",
    ],
)
def test_local_provider_remote_endpoint_requires_explicit_opt_in_before_callback(isolated_director, monkeypatch, url):
    detected = isolated_director.detect_sphere_director(director="ollama", base_url=url)
    assert detected["kind"] == "cloud"
    monkeypatch.setattr(isolated_director, "propose_sphere_plan", lambda *args, **kwargs: {})
    with pytest.raises(MCPVideoError) as error:
        isolated_director.apply_director(
            "source.mp4",
            director="ollama",
            base_url=url,
            propose=lambda plan: pytest.fail("No injected callback may receive the plan before opt-in"),
        )
    assert error.value.code == "cloud_execution_denied"
    isolated_director._assert_cloud_allowed(detected, True)


@pytest.mark.parametrize(
    "url",
    [
        "http://user:secret@localhost",
        "http://localhost@remote.example",
        "ftp://localhost",
        "localhost:11434",
        "http://",
        "http://[::1",
        "http://localhost:99999",
        "http://localhost:bad",
        "http://local host",
        "http://localhost\\@remote.example",
    ],
)
def test_malformed_or_userinfo_endpoint_fails_without_echoing_input(isolated_director, url):
    with pytest.raises(MCPVideoError) as error:
        isolated_director.detect_sphere_director(director="ollama", base_url=url)
    assert error.value.code == "invalid_director_endpoint"
    assert url not in str(error.value)


def test_cloud_provider_cannot_be_downgraded_by_loopback_endpoint(isolated_director):
    detected = isolated_director.detect_sphere_director(director="openai", base_url="http://localhost:8080")
    assert detected["kind"] == "cloud"
    with pytest.raises(MCPVideoError):
        isolated_director._assert_cloud_allowed(detected, "false")


def test_environment_endpoint_and_opt_in_are_enforced(isolated_director, monkeypatch):
    monkeypatch.setenv(isolated_director.ENV_BASE_URL, "https://api.example.com")
    detected = isolated_director.detect_sphere_director(director="lmstudio")
    assert detected["kind"] == "cloud"
    with pytest.raises(MCPVideoError):
        isolated_director._assert_cloud_allowed(detected, False)
    monkeypatch.setenv(isolated_director.ENV_ALLOW_CLOUD, "true")
    isolated_director._assert_cloud_allowed(detected, False)
