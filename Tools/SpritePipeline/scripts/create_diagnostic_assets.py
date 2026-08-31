"""Rebuild the deterministic, non-production diagnostic character PNG."""

from pathlib import Path

from PIL import Image, ImageDraw, PngImagePlugin


def main() -> None:
    target = (
        Path(__file__).resolve().parents[1]
        / "presets"
        / "characters"
        / "diagnostic_dummy"
        / "idle_reference.png"
    )
    image = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    navy = (22, 35, 58, 255)
    cyan = (52, 214, 220, 255)
    light = (171, 250, 238, 255)
    dark = (8, 15, 28, 255)

    draw.rectangle((25, 16, 38, 27), fill=navy, outline=cyan)
    draw.rectangle((28, 19, 38, 22), fill=light)
    draw.rectangle((23, 27, 40, 46), fill=navy, outline=cyan)
    draw.rectangle((27, 31, 36, 40), fill=dark)
    draw.rectangle((19, 29, 23, 43), fill=navy, outline=cyan)
    draw.rectangle((40, 29, 44, 42), fill=navy, outline=cyan)
    draw.rectangle((24, 46, 30, 56), fill=navy, outline=cyan)
    draw.rectangle((34, 46, 40, 56), fill=navy, outline=cyan)
    draw.rectangle((22, 55, 30, 57), fill=dark, outline=cyan)
    draw.rectangle((34, 55, 42, 57), fill=dark, outline=cyan)
    draw.rectangle((44, 39, 48, 42), fill=dark, outline=cyan)
    draw.line((48, 40, 54, 34), fill=light, width=2)

    metadata = PngImagePlugin.PngInfo()
    metadata.add_text("sprite_pipeline_asset", "diagnostic_only")
    target.parent.mkdir(parents=True, exist_ok=True)
    image.save(target, format="PNG", pnginfo=metadata, optimize=False, compress_level=9)


if __name__ == "__main__":
    main()
