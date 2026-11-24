"""Optional LFM3-Audio-2B ASR from a trusted, pre-staged model snapshot."""

import os
import tempfile
from pathlib import Path

from .._install_hints import pip_install_hint
from ..errors import MCPVideoError
from ..offline import OfflineModelMissing
from .transcribe import _extract_audio_segment

MODEL_NAME = "LFM3-Audio-2B"
ENV_MODEL_DIR = "KINOCUT_LFM3_AUDIO_DIR"
DEPENDENCIES = ("transformers", "torch", "accelerate", "librosa", "soundfile", "safetensors")
_REQUIRED_FILES = (
    "model.safetensors",
    "config.json",
    "processor_config.json",
    "tokenizer.json",
    "audio_tokenizer/model.safetensors",
    "audio_tokenizer/config.json",
)
_CHUNK_SECONDS = 30
_LANGUAGES = dict(
    zip(
        ["ar", "da", "de", "el", "en", "fi", "fr", "he", "it", "ja", "ko", "nl", "pl", "pt", "es", "sv", "tr", "zh"],
        [
            "Arabic",
            "Danish",
            "German",
            "Greek",
            "English",
            "Finnish",
            "French",
            "Hebrew",
            "Italian",
            "Japanese",
            "Korean",
            "Dutch",
            "Polish",
            "Portuguese",
            "Spanish",
            "Swedish",
            "Turkish",
            "Chinese",
        ],
        strict=True,
    )
)


def snapshot_files(directory: Path) -> tuple[Path, ...]:
    return tuple(directory / name for name in _REQUIRED_FILES)


def _model_directory() -> Path:
    raw = os.environ.get(ENV_MODEL_DIR, "").strip()
    if not raw:
        raise MCPVideoError(
            f"Set {ENV_MODEL_DIR} to a local {MODEL_NAME} snapshot containing model.safetensors.",
            error_type="configuration_error",
            code="lfm3_audio_dir_missing",
        )
    directory = Path(raw).expanduser().absolute()
    for path in snapshot_files(directory):
        if not path.is_file():
            raise OfflineModelMissing(path, feature=MODEL_NAME, env_hint=f"Set {ENV_MODEL_DIR} to a complete snapshot.")
    return directory


def _load(directory: Path):
    try:
        import torch
        from transformers import AutoModelForMultimodalLM, AutoProcessor
    except ImportError:
        raise MCPVideoError(
            f"{MODEL_NAME} runtime is missing. Install with: {pip_install_hint('lfm3-audio')}",
            error_type="dependency_error",
            code="missing_lfm3_audio",
        ) from None
    device = "cuda" if torch.cuda.is_available() else "cpu"
    options = {"local_files_only": True, "trust_remote_code": True}
    processor = AutoProcessor.from_pretrained(str(directory), **options)
    model = AutoModelForMultimodalLM.from_pretrained(
        str(directory),
        **options,
        use_safetensors=True,
        device_map=device,
        dtype=torch.bfloat16 if device == "cuda" else torch.float32,
    ).eval()
    return torch, device, processor, model


def _recognize(runtime, audio: str, prompt: str) -> str:
    torch, device, processor, model = runtime
    inputs = processor.apply_chat_template(
        [{"role": "system", "content": prompt}, {"role": "user", "content": [{"type": "audio", "audio": audio}]}],
        add_generation_prompt=True,
        tokenize=True,
        return_dict=True,
        return_tensors="pt",
    ).to(device)
    with torch.inference_mode():
        outputs = model.generate(
            **inputs,
            max_new_tokens=1024,
            suppress_mixed=True,
            suppress_audio_out=True,
            return_dict_in_generate=True,
        )
    return processor.decode(outputs.sequences[0, inputs["input_ids"].shape[1] :], skip_special_tokens=True).strip()


def transcribe_video(video: Path, duration: float, language: str | None) -> dict:
    if language and language.lower() not in _LANGUAGES:
        raise MCPVideoError("Unsupported LFM3-Audio language code", code="invalid_parameter")
    prompt = f"Perform ASR in {_LANGUAGES[language.lower()]}." if language else "Perform ASR."
    runtime = _load(_model_directory())
    segments = []
    with tempfile.TemporaryDirectory(prefix="kc_lfm3_") as work_dir:
        start = 0.0
        while start < duration:
            end = min(start + _CHUNK_SECONDS, duration)
            wav = _extract_audio_segment(str(video), start, end - start, output_dir=work_dir)
            try:
                text = _recognize(runtime, wav, prompt)
            finally:
                Path(wav).unlink(missing_ok=True)
            if text:
                segments.append({"start": start, "end": end, "text": text})
            start = end
    return {
        "transcript": " ".join(segment["text"] for segment in segments),
        "segments": segments,
        "language": language or "unknown",
    }
