"""Create the bundled Dreamweaver player preset from an approved project sheet."""

from __future__ import annotations

import argparse
from pathlib import Path

from sprite_pipeline.project_profile import DREAMWEAVER_PROFILE
from sprite_pipeline.service import SpritePipelineService


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("sheet", type=Path)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parent.parent)
    args = parser.parse_args()
    profile = DREAMWEAVER_PROFILE
    destination = args.root.resolve() / "presets" / "characters" / profile.character_id
    if destination.exists():
        print(f"Preset already exists: {destination}")
        return 0
    preset = SpritePipelineService(args.root).create_character_preset_from_sheet(
        display_name="赛博战士（织梦者）",
        sprite_sheet=args.sheet,
        cell_size=profile.cell_width,
        reference_frame_index=0,
        facing=profile.facing,
        identity_description=(
            "Preserve the cyber warrior identity, blue-black armour, cyan highlights, "
            "body proportions, helmet, sword silhouette, and right-facing side view "
            "from the approved project reference."
        ),
        character_id=profile.character_id,
        sheet_columns=profile.columns,
        anchor_x=profile.anchor_x,
        anchor_ground_y=profile.anchor_ground_y,
    )
    print(f"Created preset: {preset.character_id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
