"""Deterministic sprite-sheet construction."""

from __future__ import annotations

import math
from collections.abc import Iterable

from PIL import Image

from ._common import (
    PathLike,
    atomic_save_png,
    ensure_output_is_distinct,
    resolve_frame_paths,
    sha256_file,
)
from .frame_alignment import clean_transparent_rgb


def build_sprite_sheet(
    frames: PathLike | Iterable[PathLike],
    output_path: PathLike,
    columns: int | None = None,
    *,
    clean_hidden_rgb: bool = True,
) -> dict[str, object]:
    """Arrange same-sized PNG frames in deterministic row-major order.

    ``frames`` may be a directory or an explicitly ordered iterable. Directory
    inputs use natural filename ordering. Empty trailing cells in the final row
    are transparent. No frame is cropped, aligned, rescaled, or recoloured.

    Args:
        frames: Frame directory, single file, or ordered paths.
        output_path: Destination PNG.
        columns: Number of sheet columns. Defaults to one row.
        clean_hidden_rgb: Clear RGB where alpha is zero before placement.

    Returns:
        JSON-serializable dimensions, ordering, path, and SHA-256 metadata.

    Raises:
        ValueError: If there are no frames, sizes differ, or columns are invalid.
    """

    paths = resolve_frame_paths(frames)
    ensure_output_is_distinct(output_path, paths)
    if columns is None:
        columns = len(paths)
    if columns < 1:
        raise ValueError("columns must be at least 1.")

    loaded: list[Image.Image] = []
    frame_size: tuple[int, int] | None = None
    for path in paths:
        with Image.open(path) as opened:
            opened.load()
            frame = opened.convert("RGBA").copy()
        if clean_hidden_rgb:
            frame = clean_transparent_rgb(frame)
        if frame_size is None:
            frame_size = frame.size
        elif frame.size != frame_size:
            raise ValueError(
                f"Frame {path} has size {frame.size}; expected {frame_size}."
            )
        loaded.append(frame)

    assert frame_size is not None
    rows = math.ceil(len(loaded) / columns)
    sheet = Image.new(
        "RGBA", (frame_size[0] * columns, frame_size[1] * rows), (0, 0, 0, 0)
    )
    for index, frame in enumerate(loaded):
        x = (index % columns) * frame_size[0]
        y = (index // columns) * frame_size[1]
        sheet.alpha_composite(frame, (x, y))

    target = atomic_save_png(sheet, output_path)
    return {
        "schema_version": 1,
        "output_path": str(target.resolve()),
        "sha256": sha256_file(target),
        "frame_count": len(loaded),
        "frame_width": frame_size[0],
        "frame_height": frame_size[1],
        "columns": columns,
        "rows": rows,
        "sheet_width": sheet.width,
        "sheet_height": sheet.height,
        "frame_order": [str(path.resolve()) for path in paths],
    }


export_sprite_sheet = build_sprite_sheet
