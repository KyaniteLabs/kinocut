"""NIMA aesthetic scoring for MCP Video.

Evaluates the visual beauty of video frames using NIMA (Neural Image Assessment),
a VGG16 model trained on 250K human-rated photos (AVA dataset).

Direct Python import — no HTTP bridge needed. The model loads once as a singleton.

Usage:
    from kinocut.aesthetic import NimaScorer

    scorer = NimaScorer.get()
    score = scorer.score_frame("thumb.jpg")       # → 6.28 (1-10 scale)
    scores = scorer.score_frames(["f1.jpg", ...])  # → [6.2, 5.1, ...]

Integration points:
    - engine_thumbnail.py: pick the most aesthetic frame instead of 10% timestamp
    - engine_storyboard.py: select best frame from each segment
    - visual_intelligence/reframe.py: evaluate crop candidates aesthetically
    - quality_guardrails.py: holistic quality score replacing brightness/contrast heuristics
"""

from __future__ import annotations

import os
import threading
from pathlib import Path

from ..errors import MCPVideoError

# Lazy imports — only load torch when NIMA is actually used
_torch = None
_model = None
_lock = threading.Lock()


def _ensure_torch():
    """Import torch lazily so mcp-video doesn't hard-depend on it."""
    global _torch
    if _torch is None:
        try:
            import torch
            import torch.nn as nn
            import torchvision.models as models
            from torchvision import transforms

            _torch = (torch, nn, models, transforms)
        except ImportError:
            raise ImportError("NIMA scoring requires PyTorch. Install with: pip install torch torchvision") from None
    return _torch


# Weight location — shared with nima_service.py
WEIGHTS_PATH = os.path.expanduser(
    "~/.cache/huggingface/hub/models--chaofengc--IQA-PyTorch-Weights/"
    "snapshots/0df2df423c65f6a64209309695f3845727431027/"
    "NIMA_VGG16_ava-dc4e8265.pth"
)

# Alternative locations to search
WEIGHTS_SEARCH = [
    WEIGHTS_PATH,
    str(Path(__file__).parent / "weights" / "NIMA_VGG16_ava.pth"),
    str(Path(__file__).parent / "NIMA_VGG16_ava.pth"),
]


class NimaScorer:
    """Singleton NIMA aesthetic scorer.

    Loads the VGG16 model once (first call), then serves all subsequent
    evaluations from memory. Thread-safe.

    Score scale: 1.0 (ugly) to 10.0 (beautiful), matching AVA human ratings.
    """

    _instance: NimaScorer | None = None

    @classmethod
    def get(cls) -> NimaScorer:
        """Get or create the singleton scorer."""
        if cls._instance is None:
            with _lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    def __init__(self):
        torch, nn, models, transforms = _ensure_torch()

        # Build model
        vgg = models.vgg16(weights=None)
        self._features = vgg.features
        self._avgpool = nn.AdaptiveAvgPool2d((1, 1))
        self._head = nn.Linear(512, 10)

        # Load weights
        weights_path = self._find_weights()
        state = torch.load(weights_path, map_location="cpu", weights_only=True)
        remapped = {}
        for k, v in state["params"].items():
            key = k.replace("base_model.features_", "features.").replace("classifier.2", "head")
            remapped[key] = v

        # Load with state dict mapping
        self._features.load_state_dict(
            {k.replace("features.", ""): v for k, v in remapped.items() if k.startswith("features.")}, strict=False
        )
        self._head.load_state_dict(
            {k.replace("head.", ""): v for k, v in remapped.items() if k.startswith("head.")}, strict=False
        )

        self._features.eval()
        self._head.eval()
        self._torch = torch
        self._transform = transforms.Compose(
            [
                transforms.ToTensor(),
                transforms.Normalize(mean=[0.485, 0.456, 0.406], std=[0.229, 0.224, 0.225]),
            ]
        )
        self._bins = torch.arange(1, 11, dtype=torch.float32)

    def _find_weights(self) -> str:
        for path in WEIGHTS_SEARCH:
            if os.path.isfile(path):
                return path
        raise MCPVideoError(
            f"NIMA weights not found. Download with:\n"
            f"  pip install huggingface_hub\n"
            f'  python3 -c "from huggingface_hub import hf_hub_download; '
            f"hf_hub_download('chaofengc/IQA-PyTorch-Weights', 'NIMA_VGG16_ava-dc4e8265.pth')\"\n"
            f"Expected at: {WEIGHTS_PATH}",
            error_type="configuration_error",
            code="nima_weights_missing",
        )

    def score_frame(self, frame_path: str) -> float:
        """Score a single frame. Returns 1.0-10.0."""
        from PIL import Image

        torch = self._torch
        img = Image.open(frame_path).convert("RGB").resize((224, 224))
        tensor = self._transform(img).unsqueeze(0)
        with torch.no_grad():
            logits = self._head(torch.flatten(self._avgpool(self._features(tensor)), 1))
            probs = torch.softmax(logits, dim=1)
            return (probs * self._bins).sum().item()

    def score_frames(self, frame_paths: list[str]) -> list[float]:
        """Batch score multiple frames. Faster than individual calls."""
        from PIL import Image

        torch = self._torch
        tensors = []
        for path in frame_paths:
            img = Image.open(path).convert("RGB").resize((224, 224))
            tensors.append(self._transform(img))
        batch = torch.stack(tensors)
        with torch.no_grad():
            logits = self._head(torch.flatten(self._avgpool(self._features(batch)), 1))
            probs = torch.softmax(logits, dim=1)
            return (probs * self._bins).sum(1).tolist()

    def score_pil(self, img) -> float:
        """Score a PIL Image directly (no file I/O)."""
        torch = self._torch
        tensor = self._transform(img.convert("RGB").resize((224, 224))).unsqueeze(0)
        with torch.no_grad():
            logits = self._head(torch.flatten(self._avgpool(self._features(tensor)), 1))
            probs = torch.softmax(logits, dim=1)
            return (probs * self._bins).sum().item()

    def find_best_frame(
        self,
        frame_paths: list[str],
        return_score: bool = False,
    ) -> str | tuple[str, float]:
        """Find the most aesthetic frame from a list of candidates.

        Returns the path to the best frame. If return_score, also returns the score.
        """
        if not frame_paths:
            raise MCPVideoError(
                "No frames to score",
                error_type="validation_error",
                code="invalid_parameter",
            )
        if len(frame_paths) == 1:
            score = self.score_frame(frame_paths[0])
            return (frame_paths[0], score) if return_score else frame_paths[0]
        scores = self.score_frames(frame_paths)
        best_idx = scores.index(max(scores))
        if return_score:
            return frame_paths[best_idx], scores[best_idx]
        return frame_paths[best_idx]


def is_available() -> bool:
    """Check if NIMA scoring is available (torch installed + weights present)."""
    try:
        import torch  # noqa: F401

        return any(os.path.isfile(path) for path in WEIGHTS_SEARCH)
    except ImportError:
        return False
