"""Read-only inspection and grid visualization for regular sprite sheets."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont

from .errors import NotFoundError, ValidationHarnessError


def extract_character_reference_frame(
    source: str | Path,
    *,
    cell_width: int,
    cell_height: int,
    columns: int,
) -> tuple[Image.Image, dict[str, Any]]:
    """Prepare one generator-ready frame from a single PNG or regular Sheet.

    A single image must already match the project cell.  For a Sheet, the
    first non-transparent row-major cell is selected so the everyday UI does
    not ask a non-technical operator for a cell index.
    """

    path = Path(source).resolve()
    if not path.is_file():
        raise NotFoundError("character reference image not found", details={"path": str(path)})
    try:
        with Image.open(path) as opened:
            opened.load()
            if opened.format != "PNG":
                raise ValidationHarnessError("character reference must be a PNG")
            if "A" not in opened.getbands() and "transparency" not in opened.info:
                raise ValidationHarnessError("character reference must contain an alpha channel")
            rgba = opened.convert("RGBA")
    except ValidationHarnessError:
        raise
    except Exception as exc:
        raise ValidationHarnessError(
            "character reference cannot be decoded",
            details={"path": str(path), "error": str(exc)},
        ) from exc

    if rgba.size == (cell_width, cell_height):
        if rgba.getchannel("A").getbbox() is None:
            raise ValidationHarnessError("character reference cannot be completely transparent")
        return rgba, {
            "valid": True,
            "path": str(path),
            "kind": "single",
            "reference_index": 0,
        }

    inspection = inspect_sprite_sheet(
        path,
        cell_width=cell_width,
        cell_height=cell_height,
        columns=columns,
    )
    reference_index = next(
        index for index, bounds in enumerate(inspection["frame_bounds"]) if bounds is not None
    )
    left = (reference_index % columns) * cell_width
    top = (reference_index // columns) * cell_height
    reference = rgba.crop((left, top, left + cell_width, top + cell_height))
    return reference, {
        "valid": True,
        "path": str(path),
        "kind": "sheet",
        "reference_index": reference_index,
        "sheet_width": inspection["width"],
        "sheet_height": inspection["height"],
    }


def inspect_sprite_sheet(
    source: str | Path,
    *,
    cell_width: int,
    cell_height: int,
    columns: int | None = None,
) -> dict[str, Any]:
    """Validate a transparent PNG sheet and identify its used row-major cells.

    The source is never cropped or rewritten.  Trailing transparent cells are
    excluded from ``frame_count``; transparent holes before the last used cell
    are reported so a regular-grid import can be blocked instead of silently
    changing frame indices.
    """

    path = Path(source).resolve()
    if not path.is_file():
        raise NotFoundError("sprite sheet not found", details={"path": str(path)})
    if cell_width <= 0 or cell_height <= 0:
        raise ValidationHarnessError("sprite sheet cell size must be positive")
    try:
        with Image.open(path) as opened:
            opened.load()
            if opened.format != "PNG":
                raise ValidationHarnessError("sprite sheet must be a PNG")
            if "A" not in opened.getbands() and "transparency" not in opened.info:
                raise ValidationHarnessError("sprite sheet must contain an alpha channel")
            image = opened.convert("RGBA")
    except ValidationHarnessError:
        raise
    except Exception as exc:
        raise ValidationHarnessError(
            "sprite sheet cannot be decoded",
            details={"path": str(path), "error": str(exc)},
        ) from exc

    if image.width % cell_width or image.height % cell_height:
        raise ValidationHarnessError(
            "sprite sheet dimensions must be exact multiples of the cell size",
            details={"actual": [image.width, image.height], "cell_size": [cell_width, cell_height]},
        )
    physical_columns = image.width // cell_width
    rows = image.height // cell_height
    if columns is not None and physical_columns != columns:
        raise ValidationHarnessError(
            "sprite sheet has the wrong number of columns",
            details={"actual": physical_columns, "expected": columns},
        )

    used: list[bool] = []
    bounds: list[list[int] | None] = []
    alpha = image.getchannel("A")
    for index in range(physical_columns * rows):
        x = (index % physical_columns) * cell_width
        y = (index // physical_columns) * cell_height
        box = alpha.crop((x, y, x + cell_width, y + cell_height)).getbbox()
        used.append(box is not None)
        bounds.append(list(box) if box is not None else None)
    frame_count = max((index + 1 for index, present in enumerate(used) if present), default=0)
    if frame_count == 0:
        raise ValidationHarnessError("sprite sheet does not contain any visible frames")
    gaps = [index for index in range(frame_count) if not used[index]]

    return {
        "path": str(path),
        "width": image.width,
        "height": image.height,
        "cell_width": cell_width,
        "cell_height": cell_height,
        "columns": physical_columns,
        "rows": rows,
        "physical_cells": physical_columns * rows,
        "frame_count": frame_count,
        "trailing_empty_cells": physical_columns * rows - frame_count,
        "empty_cells_before_last_frame": gaps,
        "frame_bounds": bounds[:frame_count],
        "cell_bounds": bounds,
        "has_regular_order": not gaps,
    }


def build_grid_overlay(
    source: str | Path,
    inspection: dict[str, Any],
    *,
    scale: int = 1,
    frame_cells: list[tuple[int, int]] | tuple[tuple[int, int], ...] | None = None,
) -> Image.Image:
    """Return a checkerboard-backed grid preview without mutating the source.

    When ``frame_cells`` is supplied, labels show playback frame numbers rather
    than physical row-major indices. This makes sparse project sheets readable.
    """

    if scale < 1:
        raise ValueError("scale must be positive")
    with Image.open(Path(source)) as opened:
        rgba = opened.convert("RGBA")
    if scale != 1:
        resampling = getattr(Image, "Resampling", Image)
        rgba = rgba.resize((rgba.width * scale, rgba.height * scale), resampling.NEAREST)
    board = _checkerboard(rgba.size, max(8, 8 * scale))
    board.alpha_composite(rgba)
    draw = ImageDraw.Draw(board)
    font = ImageFont.load_default()
    cell_width = int(inspection["cell_width"]) * scale
    cell_height = int(inspection["cell_height"]) * scale
    columns = int(inspection["columns"])
    rows = int(inspection["rows"])
    frame_count = int(inspection["frame_count"])
    playback_index = {
        (int(column), int(row)): index
        for index, (column, row) in enumerate(frame_cells or ())
    }
    line = (99, 231, 205, 255)
    for x in range(0, board.width + 1, cell_width):
        draw.line((min(x, board.width - 1), 0, min(x, board.width - 1), board.height - 1), fill=line, width=max(1, scale))
    for y in range(0, board.height + 1, cell_height):
        draw.line((0, min(y, board.height - 1), board.width - 1, min(y, board.height - 1)), fill=line, width=max(1, scale))
    for index in range(columns * rows):
        column, row = index % columns, index // columns
        x = column * cell_width + 5 * scale
        y = row * cell_height + 4 * scale
        if frame_cells is not None:
            sequence_index = playback_index.get((column, row))
            label = f"F{sequence_index + 1}" if sequence_index is not None else "empty"
        else:
            label = f"{index + 1}" if index < frame_count else "empty"
        draw.rectangle((x - 2, y - 2, x + 7 * len(label), y + 10), fill=(15, 18, 27, 210))
        draw.text((x, y), label, fill=(245, 248, 255, 255), font=font)
    return board


def _checkerboard(size: tuple[int, int], square: int) -> Image.Image:
    canvas = Image.new("RGBA", size, (194, 198, 208, 255))
    draw = ImageDraw.Draw(canvas)
    alternate = (229, 232, 239, 255)
    for y in range(0, size[1], square):
        for x in range(0, size[0], square):
            if (x // square + y // square) % 2:
                draw.rectangle((x, y, min(x + square - 1, size[0] - 1), min(y + square - 1, size[1] - 1)), fill=alternate)
    return canvas
