from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image, ImageDraw


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from sprite_pipeline.service import SpritePipelineService
from sprite_pipeline.models import ExportOptions


class BackendCapabilityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.environment = patch.dict(os.environ, {}, clear=False)
        self.environment.start()
        os.environ.pop("PIXELLAB_API_KEY", None)
        self.temp_dir = tempfile.TemporaryDirectory(prefix="sprite_backend_capabilities_")
        self.root = Path(self.temp_dir.name) / "后端能力"
        self.root.mkdir(parents=True)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()
        self.environment.stop()

    def test_pixellab_api_key_can_be_saved_cleared_and_is_not_exposed(self) -> None:
        old_secret = "pxl_old_secret_123456"
        new_secret = "pxl_new_SUPER_SECRET_987654"
        env_path = self.root / ".env"
        env_path.write_text(
            "# Preserve unrelated local settings\n"
            "PIXELLAB_BASE_URL=https://unit.invalid\n"
            f"PIXELLAB_API_KEY={old_secret}\n"
            "CUSTOM_SETTING=keep-me\n",
            encoding="utf-8",
        )
        service = SpritePipelineService(self.root)

        configured = service.configure_pixellab_api_key(f"  {new_secret}  ")

        self.assertIs(configured, True)
        self.assertEqual(service.settings.pixellab_api_key, new_secret)
        saved = env_path.read_text(encoding="utf-8")
        self.assertEqual(saved.count("PIXELLAB_API_KEY="), 1)
        self.assertIn(f"PIXELLAB_API_KEY={new_secret}\n", saved)
        self.assertNotIn(old_secret, saved)
        self.assertIn("PIXELLAB_BASE_URL=https://unit.invalid", saved)
        self.assertIn("CUSTOM_SETTING=keep-me", saved)
        self.assertEqual(SpritePipelineService(self.root).settings.pixellab_api_key, new_secret)

        public_result = {
            "configured": configured,
            "presets": service.list_presets(),
        }
        self.assertNotIn(new_secret, json.dumps(public_result, ensure_ascii=False))
        for path in self.root.rglob("*"):
            if path.is_file() and path != env_path:
                self.assertNotIn(new_secret.encode("utf-8"), path.read_bytes(), str(path))
        self.assertEqual(list(self.root.glob(".env.*.tmp")), [])

        cleared = service.configure_pixellab_api_key(None)

        self.assertIs(cleared, False)
        self.assertIsNone(service.settings.pixellab_api_key)
        cleared_text = env_path.read_text(encoding="utf-8")
        self.assertNotIn("PIXELLAB_API_KEY", cleared_text)
        self.assertNotIn(new_secret, cleared_text)
        self.assertIn("PIXELLAB_BASE_URL=https://unit.invalid", cleared_text)
        self.assertIn("CUSTOM_SETTING=keep-me", cleared_text)
        self.assertIsNone(SpritePipelineService(self.root).settings.pixellab_api_key)
        self.assertFalse(any(new_secret.encode("utf-8") in path.read_bytes() for path in self.root.rglob("*") if path.is_file()))

    def test_128px_four_column_sheet_creates_reference_with_explicit_project_anchor(self) -> None:
        cell_size = 128
        columns = 4
        rows = 2
        reference_index = 6
        sheet_path = self.root / "incoming" / "boss_sheet.png"
        sheet_path.parent.mkdir(parents=True)
        sheet = Image.new("RGBA", (cell_size * columns, cell_size * rows), (0, 0, 0, 0))
        draw = ImageDraw.Draw(sheet)
        for index in range(columns * rows):
            left = (index % columns) * cell_size
            top = (index // columns) * cell_size
            color = ((31 * index) % 256, (67 * index) % 256, (101 * index) % 256, 255)
            draw.rectangle((left + 24, top + 18, left + 78, top + 96), fill=color)
            draw.rectangle((left + 79, top + 50, left + 90, top + 61), fill=(255, index, 128, 255))
        sheet.save(sheet_path, format="PNG", optimize=False, compress_level=9)
        expected_left = (reference_index % columns) * cell_size
        expected_top = (reference_index // columns) * cell_size
        expected_reference = sheet.crop(
            (
                expected_left,
                expected_top,
                expected_left + cell_size,
                expected_top + cell_size,
            )
        )
        service = SpritePipelineService(self.root)

        created = service.create_character_preset_from_sheet(
            display_name="Project Boss",
            sprite_sheet=sheet_path,
            cell_size=cell_size,
            reference_frame_index=reference_index,
            character_id="project_boss",
            facing="left",
            identity_description="Preserve the approved project boss silhouette and armor.",
            anchor_x=64,
            anchor_ground_y=112,
            sheet_columns=4,
        )

        self.assertEqual(created.character_id, "project_boss")
        self.assertEqual((created.cell_width, created.cell_height), (128, 128))
        self.assertEqual((created.anchor.x, created.anchor.ground_y), (64, 112))
        self.assertEqual(created.sheet_columns, 4)
        self.assertEqual(created.facing, "left")
        preset_dir = self.root / "presets" / "characters" / "project_boss"
        reference_path = preset_dir / "idle_reference.png"
        character_path = preset_dir / "character.json"
        self.assertTrue(reference_path.is_file())
        self.assertTrue(character_path.is_file())
        with Image.open(reference_path) as opened:
            opened.load()
            actual_reference = opened.convert("RGBA")
        self.assertEqual(actual_reference.size, (128, 128))
        self.assertEqual(actual_reference.tobytes(), expected_reference.tobytes())
        stored = json.loads(character_path.read_text(encoding="utf-8"))
        self.assertEqual(stored["anchor"], {"x": 64, "ground_y": 112})
        self.assertEqual(stored["sheet_columns"], 4)
        loaded, loaded_path = service.presets.load_character("project_boss")
        self.assertEqual(loaded, created)
        self.assertEqual(loaded_path, character_path)

    def test_export_filename_accepts_project_png_name_and_rejects_paths(self) -> None:
        self.assertEqual(ExportOptions(filename="赛博人物行走.png").filename, "赛博人物行走.png")
        for invalid in (
            "../walk.png",
            r"folder\walk.png",
            "walk.gif",
            "foo.png:bar.png",
            "CON.png",
            "nul.PNG",
            "COM1.any.png",
            "walk.png ",
        ):
            with self.subTest(filename=invalid):
                with self.assertRaises(ValueError):
                    ExportOptions(filename=invalid)


if __name__ == "__main__":
    unittest.main()
