"""Deterministic, non-redrawing cleanup operations for sprite frames."""

from __future__ import annotations

from pathlib import Path

from PIL import Image

from ._common import (
    SOURCE_ALPHA_KEY,
    PathLike,
    atomic_save_png,
    ensure_output_is_distinct,
    image_source_has_alpha,
)


def clean_transparent_rgb(image: Image.Image) -> Image.Image:
    """Return an RGBA copy with RGB set to zero wherever alpha is zero.

    Pixels with partial or full opacity are not changed. Clearing hidden RGB
    makes checksums and exact-frame comparisons stable without cropping,
    resizing, recolouring, or otherwise redrawing the sprite.
    """

    rgba = image.convert("RGBA")
    pixels = bytearray(rgba.tobytes())
    for offset in range(0, len(pixels), 4):
        if pixels[offset + 3] == 0:
            pixels[offset] = 0
            pixels[offset + 1] = 0
            pixels[offset + 2] = 0
    return Image.frombytes("RGBA", rgba.size, bytes(pixels))


def clean_png_transparency(
    source: PathLike, destination: PathLike | None = None
) -> dict[str, object]:
    """Clean one PNG and save it as deterministic RGBA.

    Args:
        source: Input PNG path.
        destination: Output path. When omitted, ``<stem>.rgba.png`` is created
            beside the source. In-place replacement is intentionally rejected.

    Returns:
        A JSON-serializable dictionary containing input/output paths and size.
    """

    source_path = Path(source).expanduser()
    output_path = (
        Path(destination).expanduser()
        if destination
        else source_path.with_name(f"{source_path.stem}.rgba.png")
    )
    ensure_output_is_distinct(output_path, [source_path])
    with Image.open(source_path) as opened:
        source_has_alpha = image_source_has_alpha(opened)
        source_mode = opened.mode
        opened.load()
        cleaned = clean_transparent_rgb(opened)
    atomic_save_png(
        cleaned,
        output_path,
        text_metadata={SOURCE_ALPHA_KEY: "1" if source_has_alpha else "0"},
    )
    return {
        "source": str(source_path.resolve()),
        "output": str(output_path.resolve()),
        "width": cleaned.width,
        "height": cleaned.height,
        "mode": "RGBA",
        "source_mode": source_mode,
        "source_has_alpha": source_has_alpha,
    }


def clean_rgba_file(source: PathLike, destination: PathLike) -> dict[str, object]:
    """Normalize one image into a deterministic RGBA PNG.

    Only RGB values hidden under ``alpha == 0`` are cleared; dimensions and all
    visible or partially transparent pixels remain unchanged. The source is
    never modified, and supplying the same destination path is rejected. The
    returned metadata dictionary is JSON serializable.
    """

    return clean_png_transparency(source, destination)
