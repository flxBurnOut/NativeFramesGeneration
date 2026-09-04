"""Project-specific sprite contract used by the non-technical web UI.

The attached game manifest provides the verified Cyber Warrior filenames and
runtime timing. New harness output deliberately standardizes every bundled
action to sixteen row-major frames in one 4x4 sheet. Existing lower-frame sheets
remain importable, but are no longer the generation defaults.
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
    legacy_sheet_rows: int | None = None
    legacy_frame_cells: tuple[tuple[int, int], ...] = ()

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
    profile_id="dreamweaver_player_cyber_v3_uniform_16",
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
            "jump", "jump", "跳跃", "赛博人物跳跃.png", 16, 16, 6, 6, True,
            4, 4, _row_major_cells(16), (12,), integration_status="frame_upgrade",
            note="新合同的下降关键姿势为第 13 帧（索引 12）；替换旧资产时需要同步 Godot 的下降帧映射。",
            legacy_sheet_rows=3, legacy_frame_cells=_row_major_cells(12),
        ),
        ProjectAction(
            "attack", "attack", "地面攻击", "赛博人物攻击.png", 16, 16, 18, 18, False,
            4, 4, _row_major_cells(16), (6,), integration_status="frame_upgrade",
            note="新合同使用完整 16 帧；整段只攻击一次，第 7 帧（索引 6）作为刀举过头或肩侧的唯一蓄力/技能定格姿势，随后向前纵向劈砍并只做跟随与恢复；替换旧资产时需要同步 Godot 帧列表。",
            legacy_sheet_rows=2,
            legacy_frame_cells=((0, 0), (2, 0), (1, 1), (2, 1), (3, 1)),
        ),
        ProjectAction(
            "attack_in_air", "attack_in_air", "空中攻击", "赛博人物空中攻击.png", 16, 16, 18, 5, False,
            4, 4, _row_major_cells(16), integration_status="frame_upgrade",
            note="资源场景记录为 5 FPS，但当前角色运行时代码强制按 18 FPS 播放；新 16 帧资产仍遵循运行时 18 FPS，并需同步 Godot 帧列表。",
            legacy_sheet_rows=3,
            legacy_frame_cells=((0, 0), (1, 0), (0, 1), (3, 0), (2, 0)),
        ),
        ProjectAction(
            "hurt", "hit", "受击", "赛博人物受击.png", 16, 16, 12, 12, True,
            4, 4, _row_major_cells(16), integration_status="frame_upgrade",
            note="新合同由旧 12 帧升级为 16 帧；替换旧资产时需要同步 Godot 帧列表。",
            legacy_sheet_rows=3, legacy_frame_cells=_row_major_cells(12),
        ),
        ProjectAction(
            "backward_evade", "backward_evade", "向后闪避", "赛博人物向后闪避.png", 16, 16, 12, 12, False,
            4, 4, _row_major_cells(16), integration_status="new",
            note="新增 16 帧动作资产：Harness 可生成、检查和导出；当前 Godot 角色状态机尚未接线，替换进工程前需新增动画与状态映射。",
            legacy_sheet_rows=2, legacy_frame_cells=_row_major_cells(8),
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
