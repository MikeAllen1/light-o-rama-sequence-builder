"""Optional on-PC vocal separation for singing faces.

Uses the ``audio-separator`` package with a UVR MDX-Net vocal model, run on the
CPU. It is an optional add-on (``uv sync --extra vocals``) because it pulls in
PyTorch. The model (about 67 MB) downloads once into the user's cache folder;
after that everything runs offline. Separation takes a few minutes per song,
so the separated vocals are saved next to the sequence and can be reused with
``--vocals``.
"""

from __future__ import annotations

import importlib.util
import logging
import os
import shutil
import tempfile
from pathlib import Path

MODEL_FILENAME = "UVR-MDX-NET-Voc_FT.onnx"


class SeparationError(RuntimeError):
    """Raised when vocals cannot be separated."""


def separation_available() -> bool:
    return importlib.util.find_spec("audio_separator") is not None


def model_folder() -> Path:
    base = os.environ.get("LOCALAPPDATA") or os.environ.get("XDG_CACHE_HOME")
    root = Path(base) if base else Path.home() / ".cache"
    return root / "lor-sequence-builder" / "models"


def separate_vocals(audio_path: str | Path, vocals_output: str | Path) -> Path:
    """Split the vocals out of a song into a new WAV file."""
    output = Path(vocals_output)
    if output.exists():
        raise SeparationError(f"Refusing to overwrite existing vocals: {output}")
    if not separation_available():
        raise SeparationError(
            "Vocal separation is an optional add-on; install it with "
            "'uv sync --extra vocals', or pass a vocals-only file with --vocals"
        )
    from audio_separator.separator import Separator

    models = model_folder()
    models.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="lor-vocals-") as folder:
        try:
            separator = Separator(
                output_dir=folder, model_file_dir=str(models), output_format="WAV",
                log_level=logging.ERROR,
            )
            separator.load_model(model_filename=MODEL_FILENAME)
            produced = separator.separate(str(Path(audio_path).resolve()))
        except Exception as exc:  # the add-on raises many kinds of errors
            raise SeparationError(f"Vocal separation failed: {exc}") from exc
        vocals = [Path(folder) / Path(name).name for name in produced
                  if "(vocals)" in Path(name).name.lower()]
        if not vocals or not vocals[0].is_file():
            raise SeparationError("Vocal separation did not produce a vocals track")
        output.parent.mkdir(parents=True, exist_ok=True)
        try:
            with vocals[0].open("rb") as source, output.open("xb") as target:
                shutil.copyfileobj(source, target)
        except OSError as exc:
            raise SeparationError(f"Cannot save separated vocals: {output}") from exc
    return output
