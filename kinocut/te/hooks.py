"""Thumbnail + hook-title candidates — human picks (TE.2)."""

from __future__ import annotations

from typing import Any

from kinocut.errors import MCPVideoError


def generate_hook_candidates(
    topic: str,
    *,
    count: int = 5,
    language: str = "en",
) -> dict[str, Any]:
    if not (topic or "").strip():
        raise MCPVideoError("topic required", error_type="validation_error", code="topic_required")
    n = max(1, min(int(count), 12))
    lang = (language or "en").lower()
    templates_en = [
        "I was wrong about {t}",
        "Stop doing {t} like this",
        "The {t} trick nobody shows",
        "{t} in 30 seconds",
        "What {t} looks like when it works",
        "Before you ship {t}, watch this",
    ]
    templates_es = [
        "Me equivoqué con {t}",
        "Deja de hacer {t} así",
        "El truco de {t} que nadie muestra",
        "{t} en 30 segundos",
        "Así se ve {t} cuando funciona",
        "Antes de publicar {t}, mira esto",
    ]
    templates = templates_es if lang.startswith("es") else templates_en
    titles = [templates[i % len(templates)].format(t=topic.strip()) for i in range(n)]
    thumbs = [
        {
            "candidate_id": f"thumb-{i + 1:02d}",
            "title": titles[i],
            "layout": "bold_text_left" if i % 2 == 0 else "face_right_text",
            "status": "proposed",
            "apply_policy": "human_pick_required",
        }
        for i in range(n)
    ]
    return {
        "artifact_kind": "hook_candidates",
        "language": lang,
        "topic": topic.strip(),
        "titles": titles,
        "thumbnails": thumbs,
        "apply_policy": "human_pick_required",
    }
