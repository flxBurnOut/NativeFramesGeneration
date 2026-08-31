"""Project-specific sprite contract used by the non-technical web UI.

The generation service remains project-neutral.  This small profile captures the
verified Godot contract for the current game so the UI can hide technical grid
fields and still create ordinary service jobs that remain usable from REST/CLI.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import ceil


@dataclass(frozen=True, slots=True)
class ProjectAction:
    action_id: str
    display_name: str
    filename: str
    frame_count: int
    fps: float
    loop: bool
    note: str = ""

    @property
    def rows(self) -> int:
        return ceil(self.frame_count / DREAMWEAVER_PROFILE.columns)

    @property
    def sheet_size(self) -> tuple[int, int]:
        return (
            DREAMWEAVER_PROFILE.cell_width * DREAMWEAVER_PROFILE.columns,
            DREAMWEAVER_PROFILE.cell_height * self.rows,
        )


@dataclass(frozen=True, slots=True)
class ProjectProfile:
    profile_id: str
    project_name: str
    display_name: str
    engine: str
    character_id: str
    character_name: str
    cell_width: int
    cell_height: int
    columns: int
    order: str
    facing: str
    anchor_x: int
    anchor_ground_y: int
    sprite_offset_x: int
    sprite_offset_y: int
    project_asset_dir: str
    actions: tuple[ProjectAction, ...]

    def action(self, action_id: str) -> ProjectAction:
        for item in self.actions:
            if item.action_id == action_id:
                return item
        raise KeyError(action_id)


DREAMWEAVER_PROFILE = ProjectProfile(
    profile_id="dreamweaver_player_cyber_v1",
    project_name="织梦者",
    display_name="织梦者 / 赛博战士",
    engine="Godot 4.6",
    character_id="player_cyber",
    character_name="赛博战士 / Player_Warrior_Cyber",
    cell_width=128,
    cell_height=128,
    columns=4,
    order="row_major",
    facing="right",
    anchor_x=64,
    anchor_ground_y=106,
    sprite_offset_x=0,
    sprite_offset_y=-10,
    project_asset_dir="Assets/Sprites/player_cyber Ani",
    actions=(
        ProjectAction("idle", "待机", "赛博人物待机.png", 16, 8, True),
        ProjectAction("walk", "行走", "赛博人物行走.png", 16, 5, True),
        ProjectAction(
            "jump",
            "跳跃",
            "赛博人物跳跃.png",
            12,
            6,
            True,
            "游戏状态机会在下降阶段使用第 5 帧（索引 4）。",
        ),
        ProjectAction("hurt", "受击", "赛博人物受击.png", 12, 12, True),
        ProjectAction(
            "death",
            "失败 / 倒地",
            "赛博人物失败.png",
            16,
            12,
            False,
            "播放一次并停在末帧。",
        ),
    ),
)


def project_action_choices() -> list[tuple[str, str]]:
    """Return concise Gradio-compatible labels for supported regular sheets."""

    return [
        (
            f"{item.display_name} · {item.frame_count} 帧 · {item.fps:g} FPS · "
            f"{'循环' if item.loop else '单次'}",
            item.action_id,
        )
        for item in DREAMWEAVER_PROFILE.actions
    ]

