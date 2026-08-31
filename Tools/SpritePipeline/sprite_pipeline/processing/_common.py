"""Internal path and serialization helpers for the processing package.

The helpers deliberately avoid locale-dependent behaviour so paths containing
Chinese characters work the same way as ASCII-only paths on Windows.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

from PIL import Image, PngImagePlugin


PathLike = str | os.PathLike[str]
SOURCE_ALPHA_KEY = "sprite_pipeline_source_has_alpha"
_NUMBER_PART = re.compile(r"(\d+)")


def natural_sort_key(path: Path) -> tuple[tuple[tuple[int, int | str], ...], str]:
    """Return a stable, case-insensitive natural-sort key for a path."""

    parts: list[tuple[int, int | str]] = []
    for part in _NUMBER_PART.split(path.name.casefold()):
        if part.isdigit():
            parts.append((0, int(part)))
        else:
            parts.append((1, part))
    return tuple(parts), path.name


def resolve_frame_paths(
    frames: PathLike | Iterable[PathLike], *, allow_empty: bool = False
) -> list[Path]:
    """Normalize a frame directory, one file, or an iterable into sorted paths.

    Directories are intentionally non-recursive and only direct ``.png``
    children are considered. Iterables retain their supplied order; callers can
    therefore express a frame order that differs from filename order.
    """

    if isinstance(frames, (str, os.PathLike)):
        value = Path(frames).expanduser()
        if value.is_dir():
            paths = sorted(
                (
                    child
                    for child in value.iterdir()
                    if child.is_file() and child.suffix.casefold() == ".png"
                ),
                key=natural_sort_key,
            )
        else:
            paths = [value]
    else:
        paths = [Path(item).expanduser() for item in frames]

    if not paths and not allow_empty:
        raise ValueError("No PNG frames were found.")
    return paths


def image_has_alpha(image: Image.Image) -> bool:
    """Return whether an image source actually carries alpha/transparency."""

    return "A" in image.getbands() or "transparency" in image.info


def image_source_has_alpha(image: Image.Image) -> bool:
    """Return persisted source-alpha provenance, falling back to image bands."""

    provenance = image.info.get(SOURCE_ALPHA_KEY)
    if provenance is None:
        return image_has_alpha(image)
    if isinstance(provenance, str):
        normalized = provenance.strip().casefold()
        if normalized in {"0", "false", "no"}:
            return False
        if normalized in {"1", "true", "yes"}:
            return True
    return bool(provenance)


def sha256_file(path: PathLike) -> str:
    """Return the SHA-256 digest of a file without assuming an ASCII path."""

    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def ensure_output_is_distinct(output: PathLike, inputs: Iterable[PathLike]) -> None:
    """Reject an output path that would overwrite one of its source files."""

    target = os.path.normcase(str(Path(output).expanduser().resolve()))
    for source in inputs:
        source_path = os.path.normcase(str(Path(source).expanduser().resolve()))
        if target == source_path:
            raise ValueError(f"Output path would overwrite source file: {source}")


def atomic_save_png(
    image: Image.Image,
    destination: PathLike,
    *,
    text_metadata: Mapping[str, str] | None = None,
) -> Path:
    """Save a PNG via an adjacent temporary file and atomically replace it.

    Optional text metadata is emitted in sorted order to keep output bytes
    stable. Normalized frames use it for provenance; final sheet exports omit it.
    """

    target = Path(destination).expanduser()
    target.parent.mkdir(parents=True, exist_ok=True)
    handle = tempfile.NamedTemporaryFile(
        prefix=f".{target.name}.", suffix=".tmp", dir=target.parent, delete=False
    )
    temporary = Path(handle.name)
    handle.close()
    try:
        png_info = None
        if text_metadata:
            png_info = PngImagePlugin.PngInfo()
            for key, value in sorted(text_metadata.items()):
                png_info.add_text(key, value)
        image.save(
            temporary,
            format="PNG",
            optimize=False,
            compress_level=9,
            pnginfo=png_info,
        )
        os.replace(temporary, target)
    finally:
        if temporary.exists():
            temporary.unlink()
    return target


def atomic_write_json(payload: Any, destination: PathLike) -> Path:
    """Write deterministic UTF-8 JSON and atomically replace the destination."""

    target = Path(destination).expanduser()
    target.parent.mkdir(parents=True, exist_ok=True)
    handle = tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        newline="\n",
        prefix=f".{target.name}.",
        suffix=".tmp",
        dir=target.parent,
        delete=False,
    )
    temporary = Path(handle.name)
    try:
        with handle:
            json.dump(
                payload,
                handle,
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
            handle.write("\n")
        os.replace(temporary, target)
    finally:
        if temporary.exists():
            temporary.unlink()
    return target
