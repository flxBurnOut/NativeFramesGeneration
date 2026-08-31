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
    rows: int | None = None,
    frame_cells: Iterable[tuple[int, int]] | None = None,
    clean_hidden_rgb: bool = True,
) -> dict[str, object]:
    """Arrange same-sized PNG frames in a deterministic project grid.

    ``frames`` may be a directory or an explicitly ordered iterable. Directory
    inputs use natural filename ordering. By default frames use row-major order.
    ``frame_cells`` can instead map playback frame N to an exact ``(column,row)``
    project cell; every unassigned cell remains transparent. No frame is cropped,
    aligned, rescaled, or recoloured.

    Args:
        frames: Frame directory, single file, or ordered paths.
        output_path: Destination PNG.
        columns: Number of sheet columns. Defaults to one row.
        rows: Optional fixed row count. Required project padding remains clear.
        frame_cells: Optional cell for every playback frame, in playback order.
        clean_hidden_rgb: Clear RGB where alpha is zero before placement.

    Returns:
        JSON-serializable dimensions, ordering, path, and SHA-256 metadata.

    Raises:
        ValueError: If there are no frames, sizes differ, or columns are invalid.
    """

    paths = resolve_frame_paths(frames)
    ensure_output_is_distinct(output_path, paths)
    cells = list(frame_cells) if frame_cells is not None else None
    if cells is not None:
        if len(cells) != len(paths):
            raise ValueError("frame_cells must contain one cell for every frame.")
        if len(set(cells)) != len(cells):
            raise ValueError("frame_cells cannot contain duplicate cells.")
        if any(column < 0 or row < 0 for column, row in cells):
            raise ValueError("frame_cells coordinates cannot be negative.")
    if columns is None:
        columns = max((column for column, _row in cells), default=-1) + 1 if cells is not None else len(paths)
    if columns < 1:
        raise ValueError("columns must be at least 1.")
    if rows is None:
        rows = (
            max((row for _column, row in cells), default=-1) + 1
            if cells is not None
            else math.ceil(len(paths) / columns)
        )
    if rows < 1:
        raise ValueError("rows must be at least 1.")
    if cells is not None:
        if any(column >= columns or row >= rows for column, row in cells):
            raise ValueError("frame_cells contains a cell outside the requested sheet shape.")
    elif len(paths) > columns * rows:
        raise ValueError("the requested sheet shape does not contain every frame.")

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
    sheet = Image.new(
        "RGBA", (frame_size[0] * columns, frame_size[1] * rows), (0, 0, 0, 0)
    )
    for index, frame in enumerate(loaded):
        column, row = cells[index] if cells is not None else (index % columns, index // columns)
        x = column * frame_size[0]
        y = row * frame_size[1]
        sheet.alpha_composite(frame, (x, y))

    placed_cells = cells or [(index % columns, index // columns) for index in range(len(loaded))]
    used_cells = set(placed_cells)
    unused_cells = [
        (column, row)
        for row in range(rows)
        for column in range(columns)
        if (column, row) not in used_cells
    ]

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
        "frame_cells": placed_cells,
        "unused_cells": unused_cells,
    }


export_sprite_sheet = build_sprite_sheet
