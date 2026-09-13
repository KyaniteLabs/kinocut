"""Standalone isolated optional-runtime worker; never import project modules here."""

import hashlib
import json
import os
from pathlib import Path
import sys
from urllib.parse import urlparse


def probe():
    import whisper

    models = {name: urlparse(whisper._MODELS[name]).path.split("/")[-2] for name in ("base", "base.en")}
    return {"available": True, "version": whisper.__version__, "models": models}


def recognize():
    import numpy as np
    import torch
    import whisper

    config = json.loads(Path("config.json").read_text())
    torch.set_num_threads(config["threads"])
    pcm = np.fromfile("source.pcm", dtype="<i2").astype(np.float32) / 32768.0
    count = round(len(pcm) * config["target_rate"] / config["source_rate"])
    if config["source_rate"] != config["target_rate"]:
        positions = np.arange(count, dtype=np.float64) * config["source_rate"] / config["target_rate"]
        pcm = np.interp(positions, np.arange(len(pcm)), pcm).astype(np.float32)
    # Explicit path is essential: named models could download a missing checkpoint.
    checkpoint = Path("checkpoint.pt").resolve(strict=True)
    with checkpoint.open("rb") as stream:
        if hashlib.file_digest(stream, "sha256").hexdigest() != config["model_digest"]:
            return {"error": "checkpoint_changed"}
    model = whisper.load_model(str(checkpoint), device="cpu")
    result = model.transcribe(pcm, language=config["language"], **config["decode"])
    payload = {
        "text": result["text"],
        "segments": [{key: item[key] for key in ("start", "end", "text")} for item in result["segments"]],
    }
    encoded = json.dumps(payload, ensure_ascii=False, allow_nan=False).encode()
    if len(encoded) > config["max_output_bytes"]:
        return {"error": "output_over_limit"}
    with Path("recognition.json").open("xb") as stream:
        stream.write(encoded)
    return {"recognized": True}


def main():
    os.chdir(Path(__file__).resolve().parent)
    for name in tuple(os.environ):
        if name.startswith("PYTHON"):
            os.environ.pop(name, None)
    try:
        result = probe() if sys.argv[1:] == ["probe"] else recognize()
    except Exception as exc:
        # Never expose model paths, source text or arbitrary dependency exceptions.
        print(json.dumps({"error": "backend_failed", "exception_type": type(exc).__name__}))
        return 1
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
