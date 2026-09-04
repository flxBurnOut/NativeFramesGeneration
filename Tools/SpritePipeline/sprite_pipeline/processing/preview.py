"""GIF and PNG review-preview generation for pixel-art frame sequences."""

from __future__ import annotations

import math
import os
import tempfile
from collections.abc import Iterable
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from ._common import (
    PathLike,
    atomic_save_png,
    ensure_output_is_distinct,
    resolve_frame_paths,
    sha256_file,
)
from .frame_alignment import clean_transparent_rgb


_RESAMPLING = getattr(Image, "Resampling", Image)
_DITHER = getattr(Image, "Dither", Image)
_QUANTIZE = getattr(Image, "Quantize", Image)


def build_gif(
    frames: PathLike | Iterable[PathLike],
    output_path: PathLike,
    fps: float = 12.0,
    scale: int = 1,
    *,
    loop: bool = True,
) -> dict[str, object]:
    """Build an original-size or nearest-neighbour enlarged animated GIF.

    A shared deterministic 255-colour palette is calculated for all frames;
    palette index 255 is reserved for binary GIF transparency. Alpha values
    greater than zero remain visible because GIF has no partial-alpha support.
    """

    if fps <= 0:
        raise ValueError("fps must be greater than zero.")
    if not isinstance(scale, int) or scale < 1:
        raise ValueError("scale must be a positive integer.")
    paths, loaded = _load_same_size_frames(frames)
    ensure_output_is_distinct(output_path, paths)
    if scale != 1:
        loaded = [
            frame.resize(
                (frame.width * scale, frame.height * scale),
                resample=_RESAMPLING.NEAREST,
            )
            for frame in loaded
        ]
    indexed = _to_shared_palette(loaded)
    requested_duration_ms = 1000.0 / fps
    # GIF stores delays in 10 ms centiseconds. Pillow truncates non-multiples,
    # so quantize explicitly and report the duration actually encoded.
    duration_ms = max(10, int(requested_duration_ms // 10) * 10)
    target = Path(output_path).expanduser()
    target.parent.mkdir(parents=True, exist_ok=True)
    handle = tempfile.NamedTemporaryFile(
        prefix=f".{target.name}.", suffix=".tmp", dir=target.parent, delete=False
    )
    temporary = Path(handle.name)
    handle.close()
    save_options: dict[str, object] = {
        "format": "GIF",
        "save_all": True,
        "append_images": indexed[1:],
        "duration": duration_ms,
        "disposal": 2,
        "transparency": 255,
        "optimize": False,
    }
    if loop:
        save_options["loop"] = 0
    try:
        indexed[0].save(temporary, **save_options)
        os.replace(temporary, target)
    finally:
        if temporary.exists():
            temporary.unlink()
    return {
        "schema_version": 1,
        "output_path": str(target.resolve()),
        "sha256": sha256_file(target),
        "frame_count": len(indexed),
        "width": indexed[0].width,
        "height": indexed[0].height,
        "fps": fps,
        "effective_fps": round(1000.0 / duration_ms, 6),
        "requested_duration_ms": round(requested_duration_ms, 6),
        "duration_ms": duration_ms,
        "scale": scale,
        "loop": loop,
        "frame_order": [str(path.resolve()) for path in paths],
    }


def build_frame_grid(
    frames: PathLike | Iterable[PathLike],
    output_path: PathLike,
    *,
    scale: int = 4,
    columns: int | None = None,
    padding: int = 8,
    checker_size: int = 8,
) -> dict[str, object]:
    """Build an indexed, checkerboard-backed grid of enlarged frames."""

    if not isinstance(scale, int) or scale < 1:
        raise ValueError("scale must be a positive integer.")
    if padding < 0 or checker_size < 1:
        raise ValueError("padding must be non-negative and checker_size positive.")
    paths, loaded = _load_same_size_frames(frames)
    ensure_output_is_distinct(output_path, paths)
    columns = columns or math.ceil(math.sqrt(len(loaded)))
    if columns < 1:
        raise ValueError("columns must be at least 1.")
    rows = math.ceil(len(loaded) / columns)
    frame_width = loaded[0].width * scale
    frame_height = loaded[0].height * scale
    label_height = 16
    cell_width = frame_width + padding * 2
    cell_height = frame_height + padding * 2 + label_height
    canvas = Image.new("RGBA", (cell_width * columns, cell_height * rows), (24, 24, 28, 255))
    draw = ImageDraw.Draw(canvas)
    font = ImageFont.load_default()

    for index, frame in enumerate(loaded):
        cell_x = (index % columns) * cell_width
        cell_y = (index // columns) * cell_height
        preview = frame.resize((frame_width, frame_height), _RESAMPLING.NEAREST)
        board = _checkerboard(preview.size, checker_size)
        board.alpha_composite(preview)
        canvas.alpha_composite(board, (cell_x + padding, cell_y + padding + label_height))
        draw.text(
            (cell_x + padding, cell_y + padding),
            f"frame_{index:03d}",
            fill=(240, 240, 244, 255),
            font=font,
        )

    target = atomic_save_png(canvas, output_path)
    return {
        "schema_version": 1,
        "output_path": str(target.resolve()),
        "sha256": sha256_file(target),
        "frame_count": len(loaded),
        "columns": columns,
        "rows": rows,
        "scale": scale,
        "width": canvas.width,
        "height": canvas.height,
        "frame_order": [str(path.resolve()) for path in paths],
    }


def build_first_frame_overlay(
    frames: PathLike | Iterable[PathLike],
    output_path: PathLike,
    *,
    scale: int = 4,
    columns: int | None = None,
    base_opacity: float = 0.45,
    current_opacity: float = 0.70,
    padding: int = 8,
    checker_size: int = 8,
) -> dict[str, object]:
    """Overlay frame zero with every frame and arrange comparisons in a grid.

    Frame zero is drawn first at ``base_opacity`` and each comparison frame is
    drawn above it at ``current_opacity``. The operation is preview-only and
    never modifies an approved/source frame.
    """

    if not isinstance(scale, int) or scale < 1:
        raise ValueError("scale must be a positive integer.")
    if not 0.0 <= base_opacity <= 1.0 or not 0.0 <= current_opacity <= 1.0:
        raise ValueError("Overlay opacities must be between 0 and 1.")
    paths, loaded = _load_same_size_frames(frames)
    ensure_output_is_distinct(output_path, paths)
    columns = columns or math.ceil(math.sqrt(len(loaded)))
    if columns < 1:
        raise ValueError("columns must be at least 1.")
    rows = math.ceil(len(loaded) / columns)
    preview_size = (loaded[0].width * scale, loaded[0].height * scale)
    label_height = 16
    cell_width = preview_size[0] + padding * 2
    cell_height = preview_size[1] + padding * 2 + label_height
    canvas = Image.new("RGBA", (cell_width * columns, cell_height * rows), (24, 24, 28, 255))
    draw = ImageDraw.Draw(canvas)
    font = ImageFont.load_default()
    base = loaded[0].resize(preview_size, _RESAMPLING.NEAREST)

    for index, frame in enumerate(loaded):
        cell_x = (index % columns) * cell_width
        cell_y = (index // columns) * cell_height
        current = frame.resize(preview_size, _RESAMPLING.NEAREST)
        board = _checkerboard(preview_size, checker_size)
        board.alpha_composite(_with_opacity(base, base_opacity))
        board.alpha_composite(_with_opacity(current, current_opacity))
        canvas.alpha_composite(board, (cell_x + padding, cell_y + padding + label_height))
        draw.text(
            (cell_x + padding, cell_y + padding),
            f"000 / {index:03d}",
            fill=(240, 240, 244, 255),
            font=font,
        )

    target = atomic_save_png(canvas, output_path)
    return {
        "schema_version": 1,
        "output_path": str(target.resolve()),
        "sha256": sha256_file(target),
        "frame_count": len(loaded),
        "columns": columns,
        "rows": rows,
        "scale": scale,
        "base_opacity": base_opacity,
        "current_opacity": current_opacity,
        "width": canvas.width,
        "height": canvas.height,
        "frame_order": [str(path.resolve()) for path in paths],
    }


def build_adjacent_frame_overlay(
    frames: PathLike | Iterable[PathLike],
    output_path: PathLike,
    *,
    scale: int = 4,
    columns: int | None = None,
    previous_opacity: float = 0.55,
    current_opacity: float = 0.65,
    padding: int = 8,
    checker_size: int = 8,
    loop: bool = False,
) -> dict[str, object]:
    """Overlay each frame with its immediate predecessor for continuity review.

    Previous silhouettes are magenta and current silhouettes are cyan. This
    preview makes sudden frame-to-frame position changes visible without
    cropping, translating, resizing, or otherwise modifying source frames.
    """

    if not isinstance(scale, int) or scale < 1:
        raise ValueError("scale must be a positive integer.")
    if not 0.0 <= previous_opacity <= 1.0 or not 0.0 <= current_opacity <= 1.0:
        raise ValueError("Overlay opacities must be between 0 and 1.")
    paths, loaded = _load_same_size_frames(frames)
    ensure_output_is_distinct(output_path, paths)
    columns = columns or math.ceil(math.sqrt(len(loaded)))
    if columns < 1:
        raise ValueError("columns must be at least 1.")
    rows = math.ceil(len(loaded) / columns)
    preview_size = (loaded[0].width * scale, loaded[0].height * scale)
    label_height = 16
    cell_width = preview_size[0] + padding * 2
    cell_height = preview_size[1] + padding * 2 + label_height
    canvas = Image.new("RGBA", (cell_width * columns, cell_height * rows), (24, 24, 28, 255))
    draw = ImageDraw.Draw(canvas)
    font = ImageFont.load_default()
    pairs: list[list[int]] = []

    for index, frame in enumerate(loaded):
        previous_index = len(loaded) - 1 if loop and index == 0 and len(loaded) > 1 else max(0, index - 1)
        previous = loaded[previous_index].resize(preview_size, _RESAMPLING.NEAREST)
        current = frame.resize(preview_size, _RESAMPLING.NEAREST)
        cell_x = (index % columns) * cell_width
        cell_y = (index // columns) * cell_height
        board = _checkerboard(preview_size, checker_size)
        if index > 0 or (loop and len(loaded) > 1):
            board.alpha_composite(
                _tint_silhouette(previous, (255, 82, 170), previous_opacity)
            )
        board.alpha_composite(
            _tint_silhouette(current, (74, 232, 255), current_opacity)
        )
        canvas.alpha_composite(board, (cell_x + padding, cell_y + padding + label_height))
        label = (
            f"{previous_index:03d} -> {index:03d} (loop)"
            if index == 0 and loop and len(loaded) > 1
            else f"start {index:03d}"
            if index == 0
            else f"{previous_index:03d} -> {index:03d}"
        )
        draw.text(
            (cell_x + padding, cell_y + padding),
            label,
            fill=(240, 240, 244, 255),
            font=font,
        )
        pairs.append([previous_index, index])

    target = atomic_save_png(canvas, output_path)
    return {
        "schema_version": 1,
        "output_path": str(target.resolve()),
        "sha256": sha256_file(target),
        "comparison_mode": "adjacent_frames",
        "frame_count": len(loaded),
        "pairs": pairs,
        "loop": loop,
        "columns": columns,
        "rows": rows,
        "scale": scale,
        "previous_color": [255, 82, 170],
        "current_color": [74, 232, 255],
        "width": canvas.width,
        "height": canvas.height,
        "frame_order": [str(path.resolve()) for path in paths],
    }


def build_previews(
    frames: PathLike | Iterable[PathLike],
    output_dir: PathLike,
    *,
    fps: float = 12.0,
    scale: int = 4,
    columns: int | None = None,
    loop: bool = True,
) -> dict[str, object]:
    """Create original/enlarged GIFs, a frame grid, and adjacent overlays."""

    paths = resolve_frame_paths(frames)
    target_dir = Path(output_dir).expanduser()
    if isinstance(frames, (str, os.PathLike)) and Path(frames).expanduser().is_dir():
        if os.path.normcase(str(Path(frames).expanduser().resolve())) == os.path.normcase(
            str(target_dir.resolve())
        ):
            raise ValueError("Preview output directory must differ from the frame directory.")
    target_dir.mkdir(parents=True, exist_ok=True)
    original = build_gif(paths, target_dir / "animation.gif", fps=fps, scale=1, loop=loop)
    enlarged = build_gif(
        paths, target_dir / f"animation_x{scale}.gif", fps=fps, scale=scale, loop=loop
    )
    grid = build_frame_grid(
        paths, target_dir / "frame_grid.png", scale=scale, columns=columns
    )
    overlay = build_adjacent_frame_overlay(
        paths,
        target_dir / "adjacent_frame_overlay.png",
        scale=scale,
        columns=columns,
        loop=loop,
    )
    return {
        "schema_version": 1,
        "output_dir": str(target_dir.resolve()),
        "gif_original": original,
        "gif_enlarged": enlarged,
        "frame_grid": grid,
        "adjacent_frame_overlay": overlay,
        "first_frame_overlay": overlay,
    }


def build_review_grid(
    frame_paths: PathLike | Iterable[PathLike],
    output_path: PathLike,
    scale: int = 4,
    columns: int | None = None,
) -> dict[str, object]:
    """Create a checkerboard review grid and return JSON-safe metadata.

    Every frame is enlarged with nearest-neighbour sampling and labelled below
    its cell. Labels never cover sprite pixels. Directory input is naturally
    sorted; an iterable retains the caller's explicit order.
    """

    return build_frame_grid(frame_paths, output_path, scale=scale, columns=columns)


def build_baseline_grid(
    frame_paths: PathLike | Iterable[PathLike],
    output_path: PathLike,
    *,
    ground_y: int,
    anchor_x: int | None = None,
    scale: int = 4,
    columns: int | None = None,
    padding: int = 8,
) -> dict[str, object]:
    """Create a review grid with a non-binding project reference crosshair."""

    paths, loaded = _load_same_size_frames(frame_paths)
    if not 0 <= ground_y < loaded[0].height:
        raise ValueError("ground_y must be inside each frame")
    if anchor_x is not None and not 0 <= anchor_x < loaded[0].width:
        raise ValueError("anchor_x must be inside each frame")
    ensure_output_is_distinct(output_path, paths)
    columns = columns or math.ceil(math.sqrt(len(loaded)))
    rows = math.ceil(len(loaded) / columns)
    frame_width = loaded[0].width * scale
    frame_height = loaded[0].height * scale
    label_height = 16
    cell_width = frame_width + padding * 2
    cell_height = frame_height + padding * 2 + label_height
    canvas = Image.new("RGBA", (cell_width * columns, cell_height * rows), (24, 24, 28, 255))
    draw = ImageDraw.Draw(canvas)
    font = ImageFont.load_default()
    for index, frame in enumerate(loaded):
        cell_x = (index % columns) * cell_width
        cell_y = (index // columns) * cell_height
        preview = frame.resize((frame_width, frame_height), _RESAMPLING.NEAREST)
        board = _checkerboard(preview.size, 8)
        board.alpha_composite(preview)
        origin_x = cell_x + padding
        origin_y = cell_y + padding + label_height
        canvas.alpha_composite(board, (origin_x, origin_y))
        baseline_y = origin_y + ground_y * scale
        draw.line(
            (origin_x, baseline_y, origin_x + frame_width - 1, baseline_y),
            fill=(255, 102, 134, 220),
            width=max(1, scale // 2),
        )
        if anchor_x is not None:
            anchor_preview_x = origin_x + anchor_x * scale
            draw.line(
                (anchor_preview_x, origin_y, anchor_preview_x, origin_y + frame_height - 1),
                fill=(78, 231, 255, 220),
                width=max(1, scale // 2),
            )
            marker_radius = max(2, scale)
            draw.ellipse(
                (
                    anchor_preview_x - marker_radius,
                    baseline_y - marker_radius,
                    anchor_preview_x + marker_radius,
                    baseline_y + marker_radius,
                ),
                outline=(255, 238, 128, 255),
                width=max(1, scale // 2),
            )
        draw.text((cell_x + padding, cell_y + padding), f"frame_{index:03d}", fill=(240, 240, 244, 255), font=font)
    target = atomic_save_png(canvas, output_path)
    return {
        "schema_version": 1,
        "output_path": str(target.resolve()),
        "sha256": sha256_file(target),
        "frame_count": len(loaded),
        "columns": columns,
        "rows": rows,
        "scale": scale,
        "anchor_x": anchor_x,
        "ground_y": ground_y,
        "width": canvas.width,
        "height": canvas.height,
        "frame_order": [str(path.resolve()) for path in paths],
    }


def build_overlay(
    frame_paths: PathLike | Iterable[PathLike],
    output_path: PathLike,
    scale: int = 4,
    columns: int | None = None,
    *,
    loop: bool = False,
) -> dict[str, object]:
    """Create adjacent-frame onion-skin comparisons for continuity review."""

    return build_adjacent_frame_overlay(
        frame_paths,
        output_path,
        scale=scale,
        columns=columns,
        loop=loop,
    )


def _load_same_size_frames(
    frames: PathLike | Iterable[PathLike],
) -> tuple[list[Path], list[Image.Image]]:
    paths = resolve_frame_paths(frames)
    loaded: list[Image.Image] = []
    expected: tuple[int, int] | None = None
    for path in paths:
        with Image.open(path) as opened:
            opened.load()
            frame = clean_transparent_rgb(opened)
        if expected is None:
            expected = frame.size
        elif frame.size != expected:
            raise ValueError(f"Frame {path} has size {frame.size}; expected {expected}.")
        loaded.append(frame)
    return paths, loaded


def _to_shared_palette(frames: list[Image.Image]) -> list[Image.Image]:
    sample = Image.new("RGB", (sum(frame.width for frame in frames), max(f.height for f in frames)))
    offset = 0
    for frame in frames:
        sample.paste(frame.convert("RGB"), (offset, 0))
        offset += frame.width
    quantized_sample = sample.quantize(
        colors=255,
        method=_QUANTIZE.MEDIANCUT,
        dither=_DITHER.NONE,
    )
    palette_data = (quantized_sample.getpalette() or [])[: 255 * 3]
    palette_data.extend([0] * (768 - len(palette_data)))
    palette = Image.new("P", (1, 1))
    palette.putpalette(palette_data)

    indexed_frames: list[Image.Image] = []
    for frame in frames:
        indexed = frame.convert("RGB").quantize(palette=palette, dither=_DITHER.NONE)
        transparent = frame.getchannel("A").point(lambda alpha: 255 if alpha == 0 else 0)
        indexed.paste(255, mask=transparent)
        indexed.info["transparency"] = 255
        indexed_frames.append(indexed)
    return indexed_frames


def _checkerboard(size: tuple[int, int], square: int) -> Image.Image:
    board = Image.new("RGBA", size, (196, 196, 202, 255))
    draw = ImageDraw.Draw(board)
    alternate = (232, 232, 236, 255)
    for y in range(0, size[1], square):
        for x in range(0, size[0], square):
            if (x // square + y // square) % 2:
                draw.rectangle(
                    (x, y, min(x + square - 1, size[0] - 1), min(y + square - 1, size[1] - 1)),
                    fill=alternate,
                )
    return board


def _with_opacity(image: Image.Image, opacity: float) -> Image.Image:
    adjusted = image.copy()
    adjusted.putalpha(image.getchannel("A").point(lambda value: round(value * opacity)))
    return adjusted


def _tint_silhouette(
    image: Image.Image,
    color: tuple[int, int, int],
    opacity: float,
) -> Image.Image:
    """Return a solid-colour silhouette while preserving source alpha."""

    alpha = image.getchannel("A").point(lambda value: round(value * opacity))
    tinted = Image.new("RGBA", image.size, (*color, 0))
    tinted.putalpha(alpha)
    return tinted
