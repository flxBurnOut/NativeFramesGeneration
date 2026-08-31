from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from sprite_pipeline.models import ActionPreset
from sprite_pipeline.project_profile import DREAMWEAVER_PROFILE


class ProjectAssetContractTests(unittest.TestCase):
    def test_cyber_warrior_actions_match_manifest_dimensions_and_runtime_contract(self) -> None:
        profile = DREAMWEAVER_PROFILE
        self.assertEqual(profile.manifest_character_id, "player_warrior_cyber")
        self.assertEqual((profile.cell_width, profile.cell_height, profile.columns), (128, 128, 4))
        expected = {
            "idle": ("idle", "赛博人物待机.png", 16, 8, True, (512, 512)),
            "walk": ("walk", "赛博人物行走.png", 16, 5, True, (512, 512)),
            "jump": ("jump", "赛博人物跳跃.png", 12, 6, True, (512, 384)),
            "attack": ("attack", "赛博人物攻击.png", 5, 18, False, (512, 256)),
            "attack_in_air": ("attack_in_air", "赛博人物空中攻击.png", 5, 18, False, (512, 384)),
            "hurt": ("hit", "赛博人物受击.png", 12, 12, True, (512, 384)),
            "backward_evade": ("backward_evade", "赛博人物向后闪避.png", 8, 12, False, (512, 256)),
            "death": ("defeated", "赛博人物失败.png", 16, 12, False, (512, 512)),
        }
        self.assertEqual({item.action_id for item in profile.actions}, set(expected))
        for action in profile.actions:
            with self.subTest(action=action.action_id):
                manifest_name, filename, count, fps, loop, size = expected[action.action_id]
                self.assertEqual(action.manifest_action_name, manifest_name)
                self.assertEqual(action.filename, filename)
                self.assertEqual((action.frame_count, action.fps, action.loop), (count, fps, loop))
                self.assertEqual(action.sheet_size, size)
                self.assertEqual(len(action.frame_cells), count)

    def test_sparse_attack_presets_keep_five_project_frames_from_six_provider_frames(self) -> None:
        expected_cells = {
            "attack": [(0, 0), (2, 0), (1, 1), (2, 1), (3, 1)],
            "attack_in_air": [(0, 0), (1, 0), (0, 1), (3, 0), (2, 0)],
        }
        for action_id, cells in expected_cells.items():
            path = PROJECT_ROOT / "presets" / "actions" / f"{action_id}.json"
            action = ActionPreset.model_validate(json.loads(path.read_text(encoding="utf-8")))
            with self.subTest(action=action_id):
                self.assertEqual(action.frame_count, 5)
                self.assertEqual(action.generation_frame_count, 6)
                self.assertEqual(action.generation_frame_selection, [0, 1, 2, 3, 5])
                self.assertEqual(action.frame_cells, cells)
                self.assertEqual((action.sheet_columns, action.sheet_rows), (4, 2 if action_id == "attack" else 3))

    def test_backward_evade_is_explicitly_new_instead_of_claiming_existing_integration(self) -> None:
        action = DREAMWEAVER_PROFILE.action("backward_evade")
        self.assertEqual(action.integration_status, "new")
        self.assertIn("Godot", action.note)


if __name__ == "__main__":
    unittest.main()
