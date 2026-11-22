"""Reasoning-model replies and operator-set token budgets (KC-5)."""

import json
from types import SimpleNamespace

from kinocut.defaults import (
    DEFAULT_PRODUCT_DESCRIPTION_MAX_TOKENS,
    DEFAULT_VISION_PROVIDER_MAX_TOKENS,
    ENV_PRODUCT_DESCRIPTION_MAX_TOKENS,
    ENV_VISION_MAX_TOKENS,
    token_budget,
)
from kinocut.vision_policy import strip_think_blocks
from kinocut.watching.vision_provider import SemanticVisionAssessment

ASSESSMENT = {"verdict": "pass", "summary": "clean", "findings": []}


def test_think_block_followed_by_json_parses():
    reply = "<think>Hmm, {not json} yet.\nCheck frames.</think>\n" + json.dumps(ASSESSMENT)
    assessment = SemanticVisionAssessment.model_validate_json(strip_think_blocks(reply))
    assert assessment.verdict == "pass"


def test_unterminated_think_block_is_dropped():
    assert strip_think_blocks("Answer.<think>ran out of tokens") == "Answer."


def test_plain_text_is_unchanged():
    assert strip_think_blocks("  A red mug.  ") == "A red mug."


def test_token_budget_defaults_and_overrides(monkeypatch):
    default = DEFAULT_VISION_PROVIDER_MAX_TOKENS
    monkeypatch.delenv(ENV_VISION_MAX_TOKENS, raising=False)
    assert token_budget(ENV_VISION_MAX_TOKENS, default) == default
    monkeypatch.setenv(ENV_VISION_MAX_TOKENS, "4096")
    assert token_budget(ENV_VISION_MAX_TOKENS, default) == 4096
    for bad in ("abc", "0", "-5", "999999", ""):
        monkeypatch.setenv(ENV_VISION_MAX_TOKENS, bad)
        assert token_budget(ENV_VISION_MAX_TOKENS, default) == default


def test_product_description_request_uses_budget_and_strips_think(monkeypatch):
    from kinocut.image_engine import _request_product_description

    seen = {}

    class Client:
        class messages:
            @staticmethod
            def create(**kwargs):
                seen.update(kwargs)
                return SimpleNamespace(content=[SimpleNamespace(type="text", text="<think>plan</think>A red mug.")])

    monkeypatch.delenv(ENV_PRODUCT_DESCRIPTION_MAX_TOKENS, raising=False)
    assert _request_product_description(Client, "m", "image/png", "AAAA") == "A red mug."
    assert seen["max_tokens"] == DEFAULT_PRODUCT_DESCRIPTION_MAX_TOKENS
    monkeypatch.setenv(ENV_PRODUCT_DESCRIPTION_MAX_TOKENS, "2000")
    _request_product_description(Client, "m", "image/png", "AAAA")
    assert seen["max_tokens"] == 2000
