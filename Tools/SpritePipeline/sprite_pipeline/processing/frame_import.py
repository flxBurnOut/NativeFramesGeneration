"""Deterministic frame import from PNG sequences, GIFs, and sprite sheets."""

from __future__ import annotations

import os
import re
from pathlib import Path

from PIL import Image

from ._common import (
    SOURCE_ALPHA_KEY,
    PathLike,
    atomic_save_png,
    atomic_write_json,
    ensure_output_is_distinct,
    image_source_has_alpha,
    natural_sort_key,
    sha256_file,
)
from .frame_alignment import clean_transparent_rgb


_STANDARD_FRAME = re.compile(r"^frame_\d{3,}\.png$", re.IGNORECASE)


def import_frames(
    source: PathLike,
    output_dir: PathLike,
    *,
    source_type: str | None = None,
    cell_width: int | None = None,
    cell_height: int | None = None,
    columns: int | None = None,
    frame_count: int | None = None,
    frame_cells: list[tuple[int, int]] | None = None,
    auto_detect_sheet_count: bool = False,
    clean_hidden_rgb: bool = True,
) -> dict[str, object]:
    """Import frames and save ``frame_000.png`` ... as deterministic RGBA.

    ``source`` may be a directory of PNG files, an animated GIF, or a regular
    row-major sprite sheet. The source kind is inferred from a directory/GIF;
    a PNG sheet requires ``cell_width`` and ``cell_height`` or explicit
    ``source_type="sheet"``. PNG directories use a natural filename sort, while
    GIF frames retain encoded order. Sheets use row-major order unless an exact
    playback-order ``frame_cells`` mapping is supplied.

    A ``frames_manifest.json`` sidecar records whether each original source had
    alpha. This allows QA to detect a source that was RGB before normalization.
    Rerunning removes only stale standardized ``frame_NNN.png`` outputs.

    Args:
        source: Source directory or image path.
        output_dir: Destination directory, which must differ from a PNG source
            directory so original inputs are never overwritten.
        source_type: Optional ``"directory"``, ``"gif"``, or ``"sheet"``.
        cell_width: Sheet cell width in pixels.
        cell_height: Sheet cell height in pixels.
        columns: Optional validation of the sheet's physical column count.
        frame_count: Number of row-major sheet cells to import. Omit to import
            every physical cell.
        frame_cells: Exact ``(column,row)`` cells to import in playback order.
            All other sheet cells must be transparent.
        auto_detect_sheet_count: For a sheet, import through the last cell with
            visible alpha and omit only trailing transparent padding cells.
            Internal transparent cells retain their row-major indices. This is
            mutually exclusive with an explicit ``frame_count``.
        clean_hidden_rgb: Clear RGB under fully transparent pixels when true.

    Returns:
        A JSON-serializable manifest containing paths, order, source alpha,
        dimensions, durations (for GIF), and SHA-256 values.

    Raises:
        ValueError: On an unsupported/ambiguous source or invalid sheet shape.
        OSError: When Pillow cannot decode an input image.
    """

    source_path = Path(source).expanduser()
    target_dir = Path(output_dir).expanduser()
    kind = _infer_source_type(source_path, source_type, cell_width, cell_height)

    if kind == "directory":
        if auto_detect_sheet_count:
            raise ValueError("auto_detect_sheet_count is only valid for sprite sheets.")
        if frame_cells is not None:
            raise ValueError("frame_cells is only valid for sprite sheets.")
        if source_path.resolve() == target_dir.resolve():
            raise ValueError("The output directory must differ from the source directory.")
        extracted = _read_png_directory(source_path)
    elif kind == "gif":
        if auto_detect_sheet_count:
            raise ValueError("auto_detect_sheet_count is only valid for sprite sheets.")
        if frame_cells is not None:
            raise ValueError("frame_cells is only valid for sprite sheets.")
        extracted = _read_gif(source_path)
    else:
        if cell_width is None or cell_height is None:
            raise ValueError("Sprite-sheet import requires cell_width and cell_height.")
        extracted = _read_sprite_sheet(
            source_path,
            cell_width=cell_width,
            cell_height=cell_height,
            columns=columns,
            frame_count=frame_count,
            frame_cells=frame_cells,
            auto_detect_sheet_count=auto_detect_sheet_count,
        )

    if not extracted:
        raise ValueError("The source contains no frames.")

    target_dir.mkdir(parents=True, exist_ok=True)
    if source_path.is_file():
        ensure_output_is_distinct(
            target_dir / "frame_000.png",
            [source_path],
        )
        # Check every prospective output, not only frame zero: a sheet named
        # frame_007.png in the target directory must also remain untouched.
        for index in range(1, len(extracted)):
            ensure_output_is_distinct(target_dir / f"frame_{index:03d}.png", [source_path])
    frame_records: list[dict[str, object]] = []
    expected_names: set[str] = set()
    for index, record in enumerate(extracted):
        output_name = f"frame_{index:03d}.png"
        output_path = target_dir / output_name
        frame = record.pop("image")
        if not isinstance(frame, Image.Image):
            raise TypeError("Internal frame extraction produced a non-image value.")
        rgba = clean_transparent_rgb(frame) if clean_hidden_rgb else frame.convert("RGBA")
        source_has_alpha = bool(record.get("source_has_alpha", False))
        atomic_save_png(
            rgba,
            output_path,
            text_metadata={SOURCE_ALPHA_KEY: "1" if source_has_alpha else "0"},
        )
        expected_names.add(output_name.casefold())
        frame_records.append(
            {
                "index": index,
                "output_path": str(output_path.resolve()),
                "output_name": output_name,
                "width": rgba.width,
                "height": rgba.height,
                "mode": "RGBA",
                "sha256": sha256_file(output_path),
                **record,
            }
        )

    for stale in target_dir.iterdir():
        if (
            stale.is_file()
            and _STANDARD_FRAME.fullmatch(stale.name)
            and stale.name.casefold() not in expected_names
            and (
                not source_path.is_file()
                or os.path.normcase(str(stale.resolve()))
                != os.path.normcase(str(source_path.resolve()))
            )
        ):
            stale.unlink()

    manifest: dict[str, object] = {
        "schema_version": 1,
        "source": str(source_path.resolve()),
        "source_type": kind,
        "output_dir": str(target_dir.resolve()),
        "frame_count": len(frame_records),
        "clean_hidden_rgb": clean_hidden_rgb,
        "frames": frame_records,
    }
    if kind == "sheet":
        manifest["cell_width"] = cell_width
        manifest["cell_height"] = cell_height
        manifest["columns"] = columns or extracted[0].get("sheet_columns")
        if frame_cells is not None:
            manifest["frame_cells"] = frame_cells
    manifest_path = target_dir / "frames_manifest.json"
    atomic_write_json(manifest, manifest_path)
    manifest["manifest_path"] = str(manifest_path.resolve())
    return manifest


def import_png_sequence(
    source_dir: PathLike,
    output_dir: PathLike,
    *,
    clean_hidden_rgb: bool = True,
) -> dict[str, object]:
    """Import naturally sorted direct PNG children from ``source_dir``."""

    return import_frames(
        source_dir,
        output_dir,
        source_type="directory",
        clean_hidden_rgb=clean_hidden_rgb,
    )


def import_gif(
    source_gif: PathLike,
    output_dir: PathLike,
    *,
    clean_hidden_rgb: bool = True,
) -> dict[str, object]:
    """Import an animated GIF in encoded frame order."""

    return import_frames(
        source_gif,
        output_dir,
        source_type="gif",
        clean_hidden_rgb=clean_hidden_rgb,
    )


def import_sprite_sheet(
    source_sheet: PathLike,
    output_dir: PathLike,
    *,
    cell_width: int,
    cell_height: int,
    columns: int | None = None,
    frame_count: int | None = None,
    frame_cells: list[tuple[int, int]] | None = None,
    auto_detect_sheet_count: bool = False,
    clean_hidden_rgb: bool = True,
) -> dict[str, object]:
    """Import a regular row-major sprite sheet using exact cell dimensions."""

    return import_frames(
        source_sheet,
        output_dir,
        source_type="sheet",
        cell_width=cell_width,
        cell_height=cell_height,
        columns=columns,
        frame_count=frame_count,
        frame_cells=frame_cells,
        auto_detect_sheet_count=auto_detect_sheet_count,
        clean_hidden_rgb=clean_hidden_rgb,
    )


def ingest_frames(
    source: PathLike,
    output_dir: PathLike,
    cell_width: int,
    cell_height: int,
    expected_count: int | None,
    source_kind: str = "auto",
    columns: int | None = None,
    frame_cells: list[tuple[int, int]] | None = None,
    auto_detect_sheet_count: bool = False,
) -> list[Path]:
    """Stable harness wrapper that imports and returns ordered output paths.

    ``source_kind`` accepts ``auto``, ``png_dir``/``directory``, ``gif``, or
    ``sheet``. ``expected_count`` selects the used cells for a sheet unless
    ``auto_detect_sheet_count`` is enabled; directory and GIF sources retain
    every decoded frame.

    The returned :class:`~pathlib.Path` objects point to normalized RGBA files.
    API callers should stringify them when serializing their own response.
    """

    if cell_width <= 0 or cell_height <= 0:
        raise ValueError("cell_width and cell_height must be positive.")
    if expected_count is not None and expected_count < 1:
        raise ValueError("expected_count must be positive.")
    normalized_kind = source_kind.strip().casefold()
    if normalized_kind == "auto":
        selected_kind: str | None = None
    else:
        aliases = {
            "png_dir": "directory",
            "png": "directory",
            "png_sequence": "directory",
            "sequence": "directory",
            "spritesheet": "sheet",
            "sprite_sheet": "sheet",
        }
        selected_kind = aliases.get(normalized_kind, normalized_kind)
    source_path = Path(source).expanduser()
    is_sheet = selected_kind == "sheet" or (
        selected_kind is None
        and not source_path.is_dir()
        and source_path.suffix.casefold() != ".gif"
    )
    if auto_detect_sheet_count and not is_sheet:
        raise ValueError("auto_detect_sheet_count is only valid for sprite sheets.")
    sheet_frame_count = None
    if is_sheet and not auto_detect_sheet_count:
        sheet_frame_count = expected_count
    result = import_frames(
        source,
        output_dir,
        source_type=selected_kind,
        cell_width=cell_width,
        cell_height=cell_height,
        columns=columns,
        frame_count=sheet_frame_count,
        frame_cells=frame_cells,
        auto_detect_sheet_count=auto_detect_sheet_count,
    )
    records = result.get("frames", [])
    if not isinstance(records, list):
        raise TypeError("Import manifest did not contain a frame list.")
    return [Path(str(record["output_path"])) for record in records]


def _infer_source_type(
    source: Path,
    source_type: str | None,
    cell_width: int | None,
    cell_height: int | None,
) -> str:
    if source_type is not None:
        normalized = source_type.strip().casefold()
        aliases = {"png": "directory", "sequence": "directory", "spritesheet": "sheet"}
        normalized = aliases.get(normalized, normalized)
        if normalized not in {"directory", "gif", "sheet"}:
            raise ValueError(f"Unsupported source_type: {source_type!r}")
        return normalized
    if source.is_dir():
        return "directory"
    if source.suffix.casefold() == ".gif":
        return "gif"
    if cell_width is not None and cell_height is not None:
        return "sheet"
    raise ValueError(
        "Cannot infer source type. A PNG sheet requires cell_width and cell_height."
    )


def _read_png_directory(source_dir: Path) -> list[dict[str, object]]:
    if not source_dir.is_dir():
        raise ValueError(f"PNG sequence directory does not exist: {source_dir}")
    sources = sorted(
        (
            child
            for child in source_dir.iterdir()
            if child.is_file() and child.suffix.casefold() == ".png"
        ),
        key=natural_sort_key,
    )
    if not sources:
        raise ValueError(f"No PNG files found in: {source_dir}")
    records: list[dict[str, object]] = []
    for source_index, path in enumerate(sources):
        with Image.open(path) as opened:
            if opened.format != "PNG":
                raise ValueError(f"Expected a PNG file, got {opened.format!r}: {path}")
            if int(getattr(opened, "n_frames", 1)) != 1:
                raise ValueError(f"Animated PNG is not a sequence frame: {path}")
            has_alpha = image_source_has_alpha(opened)
            original_mode = opened.mode
            opened.load()
            frame = opened.convert("RGBA").copy()
        records.append(
            {
                "image": frame,
                "source_index": source_index,
                "source_path": str(path.resolve()),
                "source_name": path.name,
                "source_mode": original_mode,
                "source_has_alpha": has_alpha,
                "source_sha256": sha256_file(path),
            }
        )
    return records


def _read_gif(source_gif: Path) -> list[dict[str, object]]:
    if not source_gif.is_file():
        raise ValueError(f"GIF does not exist: {source_gif}")
    records: list[dict[str, object]] = []
    with Image.open(source_gif) as opened:
        if opened.format != "GIF":
            raise ValueError(f"Expected a GIF file, got {opened.format!r}: {source_gif}")
        container_has_alpha = image_source_has_alpha(opened)
        frame_total = int(getattr(opened, "n_frames", 1))
        for index in range(frame_total):
            opened.seek(index)
            has_alpha = container_has_alpha or image_source_has_alpha(opened)
            original_mode = opened.mode
            duration_ms = int(opened.info.get("duration", 0) or 0)
            frame = opened.convert("RGBA").copy()
            records.append(
                {
                    "image": frame,
                    "source_index": index,
                    "source_path": str(source_gif.resolve()),
                    "source_name": source_gif.name,
                    "source_mode": original_mode,
                    "source_has_alpha": has_alpha,
                    "duration_ms": duration_ms,
                }
            )
    source_digest = sha256_file(source_gif)
    for record in records:
        record["source_sha256"] = source_digest
    return records


def _read_sprite_sheet(
    source_sheet: Path,
    *,
    cell_width: int,
    cell_height: int,
    columns: int | None,
    frame_count: int | None,
    frame_cells: list[tuple[int, int]] | None,
    auto_detect_sheet_count: bool,
) -> list[dict[str, object]]:
    if cell_width <= 0 or cell_height <= 0:
        raise ValueError("cell_width and cell_height must be positive.")
    if not source_sheet.is_file():
        raise ValueError(f"Sprite sheet does not exist: {source_sheet}")
    with Image.open(source_sheet) as opened:
        if opened.format != "PNG":
            raise ValueError(
                f"Expected a PNG sprite sheet, got {opened.format!r}: {source_sheet}"
            )
        if int(getattr(opened, "n_frames", 1)) != 1:
            raise ValueError(f"Animated PNG cannot be used as a sprite sheet: {source_sheet}")
        has_alpha = image_source_has_alpha(opened)
        original_mode = opened.mode
        opened.load()
        width, height = opened.size
        sheet = opened.convert("RGBA").copy()
    if width % cell_width or height % cell_height:
        raise ValueError(
            f"Sheet size {width}x{height} is not divisible by cell size "
            f"{cell_width}x{cell_height}."
        )
    physical_columns = width // cell_width
    rows = height // cell_height
    if columns is not None and columns != physical_columns:
        raise ValueError(
            f"columns={columns} does not match physical sheet columns={physical_columns}."
        )
    total = physical_columns * rows
    cells = list(frame_cells) if frame_cells is not None else None
    if cells is not None:
        if auto_detect_sheet_count:
            raise ValueError("frame_cells cannot be combined with auto_detect_sheet_count.")
        if frame_count is not None and frame_count != len(cells):
            raise ValueError("frame_count must match the number of frame_cells.")
        if not cells:
            raise ValueError("frame_cells cannot be empty.")
        if len(set(cells)) != len(cells):
            raise ValueError("frame_cells cannot contain duplicate cells.")
        if any(
            column < 0 or row < 0 or column >= physical_columns or row >= rows
            for column, row in cells
        ):
            raise ValueError("frame_cells contains a cell outside the physical sheet.")
        selected_cells = cells
        count = len(cells)
    elif auto_detect_sheet_count and frame_count is not None:
        raise ValueError("auto_detect_sheet_count cannot be combined with frame_count.")
    elif auto_detect_sheet_count:
        alpha = sheet.getchannel("A")
        count = 0
        for index in range(total - 1, -1, -1):
            column = index % physical_columns
            row = index // physical_columns
            left = column * cell_width
            top = row * cell_height
            cell_alpha = alpha.crop((left, top, left + cell_width, top + cell_height))
            if cell_alpha.getbbox() is not None:
                count = index + 1
                break
        if count == 0:
            raise ValueError("Sprite sheet does not contain any visible frames.")
    else:
        count = total if frame_count is None else frame_count
    if count < 1 or count > total:
        raise ValueError(f"frame_count must be between 1 and {total}, got {count}.")

    if cells is None:
        selected_cells = [
            (index % physical_columns, index // physical_columns)
            for index in range(count)
        ]
    selected_set = set(selected_cells)
    for unused_row in range(rows):
        for unused_column in range(physical_columns):
            if (unused_column, unused_row) in selected_set:
                continue
            left = unused_column * cell_width
            top = unused_row * cell_height
            unused = sheet.crop((left, top, left + cell_width, top + cell_height))
            if unused.getchannel("A").getbbox() is not None:
                raise ValueError(
                    "Unused sprite-sheet cell contains non-transparent pixels at "
                    f"row={unused_row}, column={unused_column}; frame_count may be wrong."
                )

    digest = sha256_file(source_sheet)
    records: list[dict[str, object]] = []
    for index, (column, row) in enumerate(selected_cells):
        left = column * cell_width
        top = row * cell_height
        frame = sheet.crop((left, top, left + cell_width, top + cell_height))
        records.append(
            {
                "image": frame,
                "source_index": row * physical_columns + column,
                "sequence_index": index,
                "source_path": str(source_sheet.resolve()),
                "source_name": source_sheet.name,
                "source_mode": original_mode,
                "source_has_alpha": has_alpha,
                "source_sha256": digest,
                "sheet_column": column,
                "sheet_row": row,
                "sheet_columns": physical_columns,
            }
        )
    return records
