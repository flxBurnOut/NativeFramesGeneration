from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

from PIL import Image, ImageDraw


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from sprite_pipeline.errors import ValidationHarnessError
from sprite_pipeline.sheet_inspection import (
    build_grid_overlay,
    extract_character_reference_frame,
    inspect_sprite_sheet,
)


class SheetInspectionTests(unittest.TestCase):
    cell_size = 128
    columns = 4
    rows = 3

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory(prefix="sprite_sheet_inspection_")
        self.root = Path(self.temp_dir.name) / "网格检测"
        self.root.mkdir(parents=True)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def _write_sheet(self, name: str, used_indices: set[int]) -> Path:
        path = self.root / name
        image = Image.new(
            "RGBA",
            (self.cell_size * self.columns, self.cell_size * self.rows),
            (0, 0, 0, 0),
        )
        draw = ImageDraw.Draw(image)
        for index in sorted(used_indices):
            left = (index % self.columns) * self.cell_size
            top = (index // self.columns) * self.cell_size
            color = ((37 * index + 20) % 256, (71 * index + 40) % 256, (103 * index + 60) % 256, 255)
            draw.rectangle((left + 16, top + 20, left + 80, top + 100), fill=color)
        image.save(path, format="PNG", optimize=False, compress_level=9)
        return path

    def test_inspects_512x384_sheet_as_twelve_128px_frames_and_builds_sized_overlay(self) -> None:
        sheet_path = self._write_sheet("twelve_frames.png", set(range(12)))
        original_bytes = sheet_path.read_bytes()

        inspection = inspect_sprite_sheet(
            sheet_path,
            cell_width=128,
            cell_height=128,
            columns=4,
        )

        self.assertEqual(inspection["path"], str(sheet_path.resolve()))
        self.assertEqual((inspection["width"], inspection["height"]), (512, 384))
        self.assertEqual((inspection["cell_width"], inspection["cell_height"]), (128, 128))
        self.assertEqual((inspection["columns"], inspection["rows"]), (4, 3))
        self.assertEqual(inspection["physical_cells"], 12)
        self.assertEqual(inspection["frame_count"], 12)
        self.assertEqual(inspection["trailing_empty_cells"], 0)
        self.assertEqual(inspection["empty_cells_before_last_frame"], [])
        self.assertTrue(inspection["has_regular_order"])
        self.assertEqual(len(inspection["frame_bounds"]), 12)
        self.assertEqual(inspection["frame_bounds"][0], [16, 20, 81, 101])

        overlay = build_grid_overlay(sheet_path, inspection, scale=2)
        self.assertEqual(overlay.mode, "RGBA")
        self.assertEqual(overlay.size, (1024, 768))
        self.assertEqual(sheet_path.read_bytes(), original_bytes, "inspection and overlay must not rewrite the source")

    def test_trailing_transparent_cells_are_excluded_from_frame_count(self) -> None:
        sheet_path = self._write_sheet("five_frames_with_padding.png", set(range(5)))

        inspection = inspect_sprite_sheet(
            sheet_path,
            cell_width=128,
            cell_height=128,
            columns=4,
        )

        self.assertEqual(inspection["physical_cells"], 12)
        self.assertEqual(inspection["frame_count"], 5)
        self.assertEqual(inspection["trailing_empty_cells"], 7)
        self.assertEqual(inspection["empty_cells_before_last_frame"], [])
        self.assertTrue(inspection["has_regular_order"])
        self.assertEqual(len(inspection["frame_bounds"]), 5)

    def test_transparent_hole_before_last_frame_is_reported_without_reindexing(self) -> None:
        sheet_path = self._write_sheet("middle_hole.png", {0, 1, 3, 4})

        inspection = inspect_sprite_sheet(
            sheet_path,
            cell_width=128,
            cell_height=128,
            columns=4,
        )

        self.assertEqual(inspection["frame_count"], 5)
        self.assertEqual(inspection["trailing_empty_cells"], 7)
        self.assertEqual(inspection["empty_cells_before_last_frame"], [2])
        self.assertFalse(inspection["has_regular_order"])
        self.assertEqual(inspection["frame_bounds"][2], None)
        self.assertIsNotNone(inspection["frame_bounds"][3])

    def test_character_reference_uses_single_frame_or_first_visible_sheet_cell(self) -> None:
        single = self.root / "single_reference.png"
        single_image = Image.new("RGBA", (128, 128), (0, 0, 0, 0))
        ImageDraw.Draw(single_image).rectangle((20, 18, 75, 105), fill=(20, 170, 230, 255))
        single_image.save(single, format="PNG")

        single_reference, single_state = extract_character_reference_frame(
            single,
            cell_width=128,
            cell_height=128,
            columns=4,
        )

        self.assertEqual(single_reference.tobytes(), single_image.tobytes())
        self.assertEqual(single_state["kind"], "single")
        self.assertEqual(single_state["reference_index"], 0)

        sheet = self._write_sheet("reference_sheet.png", {2, 3, 4})
        sheet_reference, sheet_state = extract_character_reference_frame(
            sheet,
            cell_width=128,
            cell_height=128,
            columns=4,
        )

        with Image.open(sheet) as opened:
            expected = opened.convert("RGBA").crop((256, 0, 384, 128))
        self.assertEqual(sheet_reference.tobytes(), expected.tobytes())
        self.assertEqual(sheet_state["kind"], "sheet")
        self.assertEqual(sheet_state["reference_index"], 2)
        self.assertEqual((sheet_state["sheet_width"], sheet_state["sheet_height"]), (512, 384))

    def test_rejects_wrong_columns_missing_alpha_and_fully_transparent_sheet(self) -> None:
        regular = self._write_sheet("wrong_columns.png", {0})
        with self.subTest(case="wrong columns"):
            with self.assertRaisesRegex(ValidationHarnessError, "wrong number of columns") as caught:
                inspect_sprite_sheet(
                    regular,
                    cell_width=128,
                    cell_height=128,
                    columns=3,
                )
            self.assertEqual(caught.exception.details, {"actual": 4, "expected": 3})

        no_alpha = self.root / "no_alpha.png"
        Image.new("RGB", (512, 384), (20, 40, 60)).save(no_alpha, format="PNG")
        with self.subTest(case="missing alpha"):
            with self.assertRaisesRegex(ValidationHarnessError, "alpha channel"):
                inspect_sprite_sheet(
                    no_alpha,
                    cell_width=128,
                    cell_height=128,
                    columns=4,
                )

        transparent = self.root / "fully_transparent.png"
        Image.new("RGBA", (512, 384), (0, 0, 0, 0)).save(transparent, format="PNG")
        with self.subTest(case="fully transparent"):
            with self.assertRaisesRegex(ValidationHarnessError, "does not contain any visible frames"):
                inspect_sprite_sheet(
                    transparent,
                    cell_width=128,
                    cell_height=128,
                    columns=4,
                )


if __name__ == "__main__":
    unittest.main()
