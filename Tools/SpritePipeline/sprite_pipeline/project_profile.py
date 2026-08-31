"""Project-specific sprite contract used by the non-technical web UI.

The attached game manifest is treated as project data. The shared generation
service still works for custom presets, while this profile locks the verified
Cyber Warrior filenames, grid shapes, playback order, and runtime timing.
"""

from __future__ import annotations

from dataclasses import dataclass


def _row_major_cells(frame_count: int, columns: int = 4) -> tuple[tuple[int, int], ...]:
    return tuple((index % columns, index // columns) for index in range(frame_count))


@dataclass(frozen=True, slots=True)
class ProjectAction:
    action_id: str
    manifest_action_name: str
    display_name: str
    filename: str
    frame_count: int
    provider_frame_count: int
    fps: float
    scene_fps: float
    loop: bool
    columns: int
    rows: int
    frame_cells: tuple[tuple[int, int], ...]
    critical_frame_indices: tuple[int, ...] = ()
    integration_status: str = "existing"
    note: str = ""

    @property
    def sheet_size(self) -> tuple[int, int]:
        return (
            DREAMWEAVER_PROFILE.cell_width * self.columns,
            DREAMWEAVER_PROFILE.cell_height * self.rows,
        )

    @property
    def unused_cells(self) -> tuple[tuple[int, int], ...]:
        used = set(self.frame_cells)
        return tuple(
            (column, row)
            for row in range(self.rows)
            for column in range(self.columns)
            if (column, row) not in used
        )

    @property
    def is_sparse(self) -> bool:
        return self.frame_cells != _row_major_cells(self.frame_count, self.columns)


@dataclass(frozen=True, slots=True)
class ProjectProfile:
    profile_id: str
    project_name: str
    display_name: str
    engine: str
    character_id: str
    manifest_character_id: str
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
    profile_id="dreamweaver_player_cyber_v2",
    project_name="织梦者",
    display_name="织梦者 / 赛博战士",
    engine="Godot 4.6.2",
    character_id="player_cyber",
    manifest_character_id="player_warrior_cyber",
    character_name="赛博战士 / Player_Warrior_Cyber",
    cell_width=128,
    cell_height=128,
    columns=4,
    order="manifest_frame_order",
    facing="right",
    anchor_x=64,
    anchor_ground_y=106,
    sprite_offset_x=0,
    sprite_offset_y=-10,
    project_asset_dir="Assets/Sprites/player_cyber Ani",
    actions=(
        ProjectAction(
            "idle", "idle", "待机", "赛博人物待机.png", 16, 16, 8, 8, True,
            4, 4, _row_major_cells(16),
        ),
        ProjectAction(
            "walk", "walk", "行走", "赛博人物行走.png", 16, 16, 5, 5, True,
            4, 4, _row_major_cells(16),
        ),
        ProjectAction(
            "jump", "jump", "跳跃", "赛博人物跳跃.png", 12, 12, 6, 6, True,
            4, 3, _row_major_cells(12), (4,),
            note="下降阶段锁定使用第 5 帧（索引 4）。",
        ),
        ProjectAction(
            "attack", "attack", "地面攻击", "赛博人物攻击.png", 5, 6, 18, 18, False,
            4, 2, ((0, 0), (2, 0), (1, 1), (2, 1), (3, 1)), (2,),
            note="项目实际只播放 5 帧；第 3 帧（索引 2）用于蓄力/技能定格。导出保留 3 个透明空格。",
        ),
        ProjectAction(
            "attack_in_air", "attack_in_air", "空中攻击", "赛博人物空中攻击.png", 5, 6, 18, 5, False,
            4, 3, ((0, 0), (1, 0), (0, 1), (3, 0), (2, 0)),
            note="资源场景记录为 5 FPS，但当前角色运行时代码强制按 18 FPS 播放；导出遵循运行时 18 FPS。",
        ),
        ProjectAction(
            "hurt", "hit", "受击", "赛博人物受击.png", 12, 12, 12, 12, True,
            4, 3, _row_major_cells(12),
        ),
        ProjectAction(
            "backward_evade", "backward_evade", "向后闪避", "赛博人物向后闪避.png", 8, 8, 12, 12, False,
            4, 2, _row_major_cells(8), integration_status="new",
            note="新增动作资产：Harness 可生成、检查和导出；当前 Godot 角色状态机尚未接线，替换进工程前需新增动画与状态映射。",
        ),
        ProjectAction(
            "death", "defeated", "失败 / 倒地", "赛博人物失败.png", 16, 16, 12, 12, False,
            4, 4, _row_major_cells(16),
            note="播放一次并停在末帧。",
        ),
    ),
)


def project_action_choices() -> list[tuple[str, str]]:
    """Return concise Gradio-compatible labels for project actions."""

    return [
        (
            f"{item.display_name} · {item.frame_count} 帧 · {item.fps:g} FPS · "
            f"{'循环' if item.loop else '单次'}",
            item.action_id,
        )
        for item in DREAMWEAVER_PROFILE.actions
    ]
