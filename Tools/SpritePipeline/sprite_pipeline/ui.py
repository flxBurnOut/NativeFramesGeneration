import html
import hashlib
import math
import re
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

from PIL import Image

from .errors import HarnessError, ProviderConfigurationError, ValidationHarnessError
from .models import ExportOptions, FrameReviewRequest, GenerationRequest
from .project_profile import DREAMWEAVER_PROFILE, ProjectAction, project_action_choices
from .service import QA_ALGORITHM_VERSION, SpritePipelineService
from .sheet_inspection import build_grid_overlay, extract_character_reference_frame, inspect_sprite_sheet


UI_CSS = r"""
:root{--muted:#aaa6b8;--panel:rgba(27,25,38,.88);--border:rgba(170,157,255,.24);--accent:#9f83ff;--mint:#63dfc9;--warn:#ffc76b}
.gradio-container{max-width:1220px!important;margin:0 auto!important;padding-bottom:60px!important}
#sprite-hero{padding:25px 28px;margin:8px 0 14px;border:1px solid var(--border);border-radius:22px;background:radial-gradient(circle at 86% 8%,rgba(159,131,255,.23),transparent 35%),linear-gradient(145deg,rgba(31,28,46,.98),rgba(19,18,28,.98));box-shadow:0 18px 60px rgba(0,0,0,.2)}
#sprite-hero h1{margin:0 0 7px;font-size:clamp(28px,4vw,44px);letter-spacing:-.035em}#sprite-hero p{margin:0;color:var(--muted);line-height:1.65;max-width:920px}
.flow-map{display:grid;grid-template-columns:repeat(5,minmax(0,1fr));gap:8px;align-items:stretch;margin-top:18px}.flow-box{padding:9px 8px;border:1px solid var(--border);border-radius:11px;background:rgba(255,255,255,.04);color:#e9e4f6;text-align:center}.flow-box small{display:block;color:var(--mint);font-weight:800;margin-bottom:3px}
.status-bar{display:flex;gap:9px;flex-wrap:wrap;margin:0 0 16px;padding:12px 15px;border:1px solid var(--border);border-radius:14px;background:var(--panel)}.status-bar span{color:var(--muted)}.status-bar b{color:#f0ecfa}
.section-intro{padding:18px 20px;border:1px solid var(--border);border-radius:16px;background:var(--panel);margin:4px 0 15px}.section-intro h2,.section-intro h3{margin:0 0 7px}.section-intro p{margin:0;color:var(--muted);line-height:1.65}
.notice{padding:14px 17px;border-radius:13px;margin:7px 0 13px;line-height:1.6}.notice strong{display:block;margin-bottom:2px}.notice.info{border:1px solid var(--border);background:rgba(159,131,255,.08)}.notice.ok{border:1px solid rgba(99,223,201,.36);background:rgba(99,223,201,.08)}.notice.warn{border:1px solid rgba(255,199,107,.38);background:rgba(255,199,107,.08)}.notice.error{border:1px solid rgba(255,140,164,.42);background:rgba(255,140,164,.09)}
.safety-card{padding:15px 16px;margin:9px 0;border:1px solid var(--border);border-radius:14px;background:rgba(255,255,255,.03)}.safety-card h4{margin:0 0 8px}.safety-card p{margin:4px 0;color:var(--muted);line-height:1.55}.safety-track{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:6px;margin-top:10px}.safety-step{padding:8px 7px;border-radius:9px;background:rgba(255,255,255,.04);text-align:center;color:var(--muted);font-size:12px}.safety-step.done{background:rgba(99,223,201,.12);color:var(--mint)}.safety-step.current{background:rgba(159,131,255,.16);color:#e7defe}.safety-step.problem{background:rgba(255,140,164,.12);color:#ff9caf}.path-list code{user-select:text!important;cursor:text!important;caret-color:auto!important}
.contract-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:10px;margin-top:12px}.contract-card{padding:12px 14px;border-radius:12px;background:rgba(255,255,255,.035)}.contract-card small{display:block;color:var(--muted);margin-bottom:4px}.contract-card b{color:#f2eefb}
.qa-counts{display:flex;gap:8px;flex-wrap:wrap;margin-top:10px}.qa-count{padding:6px 10px;border-radius:999px;background:rgba(255,255,255,.05)}.qa-count.hard{color:#ff9caf}.qa-count.warn{color:#ffd486}.diagnostic-badge{display:inline-block;margin-top:8px;padding:4px 9px;border-radius:999px;color:#2a210f;background:var(--warn);font-size:12px;font-weight:800}
.qa-change{padding:13px 16px;margin:9px 0 14px;border:1px solid var(--border);border-radius:13px;background:rgba(255,255,255,.025)}.qa-change h4{margin:0 0 8px}.qa-change p{margin:5px 0;color:var(--muted)}.qa-change .resolved{color:var(--mint)}.qa-change .new{color:#ff9caf}.qa-change .persisting{color:#ffd486}.qa-change details{margin-top:7px}.qa-change li{margin:4px 0;color:var(--muted)}
.project-table{width:100%;border-collapse:collapse;margin-top:12px}.project-table th,.project-table td{padding:9px 10px;border-bottom:1px solid var(--border);text-align:left}.project-table th{color:#dcd5ef}.project-table td{color:var(--muted)}
.choice-cards,.static-choice,.workflow-tabs{caret-color:transparent!important}.choice-cards label,.choice-cards label *,.static-choice label,.static-choice label *,.workflow-tabs button,.workflow-tabs button *{cursor:pointer!important;user-select:none!important;-webkit-user-select:none!important;caret-color:transparent!important}.static-choice input[role="combobox"],.static-choice input[readonly]{cursor:pointer!important;user-select:none!important;-webkit-user-select:none!important;caret-color:transparent!important}.choice-cards>div>div{gap:9px!important}.choice-cards label{padding:11px 13px!important;border:1px solid var(--border)!important;border-radius:13px!important;background:rgba(255,255,255,.025)!important}.choice-cards label:hover{border-color:rgba(159,131,255,.72)!important;background:rgba(159,131,255,.09)!important}.choice-cards label:has(input:checked){border-color:var(--accent)!important;background:rgba(159,131,255,.14)!important}
.primary-action button{min-height:48px;font-weight:750;border-radius:13px!important}.pixel-preview img,.frame-gallery img,.sheet-preview img{image-rendering:pixelated!important}
.pixel-editor-frame{display:block;width:100%;height:1160px;border:1px solid var(--border);border-radius:16px;background:#15131d}
@media(max-width:760px){.flow-map{grid-template-columns:repeat(2,minmax(0,1fr))}.contract-grid,.safety-track{grid-template-columns:1fr}#sprite-hero{padding:21px 19px}}
"""


PIXEL_EDITOR_BRIDGE_JS = r"""
() => {
  if (window.__spritePixelEditorBridgeInstalled) return [];
  const clickButton = (id) => {
    const root = document.getElementById(id);
    const button = root?.matches("button") ? root : root?.querySelector("button");
    if (button && !button.disabled) button.click();
  };
  window.addEventListener("message", (event) => {
    if (event.origin !== window.location.origin) return;
    if (event.data?.type !== "sprite-pixel-editor-saved") return;
    const sourceFrame = event.source;
    const trustedFrame = Array.from(document.querySelectorAll(".pixel-editor-frame"))
      .some((frame) => frame.contentWindow === event.source);
    if (!trustedFrame) return;
    window.setTimeout(() => {
      const stillCurrent = Array.from(document.querySelectorAll(".pixel-editor-frame"))
        .some((frame) => frame.contentWindow === sourceFrame);
      if (!stillCurrent) return;
      clickButton("refresh-repair-button");
      clickButton("refresh-review-button");
    }, 80);
  });
  window.__spritePixelEditorBridgeInstalled = true;
  return [];
}
"""


JOB_STATUS_CN = {
    "created": "任务已保存",
    "submitting": "正在提交",
    "provider_pending": "模型处理中",
    "saving": "正在安全保存",
    "attention_required": "需要人工恢复",
    "review_required": "结果已保存，等待检查",
    "approved": "已确认",
    "exported": "已导出",
    "failed": "处理失败",
}
CANDIDATE_STATUS_CN = {
    "created": "任务已保存，尚未提交",
    "submitting": "正在提交",
    "submission_unknown": "提交结果未知，已禁止重试",
    "provider_pending": "已提交，模型处理中",
    "saving": "模型已完成，正在安全保存",
    "received": "结果已保存",
    "check_failed": "结果已保存，检查未通过",
    "review_ready": "结果已保存，等待确认",
    "approved": "结果已保存并采用",
    "rejected": "结果已保存但已放弃",
    "failed": "生成失败",
}
REVIEW_STATUS_CN = {"pending": "未判断", "approved": "已通过", "repair_requested": "待修补", "rejected": "不采用"}
PROJECT_INTEGRATION_STATUS_CN = {
    "existing": "现有 16 帧合同",
    "frame_upgrade": "现有动作，Godot 需升级帧列表",
    "new": "新增动作，待 Godot 接线",
}
QA_CODE_CN = {
    "no_frames": "没有找到序列帧", "frame_count_mismatch": "画面数量与动作规格不一致", "frame_size_mismatch": "画面尺寸不一致",
    "missing_alpha": "缺少透明通道", "blank_frame": "画面完全透明", "corrupt_frame": "图片无法读取",
    "consecutive_duplicate_frames": "连续画面完全重复", "touches_canvas_edge": "角色碰到画布边缘", "safe_margin_violation": "角色离画布边缘过近",
    "area_change": "角色可见面积变化较大", "centroid_jump": "角色重心跳动较大", "palette_deviation": "颜色变化较大",
    "loop_endpoint_difference": "循环首尾差异较大", "ground_baseline_drift": "脚底位置发生跳动", "reference_unavailable": "参考图检查被跳过",
    "frame_position_jump": "整个人物在相邻帧之间发生突变式跳位",
    "centroid_velocity_jump": "相邻帧的位置运动趋势发生突变",
    "provider_frame_count_adjusted": "模型返回的帧数与预设不同；已保留全部有效帧并自动补透明空格",
    "palette_unavailable": "色板检查被跳过", "preview_generation_failed": "预览图生成失败",
}
ISSUE_TYPE_CHOICES = [
    ("角色长得不一致", "identity_drift"), ("衣服或配饰变化", "clothing_error"), ("武器不对", "weapon_error"),
    ("肢体异常", "limb_error"), ("动作姿势不对", "pose_error"), ("背景或透明度错误", "alpha_background_error"),
    ("大小或脚底位置跳动", "scale_baseline_error"), ("其他", "other"),
]

REPAIR_FRAME_STATES = {
    "blocked": ("⛔", "仍有阻止问题"),
    "repair": ("🛠", "待修补"),
    "modified": ("✎", "已修改"),
    "approved": ("✓", "已通过"),
    "pending": ("○", "未检查"),
}


def _repair_frame_state(candidate: Any, frame: Any) -> tuple[str, str, str]:
    qa_current = bool(
        candidate.qa_completed_at is not None
        and candidate.qa_input_sha256
        and candidate.qa_algorithm_version == QA_ALGORITHM_VERSION
        and candidate.error is None
    )
    if qa_current and frame.hard_failures:
        key = "blocked"
    elif frame.review_status.value == "repair_requested":
        key = "repair"
    elif frame.review_status.value == "approved":
        key = "approved"
    elif frame.manual_edit_versions > 0 or frame.repair_attempts > 0:
        key = "modified"
    else:
        key = "pending"
    icon, label = REPAIR_FRAME_STATES[key]
    return key, icon, label


def _adjacent_problem_frame_index(
    problem_indices: list[int],
    current_index: int | None,
    direction: int,
) -> int | None:
    if not problem_indices:
        return None
    ordered = list(dict.fromkeys(int(index) for index in problem_indices))
    current = int(current_index) if current_index is not None else None
    if current in ordered:
        position = ordered.index(current)
        return ordered[(position + (1 if direction >= 0 else -1)) % len(ordered)]
    if direction >= 0:
        return next((index for index in ordered if current is None or index > current), ordered[0])
    return next((index for index in reversed(ordered) if current is None or index < current), ordered[-1])


def _repair_qa_change_html(candidate: Any) -> str:
    summary = getattr(candidate, "qa_change_summary", None)
    if summary is None:
        return ""

    groups = (
        ("已解决", "resolved", summary.resolved),
        ("新出现", "new", summary.new),
        ("仍存在", "persisting", summary.persisting),
    )
    detail_rows: list[str] = []
    for title, css_name, issues in groups:
        for issue in issues:
            frame_numbers: set[int] = set()
            if issue.frame_index is not None:
                frame_numbers.add(int(issue.frame_index) + 1)
            raw_indices = issue.metrics.get("frame_indices")
            if isinstance(raw_indices, (list, tuple)):
                for value in raw_indices:
                    try:
                        frame_numbers.add(int(value) + 1)
                    except (TypeError, ValueError):
                        pass
            for key in ("from", "to"):
                try:
                    if issue.metrics.get(key) is not None:
                        frame_numbers.add(int(issue.metrics[key]) + 1)
                except (TypeError, ValueError):
                    pass
            scope = f"第 {'、'.join(str(value) for value in sorted(frame_numbers))} 帧 · " if frame_numbers else ""
            label = QA_CODE_CN.get(issue.code, issue.message or issue.code)
            detail_rows.append(
                f'<li><span class="{css_name}">{title}</span> · {_escape(scope + label)}</li>'
            )
    details = (
        "<details><summary>查看变化明细</summary><ul>" + "".join(detail_rows) + "</ul></details>"
        if detail_rows
        else ""
    )
    return (
        '<div class="qa-change"><h4>修补后复查变化</h4>'
        f'<p><b class="resolved">已解决 {len(summary.resolved)}</b>　'
        f'<b class="new">新出现 {len(summary.new)}</b>　'
        f'<b class="persisting">仍存在 {len(summary.persisting)}</b></p>'
        f"{details}</div>"
    )


def _escape(value: Any) -> str:
    return html.escape(str(value), quote=True)


def _notice(kind: str, title: str, body: str) -> str:
    return f'<div class="notice {kind}"><strong>{_escape(title)}</strong>{_escape(body)}</div>'


def _error_payload(exc: Exception) -> dict[str, Any]:
    if isinstance(exc, HarnessError):
        return {"ok": False, "error": exc.as_dict()}
    return {"ok": False, "error": {"code": "operation_error", "message": str(exc), "details": {"type": type(exc).__name__}}}


def _human_error(exc: Exception) -> str:
    message = str(exc)
    translations = (
        ("API key", "尚未配置 PixelLab API Key。请到“API 与项目”保存后再生成。"),
        ("frame_count", "素材画面数量与所选动作不一致。请确认动作和网格预检结果。"),
        ("wrong size", "上传图片尺寸不正确。修补图必须与当前单帧画布完全一致。"),
        ("alpha channel", "图片必须保留透明通道。请上传透明背景 PNG。"),
        ("completely transparent", "图片完全透明，请换一张包含角色内容的 PNG。"),
        ("warnings; explicit acknowledgement", "这组动画有提醒项。请勾选已查看提醒后再采用。"),
        ("hard failures", "自动检查发现阻止问题，修正后才能采用。"),
        ("repair_requested", "请先在“播放检查”把这帧标记为待修补。"),
        ("export files already exist", "暂存区已有同名文件。确认后可允许覆盖。"),
        ("column count", "Sheet 的列数不符合当前项目固定网格。"),
        ("wrong number of columns", "这张 Sheet 不是当前项目要求的 4 列网格。"),
        ("must be a PNG", "角色原型必须是 PNG 图片。"),
        ("dimensions must be exact multiples", "角色原型既不是 128×128 单帧，也不是规则的 4 列 Sheet。"),
    )
    for needle, translated in translations:
        if needle.casefold() in message.casefold():
            return translated
    return message


def _uploaded_path(value: Any) -> Path:
    if isinstance(value, (str, Path)):
        return Path(value)
    if isinstance(value, dict) and value.get("path"):
        return Path(str(value["path"]))
    name = getattr(value, "name", None) or getattr(value, "path", None)
    if name:
        return Path(str(name))
    raise ValidationHarnessError("uploaded file path is unavailable")


def _candidate_letter(index: int) -> str:
    return chr(ord("A") + index - 1) if 1 <= index <= 26 else str(index)


def _pixel_editor_embed(
    job_id: str | None,
    candidate_index: int | None,
    frame_index: int | None,
) -> str:
    if not job_id or candidate_index is None or frame_index is None:
        return _notice("info", "像素画布尚未打开", "选择一帧待修补画面后，这里会载入精确像素编辑器。")
    query = urlencode(
        {
            "job_id": str(job_id),
            "candidate": int(candidate_index),
            "frame": int(frame_index),
        }
    )
    return (
        f'<iframe class="pixel-editor-frame" src="/pixel-editor?{_escape(query)}" '
        'title="精确像素修补画布" sandbox="allow-scripts allow-same-origin allow-downloads allow-modals"></iframe>'
    )


def build_ui(
    root: str | Path | None = None,
    *,
    service: SpritePipelineService | None = None,
) -> Any:
    """Build a project-guided UI backed by the shared service used by API/CLI."""
    try:
        import gradio as gr
    except ImportError as exc:  # pragma: no cover
        raise ProviderConfigurationError("operator UI requires Gradio; install requirements.txt", details={"dependency": "gradio"}) from exc

    service = service or SpritePipelineService(root)
    profile = DREAMWEAVER_PROFILE
    # Diagnostic jobs stay out of the production history until this browser
    # session explicitly launches one from the Example page.
    visible_diagnostic_jobs: set[str] = set()

    def api_configured() -> bool:
        return bool(service.settings.pixellab_api_key)

    def header_status_html() -> str:
        return (
            '<div class="status-bar">'
            f'<span>当前项目：<b>{_escape(profile.display_name)}</b></span><span>单帧：<b>{profile.cell_width}×{profile.cell_height}</b></span>'
            f'<span>每行：<b>{profile.columns} 帧</b></span><span>PixelLab：<b>{"已保存，尚未调用验证" if api_configured() else "未配置"}</b></span></div>'
        )

    def api_banner_html() -> str:
        if api_configured():
            return _notice("ok", "PixelLab API 已保存", "现在可以生成。首次真实调用成功前，页面不会把它误写成“已连接”。")
        return _notice("warn", "PixelLab API 尚未配置", "请先到“API 与项目”填写 API Key。已有 Sheet 检查、修补和导出不需要 API。")

    def api_settings_status() -> str:
        if api_configured():
            return _notice("ok", "已受保护保存，尚未调用验证", "Key 已由当前 Windows 用户加密保护，页面不会回显完整内容。")
        return _notice("info", "未配置", "只有“生成动画”需要 PixelLab API；其他功能仍可使用。")

    def quota_html(snapshot: dict[str, Any] | None = None) -> str:
        snapshot = snapshot if snapshot is not None else service.get_cached_balance()
        if not snapshot:
            return _notice("info", "额度尚未读取", "点击“刷新额度”后显示 PixelLab 当前剩余生成次数；刷新额度不会消耗生成次数。")
        balance = snapshot.get("balance", {}) if isinstance(snapshot, dict) else {}
        subscription = balance.get("subscription", {}) if isinstance(balance, dict) else {}
        credits = balance.get("credits", {}) if isinstance(balance, dict) else {}

        def first_number(mapping: Any, names: tuple[str, ...]) -> int | float | None:
            if not isinstance(mapping, dict):
                return None
            for name in names:
                value = mapping.get(name)
                if isinstance(value, (int, float)) and not isinstance(value, bool):
                    return value
            return None

        remaining = first_number(
            subscription,
            ("generations", "remaining", "remaining_generations", "generations_remaining"),
        )
        total = first_number(
            subscription,
            ("total", "total_generations", "generations_total"),
        )
        usd = first_number(credits, ("usd",))
        pieces: list[str] = []
        if remaining is not None:
            pieces.append(f"剩余生成次数：{remaining:g}")
        if total is not None:
            pieces.append(f"套餐总次数：{total:g}")
        if usd is not None:
            pieces.append(f"额外余额：${usd:g}")
        checked_at = snapshot.get("checked_at")
        detail = "；".join(pieces) if pieces else "PixelLab 已返回账户信息，但字段格式暂时无法识别。"
        if checked_at:
            detail += f"；读取时间：{checked_at}"
        return _notice("ok", "当前 PixelLab 额度", detail)

    def refresh_quota() -> tuple[str, dict[str, Any]]:
        try:
            snapshot = service.refresh_pixellab_balance()
            return quota_html(snapshot), {"ok": True, "balance": snapshot}
        except Exception as exc:
            cached = service.get_cached_balance()
            body = _human_error(exc)
            if cached:
                body += " 已保留上一次成功读取的额度快照。"
            return _notice("error", "额度读取失败", body), _error_payload(exc)

    def generation_cost_html(count: float, action_id: str | None) -> str:
        resolved = max(1, int(count or 1))
        action = project_action(action_id)
        if action is None:
            return _notice(
                "info",
                "选择动作后显示额度",
                "额度按单帧尺寸和送给模型的帧数计算。",
            )
        per_candidate = service._pixellab_generation_units(
            profile.cell_width,
            profile.cell_height,
            action.provider_frame_count,
        )
        total = per_candidate * resolved
        return _notice(
            "warn" if total > per_candidate else "info",
            f"本次最多消耗 {total} 个 generation 额度",
            f"当前动作每个候选约 {per_candidate} 个额度，共 {resolved} 个候选、{resolved} 次独立提交。系统会在每次提交前读取余额；刷新、查询和取回不消耗额度。",
        )

    def storage_status_html() -> str:
        status = service.storage_status()
        paths = status["paths"]
        migration = status["migration"]
        mode = "便携模式（你显式指定了 --root）" if paths["portable_mode"] else "用户数据隔离模式"
        migration_status = migration.get("status", "unknown")
        migration_label = {
            "complete": "已完成",
            "complete_with_conflicts": "已完成，但有同名内容待确认",
            "incomplete": "未完成",
            "not_required": "无需迁移",
            "portable_mode": "便携模式不迁移",
        }.get(migration_status, str(migration_status))
        legacy_note = (
            "旧任务、角色和导出文件仍完整保留；确认加密副本后，旧明文 Key 会被清除。"
            if migration.get("source_root")
            else "没有需要迁移的旧目录。"
        )
        return (
            '<div class="section-intro path-list"><h3>存储与恢复位置</h3>'
            f"<p><b>{_escape(mode)}</b>。程序代码与用户数据已经分离；{_escape(legacy_note)}</p>"
            f"<p>用户数据：<code>{_escape(paths['data_root'])}</code><br>"
            f"任务与原始结果：<code>{_escape(paths['jobs_dir'])}</code><br>"
            f"用户角色：<code>{_escape(paths['user_characters_dir'])}</code><br>"
            f"最终导出：<code>{_escape(paths['exports_dir'])}</code></p>"
            f"<p>迁移状态：{_escape(migration_label)}；已复制任务 {migration.get('copied_jobs', 0)} 个、"
            f"角色 {migration.get('copied_characters', 0)} 个、导出文件 {migration.get('copied_exports', 0)} 个；"
            f"已识别更新版本 {migration.get('skipped_destination_newer', 0)} 个；"
            f"冲突 {len(migration.get('conflicts', []))} 个，错误 {len(migration.get('errors', []))} 个。</p></div>"
        )

    def refresh_storage_status() -> tuple[str, dict[str, Any]]:
        return storage_status_html(), service.storage_status()

    def official_character_choices() -> list[tuple[str, str]]:
        choices = [
            (str(item["name"]), str(item["id"]))
            for item in service.list_presets()["characters"]
            if item.get("valid", True) and item["id"] != "diagnostic_dummy"
        ]
        choices.sort(key=lambda item: (0 if item[1] == profile.character_id else 1, item[0]))
        return choices

    def character_projection(character_id: str | None) -> tuple[str | None, str]:
        if not character_id:
            return None, _notice("warn", "还没有角色外观参考", "请到“API 与项目”上传一张 128×128 透明 PNG，或从现有 Sheet 选择一格。")
        try:
            character, preset_path = service.presets.load_character(character_id)
            return str(preset_path.parent / character.reference_frame), _notice(
                "ok", f"角色：{character.display_name}", "模型只用这张单帧图保持脸、服装、颜色和武器一致；它不是一套动画。"
            )
        except Exception as exc:
            return None, _notice("error", "角色外观参考不可用", _human_error(exc))

    def project_action(action_id: str | None) -> ProjectAction | None:
        if not action_id:
            return None
        try:
            return profile.action(action_id)
        except KeyError:
            return None

    def action_projection(action_id: str | None) -> str:
        action = project_action(action_id)
        if action is None:
            return _notice("warn", "请选择动作", "动作会自动带入项目的帧数、FPS、循环方式和目标文件名。")
        width, height = action.sheet_size
        layout = (
            "按项目指定格位播放，未使用格保持透明"
            if action.is_sparse
            else "从左到右、从上到下"
        )
        body = (
            f"{action.frame_count} 帧 · {action.fps:g} FPS · {'循环播放' if action.loop else '播放一次'}。"
            f"预计导出 {width}×{height} PNG，{profile.cell_width}×{profile.cell_height}/格，"
            f"{action.columns} 列×{action.rows} 行；{layout}。"
        )
        if action.provider_frame_count != action.frame_count:
            body += f" 模型生成 {action.provider_frame_count} 个连续源帧，Harness 保留为项目需要的 {action.frame_count} 帧。"
        if action.note:
            body += f" {action.note}"
        return _notice("info", f"{action.display_name} → {action.filename}", body)

    def save_api_key(value: str) -> tuple[str, str, str, Any, Any]:
        try:
            if not (value or "").strip():
                raise ValidationHarnessError("请先填写 API Key；如果要删除已保存的 Key，请使用“清除本机 Key”")
            service.configure_pixellab_api_key(value)
            return header_status_html(), api_settings_status(), api_banner_html(), gr.update(interactive=True), gr.update(value="")
        except Exception as exc:
            return header_status_html(), _notice("error", "API Key 没有保存", _human_error(exc)), api_banner_html(), gr.update(interactive=api_configured()), gr.update()

    def clear_api_key() -> tuple[str, str, str, Any, Any]:
        try:
            service.configure_pixellab_api_key(None)
            return header_status_html(), api_settings_status(), api_banner_html(), gr.update(interactive=False), gr.update(value="")
        except Exception as exc:
            return header_status_html(), _notice("error", "没有清除成功", _human_error(exc)), api_banner_html(), gr.update(interactive=api_configured()), gr.update()

    def inspect_generation_reference_source(source: Path) -> tuple[Image.Image, dict[str, Any]]:
        """Return the exact 128px frame that will be sent to the generator."""
        return extract_character_reference_frame(
            source,
            cell_width=profile.cell_width,
            cell_height=profile.cell_height,
            columns=profile.columns,
        )

    def prepare_generation_reference(uploaded: Any, saved_character_id: str | None) -> tuple[Any, str, dict[str, Any]]:
        if uploaded is None:
            reference, _summary = character_projection(saved_character_id)
            if reference:
                return reference, _notice(
                    "info",
                    "当前使用已保存角色",
                    "上传新的角色原型 PNG 后，会改用上传图片；不会修改这个已保存角色。",
                ), {}
            return None, _notice("warn", "还没有角色原型", "请上传一张角色原型 PNG。"), {}
        try:
            source = _uploaded_path(uploaded)
            reference, state = inspect_generation_reference_source(source)
            if state["kind"] == "single":
                detail = f"将直接使用这张 {profile.cell_width}×{profile.cell_height} 透明 PNG。"
            else:
                detail = (
                    f"识别为 {state['sheet_width']}×{state['sheet_height']} Sheet；"
                    f"将自动取第 {state['reference_index'] + 1} 格作为角色第一帧。"
                )
            return reference, _notice("ok", "角色原型已准备好", detail), state
        except Exception as exc:
            return None, _notice("error", "这张角色原型暂时不能使用", _human_error(exc)), {}

    def resolve_generation_character(
        uploaded: Any,
        reference_state: dict[str, Any],
        name: str,
        identity_prompt: str,
        saved_character_id: str | None,
    ) -> tuple[str, dict[str, Any]]:
        if uploaded is None:
            if not saved_character_id:
                raise ValidationHarnessError("请上传角色原型图，或选择一个已保存角色")
            service.presets.load_character(saved_character_id)
            return saved_character_id, {}

        source = _uploaded_path(uploaded).resolve()
        _reference, inspected = inspect_generation_reference_source(source)
        if not reference_state.get("valid") or str(source) != str(Path(str(reference_state.get("path", ""))).resolve()):
            reference_state = inspected
        display_name = (name or "").strip() or "新角色"
        identity = (identity_prompt or "").strip()
        signature = "|".join(
            (str(source), display_name, identity, str(reference_state.get("reference_index", 0)))
        )
        reusable_id = reference_state.get("character_id") if reference_state.get("signature") == signature else None
        if reusable_id:
            try:
                service.presets.load_character(str(reusable_id))
                return str(reusable_id), reference_state
            except Exception:
                pass

        common = dict(
            display_name=display_name,
            facing=profile.facing,
            identity_description=identity,
            character_id=(
                "user_"
                + hashlib.sha256(
                    source.read_bytes()
                    + display_name.encode("utf-8")
                    + identity.encode("utf-8")
                    + str(reference_state.get("reference_index", 0)).encode("ascii")
                ).hexdigest()[:16]
            ),
            sheet_columns=profile.columns,
            anchor_x=profile.anchor_x,
            anchor_ground_y=profile.anchor_ground_y,
            reuse_if_identical=True,
        )
        if reference_state["kind"] == "single":
            preset = service.create_character_preset(reference_image=source, **common)
        else:
            preset = service.create_character_preset_from_sheet(
                sprite_sheet=source,
                cell_size=profile.cell_width,
                reference_frame_index=int(reference_state["reference_index"]),
                **common,
            )
        return preset.character_id, {
            **reference_state,
            "character_id": preset.character_id,
            "signature": signature,
        }

    def job_label(job: Any) -> str:
        source = {"pixellab": "AI 生成", "import": "已有 Sheet", "fixture": "流程示例"}.get(job.request.provider, job.request.provider)
        when = job.updated_at.astimezone().strftime("%m-%d %H:%M")
        character = "流程测试机器人" if job.character.character_id == "diagnostic_dummy" else job.character.display_name
        return f"{source} · {job.action.display_name or job.action.action_id} · {character} · {when} · {JOB_STATUS_CN.get(job.status.value, job.status.value)}"

    def job_summary_label(row: dict[str, Any]) -> str:
        source = {"pixellab": "AI 生成", "import": "已有 Sheet", "fixture": "流程示例"}.get(
            str(row.get("provider", "")), str(row.get("provider", ""))
        )
        try:
            when = datetime.fromisoformat(str(row.get("updated_at", ""))).astimezone().strftime("%m-%d %H:%M")
        except (TypeError, ValueError):
            when = "时间未知"
        character = (
            "流程测试机器人"
            if row.get("character_id") == "diagnostic_dummy"
            else str(row.get("character_name") or row.get("character_id") or "未知角色")
        )
        candidate_count = int(row.get("candidate_count") or 0)
        saved_count = int(row.get("saved_candidate_count") or 0)
        candidate_note = f"{saved_count}/{candidate_count} 个候选已保存" if candidate_count else "尚无候选"
        status = JOB_STATUS_CN.get(str(row.get("status", "")), str(row.get("status", "")))
        return (
            f"{source} · {row.get('action_name') or row.get('action_id')} · {character} · "
            f"{candidate_note} · {when} · {status}"
        )

    def job_choices(*, approved_only: bool = False, repair_only: bool = False) -> list[tuple[str, str]]:
        result: list[tuple[str, str]] = []
        for row in service.list_jobs():
            job_id = str(row.get("job_id", ""))
            if row.get("status") == "invalid":
                continue
            if row.get("character_id") == "diagnostic_dummy" and job_id not in visible_diagnostic_jobs:
                continue
            if approved_only and int(row.get("approved_candidate_count") or 0) < 1:
                continue
            if repair_only and int(row.get("repair_frame_count") or 0) < 1:
                continue
            result.append((job_summary_label(row), job_id))
        return result

    def saved_asset_choices() -> list[tuple[str, str]]:
        choices: list[tuple[str, str]] = []
        for row in service.list_jobs():
            job_id = str(row.get("job_id", ""))
            if row.get("status") == "invalid" or row.get("provider") == "fixture":
                continue
            if row.get("character_id") == "diagnostic_dummy" and job_id not in visible_diagnostic_jobs:
                continue
            choices.append((job_summary_label(row), job_id))
        return choices

    def saved_asset_catalog_projection(job_id: str | None) -> str:
        if not job_id:
            return _notice(
                "info",
                "还没有选择任务",
                "启动时只读取轻量摘要。选择或打开任务后，才会读取候选、帧和详细记录。",
            )
        row = next(
            (item for item in service.list_jobs() if str(item.get("job_id")) == str(job_id)),
            None,
        )
        if row is None or row.get("status") == "invalid":
            return _notice("error", "任务摘要不可用", "任务文件夹存在，但轻量摘要无法读取。")
        candidate_count = int(row.get("candidate_count") or 0)
        saved_count = int(row.get("saved_candidate_count") or 0)
        frame_count = int(row.get("total_frame_count") or 0)
        repair_count = int(row.get("repair_frame_count") or 0)
        return _notice(
            "info",
            f"{row.get('action_name') or row.get('action_id')} · {JOB_STATUS_CN.get(str(row.get('status')), str(row.get('status')))}",
            f"任务文件夹 {row['job_id']}；{candidate_count} 个候选中 {saved_count} 个已有画面，共 {frame_count} 帧，{repair_count} 帧待修补。当前只读取了摘要。",
        )

    def task_center_projection(job_id: str | None) -> tuple[str, dict[str, Any], Any]:
        if not job_id:
            return (
                _notice("info", "还没有真实生成任务", "提交后任务会立即保存到本机；刷新或重新打开页面仍会出现在这里。"),
                {},
                gr.update(choices=[], value=None, interactive=False),
            )
        try:
            job = service.get_job(str(job_id))
            cards: list[str] = []
            attach_choices: list[tuple[str, int]] = []
            integrity_problem = False
            for candidate in job.candidates:
                safety = service.candidate_safety(job.job_id, candidate.candidate_index)
                stage = safety["stage"]
                submitted = bool(safety["provider_job_id"] or safety["submitted_at"] or safety["result_saved_at"])
                provider_done = bool(safety["provider_completed_at"] or safety["result_saved_at"])
                saved = bool(safety["result_saved_at"])
                unknown = stage == "submission_unknown"
                failed = stage == "failed"

                def step_class(done: bool, current: bool = False, problem: bool = False) -> str:
                    if problem:
                        return "problem"
                    if done:
                        return "done"
                    return "current" if current else ""

                remote = safety["provider_job_id"] or "尚未取得"
                detail = (
                    f"远端任务编号：{remote}；本地提交次数：{safety['submission_attempts']}/1。"
                )
                if saved:
                    integrity = "校验通过" if safety["result_integrity"] else "校验异常"
                    integrity_problem = integrity_problem or not bool(safety["result_integrity"])
                    detail += f" 保存时间：{safety['result_saved_at']}；完整性：{integrity}。"
                elif candidate.error:
                    detail += f" 当前说明：{_human_error(Exception(candidate.error.get('message', '')))}。"
                cards.append(
                    '<div class="safety-card">'
                    f"<h4>候选 {_candidate_letter(candidate.candidate_index)} · {_escape(CANDIDATE_STATUS_CN.get(candidate.status.value, candidate.status.value))}</h4>"
                    f"<p>{_escape(detail)}</p>"
                    '<div class="safety-track">'
                    f'<div class="safety-step {step_class(True)}">1. 任务已保存</div>'
                    f'<div class="safety-step {step_class(submitted, stage == "submitting", unknown)}">2. 已提交</div>'
                    f'<div class="safety-step {step_class(provider_done, stage == "processing", failed)}">3. 模型处理</div>'
                    f'<div class="safety-step {step_class(saved, stage == "saving", failed and provider_done)}">4. 结果已保存</div>'
                    "</div></div>"
                )
                if unknown and not safety["provider_job_id"]:
                    attach_choices.append(
                        (f"候选 {_candidate_letter(candidate.candidate_index)}", candidate.candidate_index)
                    )
            title_kind = "error" if job.status.value in {"failed", "attention_required"} or integrity_problem else "ok" if any(c.result_saved_at for c in job.candidates) else "info"
            header = _notice(
                title_kind,
                f"任务 {job.job_id}",
                f"{JOB_STATUS_CN.get(job.status.value, job.status.value)}。页面刷新不会删除此任务；后台只会查询或保存，绝不会自动重复收费提交。",
            )
            return (
                header + "".join(cards),
                {"ok": True, "job": job.model_dump(mode="json")},
                gr.update(
                    choices=attach_choices,
                    value=attach_choices[0][1] if attach_choices else None,
                    interactive=bool(attach_choices),
                ),
            )
        except Exception as exc:
            return (
                _notice("error", "任务安全记录无法读取", _human_error(exc)),
                _error_payload(exc),
                gr.update(choices=[], value=None, interactive=False),
            )

    def task_job_update(preferred: str | None = None) -> Any:
        choices = saved_asset_choices()
        values = {value for _label, value in choices}
        selected = preferred if preferred in values else choices[0][1] if choices else None
        return gr.update(choices=choices, value=selected)

    def attach_remote_job(
        job_id: str | None,
        candidate_index: int | None,
        provider_job_id: str,
    ) -> tuple[str, Any, str, dict[str, Any], Any, Any]:
        try:
            if not job_id or candidate_index is None:
                raise ValidationHarnessError("请先选择需要恢复的候选")
            if not provider_job_id.strip():
                raise ValidationHarnessError("请填写 PixelLab 返回的远端任务编号")
            job = service.attach_provider_job_id(
                str(job_id),
                int(candidate_index),
                provider_job_id,
            )
            job = service.generate_job(job.job_id, wait=False, candidate_index=int(candidate_index))
            projection = task_center_projection(job.job_id)
            return (
                _notice("ok", "远端任务已绑定", "刚才只查询了已有任务，没有创建新的收费生成。"),
                task_job_update(job.job_id),
                *projection,
                gr.update(value=""),
            )
        except Exception as exc:
            projection = task_center_projection(job_id)
            return (
                _notice("error", "远端任务没有绑定", _human_error(exc)),
                task_job_update(job_id),
                *projection,
                gr.update(),
            )

    def candidate_choices(job: Any, *, approved_only: bool = False, repair_only: bool = False) -> list[tuple[str, int]]:
        result: list[tuple[str, int]] = []
        for candidate in job.candidates:
            if repair_only and (
                candidate.status.value in {"approved", "rejected", "failed"}
                or (job.export and job.export.candidate_index == candidate.candidate_index)
            ):
                continue
            if approved_only and candidate.status.value != "approved":
                continue
            if repair_only and not any(frame.review_status.value == "repair_requested" for frame in candidate.frames):
                continue
            recoverable = (
                candidate.status.value == "failed"
                and candidate.provider_status == "completed"
                and bool(candidate.provider_job_id)
                and not candidate.frames
            )
            recovery_label = " · 可取回已完成结果" if recoverable else ""
            result.append((f"生成结果 {_candidate_letter(candidate.candidate_index)} · {CANDIDATE_STATUS_CN.get(candidate.status.value, candidate.status.value)}{recovery_label}", candidate.candidate_index))
        return result

    def default_candidate(job: Any, *, approved_only: bool = False, repair_only: bool = False) -> int | None:
        choices = candidate_choices(job, approved_only=approved_only, repair_only=repair_only)
        if not choices:
            return None
        if job.export and any(value == job.export.candidate_index for _label, value in choices):
            return job.export.candidate_index
        return int(choices[0][1])

    def saved_asset_projection(
        job_id: str | None,
        candidate_index: int | None = None,
    ) -> tuple[Any, str, str | None, list[tuple[str, str]], Any, Any]:
        empty = (
            gr.update(choices=[], value=None, visible=False),
            _notice(
                "info",
                "尚未打开任务内容",
                "上方目录只有轻量摘要。点击“打开所选任务”后，才会读取候选和逐帧图片。",
            ),
            None,
            [],
            gr.update(interactive=False),
            gr.update(interactive=False),
        )
        if not job_id:
            return empty
        try:
            job = service.get_job(str(job_id))
            choices = candidate_choices(job)
            values = {int(value) for _label, value in choices}
            requested = int(candidate_index) if candidate_index is not None else None
            selected = requested if requested in values else default_candidate(job)
            if selected is None:
                return (
                    gr.update(choices=[], value=None, visible=False),
                    _notice("info", "任务尚无候选内容", "任务记录已经保存，但模型结果还没有写入本机。"),
                    None,
                    [],
                    gr.update(interactive=False),
                    gr.update(interactive=False),
                )
            candidate = next(item for item in job.candidates if item.candidate_index == selected)
            qa_current = bool(
                candidate.qa_completed_at is not None
                and candidate.qa_input_sha256
                and candidate.qa_algorithm_version == QA_ALGORITHM_VERSION
                and candidate.error is None
            )
            prefix = service.store.job_dir(job.job_id) / "previews" / candidate.candidate_id
            preview_path = prefix.with_suffix(".zoom.gif")
            if not preview_path.is_file():
                preview_path = prefix.with_suffix(".preview.gif")
            preview = str(preview_path) if qa_current and preview_path.is_file() else None
            gallery: list[tuple[str, str]] = []
            for frame in candidate.frames:
                frame_path = service.store.resolve_job_path(job.job_id, frame.active_path)
                if frame_path.is_file():
                    gallery.append(
                        (
                            str(frame_path),
                            f"第 {frame.index + 1} 帧 · {REVIEW_STATUS_CN.get(frame.review_status.value, frame.review_status.value)}",
                        )
                    )
            repairable = bool(
                candidate.status.value not in {"approved", "rejected", "failed"}
                and not (job.export and job.export.candidate_index == candidate.candidate_index)
                and any(frame.review_status.value == "repair_requested" for frame in candidate.frames)
            )
            source = {"pixellab": "AI 生成", "import": "已有 Sheet", "fixture": "流程示例"}.get(
                job.request.provider, job.request.provider
            )
            summary = (
                '<div class="section-intro">'
                f"<h3>{_escape(job.action.display_name or job.action.action_id)} · 候选 {_candidate_letter(selected)}</h3>"
                f"<p>来源：{_escape(source)}；当前候选 {len(candidate.frames)} 帧；任务内共 {len(job.candidates)} 个候选，全部保存在同一个任务文件夹中。</p>"
                f'<p class="path-list">任务文件夹：<code>{_escape(service.store.job_dir(job.job_id))}</code></p>'
                f'<div class="qa-counts"><span class="qa-count">{_escape(CANDIDATE_STATUS_CN.get(candidate.status.value, candidate.status.value))}</span>'
                f'<span class="qa-count hard">{len(candidate.hard_failures)} 个阻止问题</span>'
                f'<span class="qa-count warn">{len(candidate.warnings)} 条提醒</span></div></div>'
            )
            if candidate.frames and not qa_current:
                summary += _notice(
                    "warn",
                    "动画预览需要重新检查",
                    "逐帧原图仍可查看；动态预览会在播放检查重新运行后更新，不会调用生成 API。",
                )
            return (
                gr.update(choices=choices, value=selected, visible=len(choices) > 1),
                summary,
                preview,
                gallery,
                gr.update(interactive=bool(candidate.frames)),
                gr.update(interactive=repairable),
            )
        except Exception as exc:
            return (
                gr.update(choices=[], value=None, visible=False),
                _notice("error", "任务内容无法打开", _human_error(exc)),
                None,
                [],
                gr.update(interactive=False),
                gr.update(interactive=False),
            )

    def open_saved_asset(job_id: str | None, candidate_index: int | None = None) -> tuple[Any, ...]:
        return (
            saved_asset_catalog_projection(job_id),
            *saved_asset_projection(job_id, candidate_index),
            *task_center_projection(job_id),
        )

    def select_saved_asset_summary(job_id: str | None) -> tuple[Any, ...]:
        """Change catalog selection without opening the full task payload."""
        return (
            saved_asset_catalog_projection(job_id),
            *saved_asset_projection(None),
            *task_center_projection(None),
        )

    def reload_saved_asset_catalog(current: str | None) -> tuple[Any, str]:
        choices = saved_asset_choices()
        values = {value for _label, value in choices}
        selected = current if current in values else choices[0][1] if choices else None
        return (
            gr.update(choices=choices, value=selected),
            saved_asset_catalog_projection(selected),
        )

    def refresh_saved_assets(
        current: str | None,
        candidate_index: int | None,
    ) -> tuple[Any, ...]:
        try:
            service.recover_pending_jobs()
        except Exception:
            pass
        choices = saved_asset_choices()
        values = {value for _label, value in choices}
        selected = current if current in values else choices[0][1] if choices else None
        return (
            gr.update(choices=choices, value=selected),
            *open_saved_asset(selected, candidate_index if selected == current else None),
        )

    def issue_markdown(candidate: Any) -> str:
        if not candidate.hard_failures and not candidate.warnings:
            return "### 自动检查明细\n\n没有发现阻止问题或提醒。仍请人工确认角色、服装、武器、肢体和动作意图。"
        lines = ["### 自动检查明细"]
        if candidate.hard_failures:
            lines.append("\n**必须先解决**")
            for item in candidate.hard_failures:
                frame = f"（第 {item.frame_index + 1} 帧）" if item.frame_index is not None else ""
                lines.append(f"- {QA_CODE_CN.get(item.code, item.code)}{frame}")
        if candidate.warnings:
            lines.append("\n**请重点留意**")
            for item in candidate.warnings:
                frame = f"（第 {item.frame_index + 1} 帧）" if item.frame_index is not None else ""
                lines.append(f"- {QA_CODE_CN.get(item.code, item.code)}{frame}")
        lines.append("\n自动检查无法替你判断角色身份、服装、武器和肢体是否符合美术要求。")
        return "\n".join(lines)

    def selected_frame_html(job: Any, candidate: Any, frame_index: int) -> str:
        if not candidate.frames:
            return _notice("info", "还没有画面", "等待生成完成或先导入一张 Sheet。")
        frame_index = max(0, min(frame_index, len(candidate.frames) - 1))
        frame = candidate.frames[frame_index]
        issues = len(frame.hard_failures) + len(frame.warnings)
        return _notice(
            "info",
            f"第 {frame.index + 1} 帧",
            f"人工状态：{REVIEW_STATUS_CN.get(frame.review_status.value, frame.review_status.value)}；"
            f"自动提示 {issues} 项；手工像素版本 {frame.manual_edit_versions} 个；"
            f"外部/未来 AI 替换 {frame.repair_attempts}/2 次。",
        )

    def review_payload(job_id: str | None, candidate_index: int | None = None) -> tuple[Any, ...]:
        empty = (
            gr.update(choices=[], value=None, visible=False), None, [], _notice("info", "还没有可检查的动画", "请先到“生成动画”生成，或在本页上传一张已有 Sheet。"),
            "### 自动检查明细\n\n任务完成后会显示在这里。", {}, 0, _notice("info", "尚未选择画面", "点击下方任意帧查看。"),
            gr.update(visible=False, value=False), gr.update(interactive=False), None, None, gr.update(visible=False),
            gr.update(interactive=False), gr.update(interactive=False), gr.update(interactive=False),
        )
        if not job_id:
            return empty
        try:
            job = service.get_job(str(job_id))
            selected = int(candidate_index) if candidate_index else default_candidate(job)
            if selected is None:
                return empty
            candidate = next(item for item in job.candidates if item.candidate_index == selected)
            integrity_ok = True
            if job.request.provider != "import":
                safety = service.candidate_safety(job.job_id, selected)
                integrity_ok = safety["result_integrity"] is True
                # The safety read may recover old commit metadata.
                job = service.get_job(job.job_id)
                candidate = next(item for item in job.candidates if item.candidate_index == selected)
            choices = candidate_choices(job)
            prefix = service.store.job_dir(job.job_id) / "previews" / candidate.candidate_id
            gallery = [
                (str(service.store.resolve_job_path(job.job_id, frame.active_path)), f"第 {frame.index + 1} 帧 · {REVIEW_STATUS_CN.get(frame.review_status.value, frame.review_status.value)}")
                for frame in candidate.frames
            ]
            qa_current = bool(
                candidate.qa_completed_at is not None
                and candidate.qa_input_sha256
                and candidate.qa_algorithm_version == QA_ALGORITHM_VERSION
                and candidate.error is None
                and integrity_ok
            )
            hard_count = len(candidate.hard_failures) if qa_current else 0
            warning_count = len(candidate.warnings) if qa_current else 0
            source = {"pixellab": "AI 生成", "import": "已有 Sheet", "fixture": "流程示例"}.get(job.request.provider, job.request.provider)
            diagnostic = '<span class="diagnostic-badge">仅供流程测试，不可作为游戏美术</span>' if candidate.diagnostic_only else ""
            summary = (
                '<div class="section-intro">'
                f"<h3>{_escape(job.action.display_name or job.action.action_id)} · {_escape(CANDIDATE_STATUS_CN.get(candidate.status.value, candidate.status.value))}</h3>"
                f"<p>来源：{_escape(source)} · {len(candidate.frames)} 帧 · {job.action.fps:g} FPS · {'循环' if job.action.loop else '单次'}</p>"
                f'<div class="qa-counts"><span class="qa-count hard">{hard_count} 个阻止问题</span><span class="qa-count warn">{warning_count} 条提醒</span></div>{diagnostic}</div>'
            )
            if not integrity_ok:
                summary += _notice(
                    "error",
                    "原始生成结果完整性异常",
                    "为保护已生成资产，当前候选已停止复检、批准和导出。请先从备份恢复原始结果文件。",
                )
            elif not qa_current:
                summary += _notice(
                    "warn",
                    "当前版本尚未完成本机检查",
                    "旧版本的动画预览和问题计数已隐藏。点击“重新运行本机检查”即可重建，不会调用生成 API。",
                )
            status = candidate.status.value
            recheck_enabled = integrity_ok and bool(candidate.frames) and (
                status in {"received", "check_failed", "review_ready"}
                or (
                    status == "approved"
                    and not (job.export and job.export.candidate_index == candidate.candidate_index)
                    and not qa_current
                )
            )
            mark_ok_enabled = qa_current and status == "review_ready"
            mark_repair_enabled = qa_current and status in {"review_ready", "check_failed"}
            return (
                gr.update(choices=choices, value=selected, visible=len(choices) > 1),
                str(prefix.with_suffix(".zoom.gif")) if qa_current and prefix.with_suffix(".zoom.gif").is_file() else None,
                gallery, summary,
                issue_markdown(candidate) if qa_current else "### 自动检查明细\n\n当前版本尚未完成本机检查；旧版本问题已隐藏。",
                {"ok": True, "job": job.model_dump(mode="json")}, 0,
                selected_frame_html(job, candidate, 0), gr.update(visible=warning_count > 0, value=False),
                gr.update(interactive=qa_current and status == "review_ready" and hard_count == 0),
                str(prefix.with_suffix(".overlay.png")) if qa_current and prefix.with_suffix(".overlay.png").is_file() else None,
                str(prefix.with_suffix(".baseline.png")) if qa_current and prefix.with_suffix(".baseline.png").is_file() else None,
                gr.update(visible=len(choices) > 1),
                gr.update(interactive=recheck_enabled),
                gr.update(interactive=mark_ok_enabled),
                gr.update(interactive=mark_repair_enabled),
            )
        except Exception as exc:
            return gr.update(), None, [], _notice("error", "动画无法加载", _human_error(exc)), "", _error_payload(exc), 0, _notice("error", "无法选择画面", _human_error(exc)), gr.update(visible=False, value=False), gr.update(interactive=False), None, None, gr.update(visible=False), gr.update(interactive=False), gr.update(interactive=False), gr.update(interactive=False)

    def review_job_update(preferred: str | None = None) -> Any:
        choices = job_choices()
        values = {value for _label, value in choices}
        selected = preferred if preferred in values else choices[0][1] if choices else None
        return gr.update(choices=choices, value=selected)

    def generate_animation(
        uploaded_reference: Any,
        reference_state: dict[str, Any],
        character_name: str,
        identity_prompt: str,
        saved_character_id: str | None,
        action_id: str,
        count: float,
        description: str,
        seed_text: str,
        request_key: str,
    ) -> tuple[Any, ...]:
        job = None
        updated_reference_state = reference_state or {}
        try:
            if not api_configured():
                raise ValidationHarnessError("PixelLab API key is not configured")
            if not action_id:
                raise ValidationHarnessError("请选择要生成的动作")
            character_id, updated_reference_state = resolve_generation_character(
                uploaded_reference,
                updated_reference_state,
                character_name,
                identity_prompt,
                saved_character_id,
            )
            seed = int(seed_text.strip()) if seed_text and seed_text.strip() else None
            job = service.create_job(GenerationRequest(
                character_id=character_id, action_id=action_id, provider="pixellab", candidate_count=int(count or 1), seed=seed,
                action_description=(description or "").strip() or None,
                request_key=request_key,
            ))
            job = service.generate_job(job.job_id, wait=False)
            pending = any(item.status.value in {"provider_pending", "saving"} for item in job.candidates)
            asset_projection = saved_asset_projection(job.job_id)
            task_projection = task_center_projection(job.job_id)
            return (
                _notice(
                    "info" if pending else "ok",
                    "任务已保存并提交" if pending else "结果已安全保存",
                    "现在可以刷新或关闭页面；后台会继续查询并在完成后校验保存，不会重复提交。"
                    if pending
                    else "结果已进入“播放检查”，请播放整段动画并逐帧确认。",
                ),
                {"ok": True, "job": job.model_dump(mode="json")},
                updated_reference_state,
                gr.update(choices=official_character_choices(), value=character_id),
                uuid.uuid4().hex,
                task_job_update(job.job_id),
                saved_asset_catalog_projection(job.job_id),
                *asset_projection,
                *task_projection,
                review_job_update(job.job_id),
                *review_payload(job.job_id),
            )
        except Exception as exc:
            job_id = job.job_id if job is not None else None
            asset_projection = saved_asset_projection(job_id)
            task_projection = task_center_projection(job_id)
            keep_request_key = False
            if job_id:
                try:
                    persisted = service.get_job(job_id)
                    keep_request_key = any(
                        candidate.submission_attempts > 0
                        for candidate in persisted.candidates
                    )
                except Exception:
                    keep_request_key = True
            return (
                _notice("error", "生成没有完成", _human_error(exc)),
                _error_payload(exc),
                updated_reference_state,
                gr.update(),
                request_key if keep_request_key else uuid.uuid4().hex,
                task_job_update(job_id),
                saved_asset_catalog_projection(job_id),
                *asset_projection,
                *task_projection,
                review_job_update(job_id),
                *review_payload(job_id),
            )

    def inspect_uploaded_sheet(uploaded: Any, action_id: str | None) -> tuple[Any, str, dict[str, Any], Any]:
        if uploaded is None:
            return None, _notice("info", "等待上传", "请选择一张透明 PNG Sprite Sheet。"), {}, gr.update(interactive=False)
        try:
            source = _uploaded_path(uploaded)
            result = inspect_sprite_sheet(source, cell_width=profile.cell_width, cell_height=profile.cell_height, columns=profile.columns)
            action = project_action(action_id)
            problems: list[str] = []
            compatibility_notes: list[str] = []
            occupied_cells = {
                (index % result["columns"], index // result["columns"])
                for index, bounds in enumerate(result["cell_bounds"])
                if bounds is not None
            }
            selected_cells: list[tuple[int, int]] = []
            layout_kind = "unselected"
            if action is None:
                problems.append("还没有选择动画类型")
            elif not occupied_cells:
                problems.append("Sheet 中没有找到任何有内容的格子")
            else:
                current_cells = list(action.frame_cells)
                legacy_cells = list(action.legacy_frame_cells)
                if (
                    (result["width"], result["height"]) == action.sheet_size
                    and occupied_cells == set(current_cells)
                ):
                    selected_cells = current_cells
                    layout_kind = "current_16"
                elif (
                    action.legacy_sheet_rows is not None
                    and result["rows"] == action.legacy_sheet_rows
                    and legacy_cells
                    and occupied_cells == set(legacy_cells)
                ):
                    selected_cells = legacy_cells
                    layout_kind = "known_legacy"
                    compatibility_notes.append(
                        f"识别为“{action.display_name}”旧版 {len(legacy_cells)} 帧布局；将保留原播放顺序进入检查"
                    )
                else:
                    selected_cells = sorted(occupied_cells, key=lambda cell: (cell[1], cell[0]))
                    layout_kind = "detected_visible_cells"
                    compatibility_notes.append(
                        f"这不是新的 16 帧标准 Sheet；将按从左到右、从上到下的 {len(selected_cells)} 个可见格进入检查"
                    )
            occupied_count = len(occupied_cells)
            order_text = (
                " → ".join(
                    f"F{index + 1}=第{row + 1}行第{column + 1}格"
                    for index, (column, row) in enumerate(selected_cells)
                )
                if selected_cells
                else "选择动作后显示"
            )
            summary = (
                '<div class="section-intro"><h3>网格预检</h3>'
                f"<p>图片尺寸：{result['width']}×{result['height']}；已识别：{profile.cell_width}×{profile.cell_height}/格 · "
                f"{result['columns']} 列×{result['rows']} 行 · {occupied_count} 个有内容的格。</p>"
                f"<p>实际播放顺序：{_escape(order_text)}</p>"
            )
            if problems:
                summary += f'<div class="notice error"><strong>暂时不能加入检查</strong>{_escape("；".join(problems))}</div>'
            elif compatibility_notes:
                assert action is not None
                summary += f'<div class="notice warn"><strong>兼容旧版或非标准帧数</strong>{_escape("；".join(compatibility_notes))}。动作仍按“{_escape(action.display_name)}”的 {action.fps:g} FPS、{"循环" if action.loop else "单次"}方式播放。</div>'
            else:
                assert action is not None
                summary += f'<div class="notice ok"><strong>符合新的统一规格</strong>这是完整 16 帧、4×4 Sheet；将按“{_escape(action.display_name)}”的 {action.fps:g} FPS、{"循环" if action.loop else "单次"}方式进入检查。</div>'
            summary += "</div>"
            state = {
                **result,
                "valid": not problems,
                "action_id": action_id,
                "frame_cells": [list(cell) for cell in selected_cells],
                "layout_kind": layout_kind,
            }
            return build_grid_overlay(
                source,
                result,
                frame_cells=selected_cells or None,
            ), summary, state, gr.update(interactive=not problems)
        except Exception as exc:
            return None, _notice("error", "无法识别这张 Sheet", _human_error(exc)), {}, gr.update(interactive=False)

    def import_sheet(uploaded: Any, action_id: str, inspection: dict[str, Any]) -> tuple[Any, ...]:
        job = None
        try:
            if uploaded is None or not inspection.get("valid"):
                raise ValidationHarnessError("请先完成网格预检并选择匹配的动画类型")
            source = _uploaded_path(uploaded).resolve()
            if str(source) != str(Path(str(inspection.get("path", ""))).resolve()) or action_id != inspection.get("action_id"):
                raise ValidationHarnessError("上传文件或动画类型已变化，请重新进行网格预检")
            frame_cells = [
                (int(cell[0]), int(cell[1]))
                for cell in inspection.get("frame_cells", [])
            ]
            if not frame_cells:
                raise ValidationHarnessError("网格预检没有提供可导入的播放格位")
            job = service.create_job(GenerationRequest(
                character_id=profile.character_id, action_id=action_id, provider="import", candidate_count=1,
            ))
            job = service.ingest_candidate(
                job.job_id,
                1,
                source,
                source_kind="sheet",
                columns=profile.columns,
                frame_cells=frame_cells,
            )
            return _notice("ok", "Sheet 已切分并加入检查", "请继续在本页播放整段动画，再决定采用或修补。"), {"ok": True, "job": job.model_dump(mode="json")}, review_job_update(job.job_id), *review_payload(job.job_id)
        except Exception as exc:
            job_id = job.job_id if job is not None else None
            return _notice("error", "已有 Sheet 没有加入检查", _human_error(exc)), _error_payload(exc), review_job_update(job_id), *review_payload(job_id)

    def refresh_review(current: str | None) -> tuple[Any, ...]:
        choices = job_choices()
        values = {value for _label, value in choices}
        selected = current if current in values else choices[0][1] if choices else None
        return gr.update(choices=choices, value=selected), *review_payload(selected)

    def recover_provider_result(
        job_id: str | None,
        candidate_index: int | None,
    ) -> tuple[Any, ...]:
        try:
            if not api_configured():
                raise ValidationHarnessError("PixelLab API key is not configured")
            if not job_id:
                raise ValidationHarnessError("请先选择要取回的任务")
            job = service.get_job(str(job_id))
            selected = int(candidate_index) if candidate_index else None
            if selected is None:
                selected = next(
                    (
                        item.candidate_index
                        for item in job.candidates
                        if item.status.value == "failed"
                        and item.provider_status == "completed"
                        and item.provider_job_id
                        and not item.frames
                    ),
                    None,
                )
            if selected is None:
                raise ValidationHarnessError("所选任务没有可取回的已完成结果")
            job = service.recover_completed_candidate(job.job_id, selected)
            candidate = next(item for item in job.candidates if item.candidate_index == selected)
            pending = candidate.status.value == "provider_pending"
            return (
                _notice(
                    "info" if pending else "ok",
                    "正在读取已有结果" if pending else "已取回已有结果",
                    "没有创建新的生成任务；请稍后再点一次此按钮。"
                    if pending
                    else f"没有创建新的生成任务；已保留 {len(candidate.frames)} 个有效帧。",
                ),
                review_job_update(job.job_id),
                *review_payload(job.job_id, selected),
            )
        except Exception as exc:
            return (
                _notice("error", "已有结果没有取回", _human_error(exc)),
                review_job_update(job_id),
                *review_payload(job_id, candidate_index),
            )

    def select_frame(job_id: str | None, candidate_index: int | None, evt: gr.SelectData) -> tuple[int, str]:
        try:
            raw_index, raw_value = getattr(evt, "index", 0), getattr(evt, "value", None)
            caption = str(raw_value.get("caption") or raw_value.get("label") or "") if isinstance(raw_value, dict) else str(raw_value[1]) if isinstance(raw_value, (list, tuple)) and len(raw_value) > 1 else ""
            match = re.search(r"第\s*(\d+)\s*帧", caption)
            frame_index = int(match.group(1)) - 1 if match else int(raw_index[-1]) if isinstance(raw_index, (list, tuple)) else int(raw_index)
            job = service.get_job(str(job_id))
            candidate = next(item for item in job.candidates if item.candidate_index == int(candidate_index))
            return frame_index, selected_frame_html(job, candidate, frame_index)
        except Exception as exc:
            return 0, _notice("error", "无法选择这帧", _human_error(exc))

    def mark_frame(job_id: str | None, candidate_index: int | None, frame_index: int, status: str, issue_type: str, note: str) -> tuple[Any, ...]:
        try:
            service.review_frame(str(job_id), int(candidate_index), FrameReviewRequest(
                frame_index=int(frame_index), status=status, issue_type=issue_type if status == "repair_requested" else None,
                note=note or "", reviewer="web_user",
            ))
            message = "这帧已加入“逐帧修补”列表。" if status == "repair_requested" else "这帧已标记为没有问题。"
            repairs = job_choices(repair_only=True)
            selected = str(job_id) if any(value == str(job_id) for _label, value in repairs) else repairs[0][1] if repairs else None
            return (
                _notice("ok", "判断已保存", message),
                *review_payload(str(job_id), int(candidate_index)),
                gr.update(choices=repairs, value=selected),
                *repair_projection(selected, int(candidate_index) if selected == str(job_id) else None, int(frame_index) if selected == str(job_id) else None),
            )
        except Exception as exc:
            repairs = job_choices(repair_only=True)
            selected = str(job_id) if any(value == str(job_id) for _label, value in repairs) else repairs[0][1] if repairs else None
            return (
                _notice("error", "没有保存成功", _human_error(exc)),
                *review_payload(job_id, candidate_index),
                gr.update(choices=repairs, value=selected),
                *repair_projection(selected),
            )

    def approve_candidate(job_id: str | None, candidate_index: int | None, acknowledge: bool) -> tuple[Any, ...]:
        try:
            service.approve_candidate(str(job_id), int(candidate_index), reviewer="web_user", acknowledge_warnings=bool(acknowledge))
            return _notice("ok", "这组动画已通过", "现在可以到“导出”生成固定网格 PNG Sprite Sheet。"), *review_payload(str(job_id), int(candidate_index)), gr.update(choices=job_choices(approved_only=True), value=str(job_id)), *export_projection(str(job_id), int(candidate_index))
        except Exception as exc:
            return _notice("error", "还不能采用这组动画", _human_error(exc)), *review_payload(job_id, candidate_index), gr.update(choices=job_choices(approved_only=True)), *export_projection(None)

    def reject_candidate(job_id: str | None, candidate_index: int | None, note: str) -> tuple[Any, ...]:
        try:
            service.reject_candidate(str(job_id), int(candidate_index), reviewer="web_user", note=note or "")
            return _notice("ok", "已放弃这组结果", "其他生成结果和原始文件仍保留。"), *review_payload(str(job_id), int(candidate_index))
        except Exception as exc:
            return _notice("error", "暂时无法放弃", _human_error(exc)), *review_payload(job_id, candidate_index)

    def recheck_candidate(job_id: str | None, candidate_index: int | None) -> tuple[Any, ...]:
        if not job_id or candidate_index is None:
            return _notice("error", "没有可检查的动画", "请先选择一个已经保存的生成结果。"), *review_payload(job_id, candidate_index)
        try:
            service.check_candidate(str(job_id), int(candidate_index))
            return (
                _notice(
                    "ok",
                    "本机检查已重新完成",
                    "没有调用生成 API，也没有消耗生成次数；当前预览和问题计数已更新。",
                ),
                *review_payload(str(job_id), int(candidate_index)),
            )
        except Exception as exc:
            return (
                _notice(
                    "error",
                    "本机检查仍未完成",
                    f"已保存的帧不会丢失，也不会消耗生成次数。{_human_error(exc)}",
                ),
                *review_payload(job_id, candidate_index),
            )

    def repair_job_choices_with_context(current: str | None = None) -> list[tuple[str, str]]:
        choices = job_choices(repair_only=True)
        if not current or any(value == str(current) for _label, value in choices):
            return choices
        try:
            job = service.get_job(str(current))
            has_safe_context = any(
                candidate.frames
                and candidate.status.value not in {"approved", "rejected", "failed"}
                and not (job.export and job.export.candidate_index == candidate.candidate_index)
                for candidate in job.candidates
            )
            if has_safe_context:
                choices.insert(0, (job_label(job) + " · 当前修补上下文", job.job_id))
        except Exception:
            pass
        return choices

    def repair_projection(job_id: str | None, candidate_index: int | None = None, frame_index: int | None = None) -> tuple[Any, ...]:
        empty = (
            gr.update(choices=[], value=None, visible=False), gr.update(choices=[], value=None), None, [],
            _notice("info", "当前没有待修补帧", "先到“播放检查”选择问题帧并点击“把当前帧送去修补”。"),
            gr.update(interactive=False), gr.update(value="other"), gr.update(value=""),
            _pixel_editor_embed(None, None, None), None, gr.update(value=None), {},
            [], gr.update(interactive=False), gr.update(interactive=False),
        )
        if not job_id:
            return empty
        try:
            job = service.get_job(str(job_id))
            candidates = candidate_choices(job, repair_only=True)
            explicit_candidate = None
            if candidate_index is not None:
                explicit_candidate = next(
                    (
                        item
                        for item in job.candidates
                        if item.candidate_index == int(candidate_index)
                        and item.frames
                        and item.status.value not in {"approved", "rejected", "failed"}
                        and not (job.export and job.export.candidate_index == item.candidate_index)
                    ),
                    None,
                )
            if explicit_candidate is not None and not any(
                value == explicit_candidate.candidate_index for _label, value in candidates
            ):
                candidates.append(
                    (
                        f"生成结果 {_candidate_letter(explicit_candidate.candidate_index)} · "
                        f"{CANDIDATE_STATUS_CN.get(explicit_candidate.status.value, explicit_candidate.status.value)} · 当前上下文",
                        explicit_candidate.candidate_index,
                    )
                )
            selected_candidate = (
                explicit_candidate.candidate_index
                if explicit_candidate is not None
                else default_candidate(job, repair_only=True)
            )
            if selected_candidate is None:
                return empty
            candidate = next(item for item in job.candidates if item.candidate_index == selected_candidate)
            frames = list(candidate.frames)
            problem_indices = [
                frame.index
                for frame in frames
                if frame.review_status.value == "repair_requested"
            ]
            selected_frame = (
                int(frame_index)
                if frame_index is not None and any(frame.index == int(frame_index) for frame in frames)
                else problem_indices[0] if problem_indices else frames[0].index
            )
            frame_position = next(
                index for index, item in enumerate(frames) if item.index == selected_frame
            )
            frame = frames[frame_position]
            current = service.store.resolve_job_path(job.job_id, frame.active_path)
            neighbor_specs: list[tuple[int, str]] = []
            if frame_position > 0:
                neighbor_specs.append((frame_position - 1, "上一帧"))
            elif job.action.loop and len(frames) > 1:
                neighbor_specs.append((len(frames) - 1, "循环上一帧"))
            neighbor_specs.append((frame_position, "当前帧"))
            if frame_position + 1 < len(frames):
                neighbor_specs.append((frame_position + 1, "下一帧"))
            elif job.action.loop and len(frames) > 1:
                neighbor_specs.append((0, "循环下一帧"))
            seen_neighbor_positions: set[int] = set()
            neighbors = []
            for position, relationship in neighbor_specs:
                if position in seen_neighbor_positions:
                    continue
                seen_neighbor_positions.add(position)
                neighbor_frame = frames[position]
                neighbors.append(
                    (
                        str(service.store.resolve_job_path(job.job_id, neighbor_frame.active_path)),
                        f"{relationship} · 第 {neighbor_frame.index + 1} 帧",
                    )
                )
            frame_choices = []
            timeline = []
            for item in frames:
                _state_key, icon, state_label = _repair_frame_state(candidate, item)
                suffix = f" · {item.review_note}" if item.review_note else ""
                caption = f"{icon} 第 {item.index + 1} 帧 · {state_label}{suffix}"
                frame_choices.append((caption, item.index))
                timeline.append(
                    (
                        str(service.store.resolve_job_path(job.job_id, item.active_path)),
                        caption,
                    )
                )
            state_key, _icon, state_label = _repair_frame_state(candidate, frame)
            can_manual_edit = frame.review_status.value == "repair_requested"
            can_replace = (
                can_manual_edit
                and frame.repair_attempts < 2
            )
            navigation_enabled = bool(problem_indices) and (
                len(problem_indices) > 1 or selected_frame not in problem_indices
            )
            notice_kind = {
                "blocked": "error",
                "repair": "warn",
                "modified": "ok",
                "approved": "ok",
                "pending": "info",
            }[state_key]
            notice_title = (
                f"正在修补第 {selected_frame + 1} 帧 · {state_label}"
                if can_manual_edit
                else f"正在查看第 {selected_frame + 1} 帧 · {state_label}"
            )
            edit_guidance = (
                "当前帧可以修改。"
                if can_manual_edit
                else "当前帧为只读；若仍需修改，请先在“播放检查”重新标记为待修补。"
            )
            return (
                gr.update(choices=candidates, value=selected_candidate, visible=len(candidates) > 1), gr.update(choices=frame_choices, value=selected_frame),
                str(current), neighbors, _notice(
                    notice_kind,
                    notice_title,
                    f"只修改这一格；其他 {len(candidate.frames) - 1} 帧不变。"
                    f"当前还有 {len(problem_indices)} 帧待修补。{edit_guidance}"
                    f"手工像素版本 {frame.manual_edit_versions} 个；外部/未来 AI 替换 {frame.repair_attempts}/2 次。",
                ) + _repair_qa_change_html(candidate),
                gr.update(interactive=can_replace), gr.update(value=frame.issue_type.value if frame.issue_type else "other"), gr.update(value=frame.review_note),
                _pixel_editor_embed(job.job_id, selected_candidate, selected_frame), frame.sha256,
                gr.update(value=None), {},
                timeline,
                gr.update(interactive=navigation_enabled),
                gr.update(interactive=navigation_enabled),
            )
        except Exception as exc:
            return (*empty[:4], _notice("error", "修补任务无法加载", _human_error(exc)), *empty[5:])

    def refresh_repairs(
        current: str | None,
        candidate_index: int | None,
        frame_index: int | None,
    ) -> tuple[Any, ...]:
        choices = repair_job_choices_with_context(current)
        values = {value for _label, value in choices}
        selected = current if current in values else choices[0][1] if choices else None
        preserve = selected == current
        return gr.update(choices=choices, value=selected), *repair_projection(
            selected,
            candidate_index if preserve else None,
            frame_index if preserve else None,
        )

    def load_saved_asset_in_review(
        job_id: str | None,
        candidate_index: int | None,
    ) -> tuple[Any, ...]:
        try:
            if not job_id or candidate_index is None:
                raise ValidationHarnessError("请先打开一个已有画面的候选")
            job = service.get_job(str(job_id))
            candidate = next(
                item for item in job.candidates if item.candidate_index == int(candidate_index)
            )
            if not candidate.frames:
                raise ValidationHarnessError("这个候选还没有保存任何画面")
            choices = job_choices()
            return (
                _notice("ok", "已载入播放检查", "当前任务和候选已经打开，可以继续检查或标记待修补帧。"),
                gr.update(selected="review"),
                gr.update(choices=choices, value=str(job_id)),
                *review_payload(str(job_id), int(candidate_index)),
            )
        except Exception as exc:
            return (
                _notice("error", "无法进入播放检查", _human_error(exc)),
                gr.update(),
                review_job_update(job_id),
                *review_payload(job_id, candidate_index),
            )

    def load_saved_asset_in_repair(
        job_id: str | None,
        candidate_index: int | None,
    ) -> tuple[Any, ...]:
        try:
            if not job_id or candidate_index is None:
                raise ValidationHarnessError("请先打开一个含待修补帧的候选")
            job = service.get_job(str(job_id))
            candidate = next(
                item for item in job.candidates if item.candidate_index == int(candidate_index)
            )
            if not any(frame.review_status.value == "repair_requested" for frame in candidate.frames):
                raise ValidationHarnessError("这个候选当前没有待修补帧；请先到播放检查中标记")
            choices = repair_job_choices_with_context(str(job_id))
            return (
                _notice("ok", "已载入逐帧修补", "已打开该候选的第一个待修补帧。"),
                gr.update(selected="repair"),
                gr.update(choices=choices, value=str(job_id)),
                *repair_projection(str(job_id), int(candidate_index)),
            )
        except Exception as exc:
            return (
                _notice("error", "无法进入逐帧修补", _human_error(exc)),
                gr.update(),
                gr.update(choices=repair_job_choices_with_context(job_id), value=job_id),
                *repair_projection(job_id, candidate_index),
            )

    def navigate_problem_frame(
        job_id: str | None,
        candidate_index: int | None,
        frame_index: int | None,
        direction: int,
    ) -> tuple[Any, ...]:
        try:
            job = service.get_job(str(job_id))
            candidate = next(
                item for item in job.candidates if item.candidate_index == int(candidate_index)
            )
            problem_indices = [
                frame.index
                for frame in candidate.frames
                if frame.review_status.value == "repair_requested"
            ]
            target = _adjacent_problem_frame_index(problem_indices, frame_index, direction)
            return repair_projection(job.job_id, candidate.candidate_index, target)
        except Exception:
            return repair_projection(job_id, candidate_index, frame_index)

    def select_repair_timeline_frame(
        job_id: str | None,
        candidate_index: int | None,
        evt: gr.SelectData,
    ) -> tuple[Any, ...]:
        try:
            job = service.get_job(str(job_id))
            candidate = next(
                item for item in job.candidates if item.candidate_index == int(candidate_index)
            )
            raw_index = getattr(evt, "index", 0)
            position = int(raw_index[-1]) if isinstance(raw_index, (list, tuple)) else int(raw_index)
            if position < 0 or position >= len(candidate.frames):
                raise IndexError(position)
            return repair_projection(job.job_id, candidate.candidate_index, candidate.frames[position].index)
        except Exception:
            return repair_projection(job_id, candidate_index)

    def replace_repair_frame(
        job_id: str | None,
        candidate_index: int | None,
        frame_index: int | None,
        replacement: Any,
        base_sha256: str | None,
        upload_context: dict[str, Any] | None,
    ) -> tuple[Any, ...]:
        try:
            if replacement is None:
                raise ValidationHarnessError("请上传修补后的透明 PNG")
            expected_upload_context = {
                "job_id": str(job_id or ""),
                "candidate_index": int(candidate_index) if candidate_index is not None else None,
                "frame_index": int(frame_index) if frame_index is not None else None,
                "base_sha256": str(base_sha256 or ""),
            }
            if upload_context != expected_upload_context:
                raise ValidationHarnessError(
                    "上传图片所属的任务、候选或帧已经变化；为防止写错帧，请重新选择文件"
                )
            updated = service.replace_frame(
                str(job_id),
                int(candidate_index),
                int(frame_index),
                _uploaded_path(replacement),
                base_sha256=str(base_sha256 or ""),
            )
            updated_candidate = next(
                item for item in updated.candidates if item.candidate_index == int(candidate_index)
            )
            qa_current = bool(
                updated_candidate.qa_completed_at is not None
                and updated_candidate.qa_input_sha256
                and updated_candidate.qa_algorithm_version == QA_ALGORITHM_VERSION
                and updated_candidate.error is None
            )
            choices = repair_job_choices_with_context(str(job_id))
            selected = str(job_id) if any(value == str(job_id) for _label, value in choices) else choices[0][1] if choices else None
            notice = (
                _notice(
                    "warn",
                    "替换帧已保存，自动复查未完成",
                    "原图和新版本都已保留；可在播放检查中重新运行检查。",
                )
                if not qa_current
                else _notice(
                    "ok",
                    "替换帧已保存并重新检查",
                    "原图仍保留；请回到“播放检查”重新播放整段动画。",
                )
            )
            preserve = selected == str(job_id)
            return notice, gr.update(choices=choices, value=selected), *repair_projection(
                selected,
                int(candidate_index) if preserve and candidate_index is not None else None,
                int(frame_index) if preserve and frame_index is not None else None,
            )
        except Exception as exc:
            choices = repair_job_choices_with_context(str(job_id) if job_id else None)
            return _notice("error", "替换没有生效", _human_error(exc)), gr.update(choices=choices, value=job_id), *repair_projection(job_id, candidate_index, frame_index)

    def capture_repair_upload_context(
        replacement: Any,
        job_id: str | None,
        candidate_index: int | None,
        frame_index: int | None,
        base_sha256: str | None,
    ) -> dict[str, Any]:
        if replacement is None:
            return {}
        return {
            "job_id": str(job_id or ""),
            "candidate_index": int(candidate_index) if candidate_index is not None else None,
            "frame_index": int(frame_index) if frame_index is not None else None,
            "base_sha256": str(base_sha256 or ""),
        }

    def export_projection(job_id: str | None, candidate_index: int | None = None) -> tuple[Any, ...]:
        empty = gr.update(choices=[], value=None, visible=False), _notice("info", "还没有可导出的动画", "先在“播放检查”确认采用一组动画。"), None, gr.update(value=""), gr.update(interactive=False)
        if not job_id:
            return empty
        try:
            job = service.get_job(str(job_id))
            choices = candidate_choices(job, approved_only=True)
            choice_values = {value for _label, value in choices}
            requested = int(candidate_index) if candidate_index else None
            selected = requested if requested in choice_values else default_candidate(job, approved_only=True)
            if selected is None:
                return empty
            candidate = next(item for item in job.candidates if item.candidate_index == selected)
            integrity_ok = True
            if job.request.provider != "import":
                safety = service.candidate_safety(job.job_id, selected)
                integrity_ok = safety["result_integrity"] is True
                job = service.get_job(job.job_id)
                candidate = next(item for item in job.candidates if item.candidate_index == selected)
            qa_current = bool(
                candidate.qa_completed_at is not None
                and candidate.qa_input_sha256
                and candidate.qa_algorithm_version == QA_ALGORITHM_VERSION
                and candidate.error is None
                and integrity_ok
            )
            already_exported = bool(
                job.export and job.export.candidate_index == candidate.candidate_index
            )
            columns = job.action.sheet_columns or job.character.sheet_columns
            if len(candidate.frames) == job.action.frame_count:
                rows = job.action.sheet_rows or math.ceil(len(candidate.frames) / columns)
                frame_cells = job.action.frame_cells
            else:
                rows = max(job.action.sheet_rows or 0, math.ceil(len(candidate.frames) / columns))
                frame_cells = []
            width, height = job.character.cell_width * columns, job.character.cell_height * rows
            regular_cells = [(index % columns, index // columns) for index in range(len(candidate.frames))]
            order_text = (
                "按项目指定格位读取（透明空格不参与播放）"
                if frame_cells and frame_cells != regular_cells
                else "从左到右、从上到下"
            )
            try:
                action = profile.action(job.action.action_id)
                filename = action.filename if job.character.character_id == profile.character_id else f"{job.character.character_id}_{job.action.action_id}.png"
            except KeyError:
                filename = f"{job.character.character_id}_{job.action.action_id}.png"
            unused_count = columns * rows - len(candidate.frames)
            count_note = (
                f"实际采用 {len(candidate.frames)} 帧；末尾 {unused_count} 个格子保持透明。"
                if unused_count
                else f"实际采用 {len(candidate.frames)} 帧；没有空格。"
            )
            summary = (
                '<div class="section-intro"><h3>最终 Sprite Sheet</h3>'
                f"<p>输出尺寸：{width}×{height}；单帧：{job.character.cell_width}×{job.character.cell_height}；"
                f"排列：{columns} 列×{rows} 行；顺序：{order_text}；背景：透明 RGBA。{count_note}</p>"
                '<div class="notice info"><strong>关于位置对齐</strong>每帧保留完整画布，不会紧贴角色裁切，也不会逐帧自动居中。导出会保持你在检查页确认过的坐标。</div></div>'
            )
            if not integrity_ok:
                summary += _notice(
                    "error",
                    "原始生成结果完整性异常",
                    "新的导出已被阻止。若此前已经导出，旧文件仍保持只读可用；请先恢复任务的原始结果文件。",
                )
            elif not qa_current and already_exported:
                summary += _notice(
                    "warn",
                    "已有导出已保留，当前页面只读",
                    "此候选使用的是旧版检查规则，已导出的文件不会消失；为避免覆盖历史结果，当前版本不允许重新导出。",
                )
            elif not qa_current:
                summary += _notice(
                    "warn",
                    "导出前需要重新检查",
                    "检查规则已经升级。请回到“播放检查”运行一次本机检查，再确认采用；不会消耗 API 次数。",
                )
            prefix = service.store.job_dir(job.job_id) / "previews" / candidate.candidate_id
            preview = prefix.with_suffix(".sheet.png")
            if already_exported and job.export is not None:
                exported_sheet = service.settings.resolve_record_path(job.export.sheet_path)
                if exported_sheet.is_file():
                    preview = exported_sheet
                filename = Path(job.export.sheet_path).name
            return (
                gr.update(choices=choices, value=selected, visible=len(choices) > 1),
                summary,
                str(preview) if preview.is_file() else None,
                gr.update(value=filename),
                gr.update(interactive=qa_current),
            )
        except Exception as exc:
            return (*empty[:1], _notice("error", "导出信息无法加载", _human_error(exc)), *empty[2:])

    def refresh_exports(current: str | None) -> tuple[Any, ...]:
        choices = job_choices(approved_only=True)
        values = {value for _label, value in choices}
        selected = current if current in values else choices[0][1] if choices else None
        return gr.update(choices=choices, value=selected), *export_projection(selected)

    def export_one(job_id: str | None, candidate_index: int | None, filename: str, overwrite: bool) -> tuple[str, str | None, list[str], dict[str, Any]]:
        try:
            job = service.export_candidate(str(job_id), int(candidate_index), ExportOptions(filename=(filename or "").strip(), overwrite=bool(overwrite)))
            assert job.export is not None
            return (
                _notice("ok", "Sprite Sheet 已导出到用户导出目录", "文件与软件代码分开保存，不会自动覆盖游戏工程。"),
                str(service.settings.resolve_record_path(job.export.sheet_path)),
                [
                    str(service.settings.resolve_record_path(job.export.preview_path)),
                    str(service.settings.resolve_record_path(job.export.recipe_path)),
                    str(service.settings.resolve_record_path(job.export.qa_path)),
                ],
                {"ok": True, "job": job.model_dump(mode="json")},
            )
        except Exception as exc:
            return _notice("error", "导出没有完成", _human_error(exc)), None, [], _error_payload(exc)

    def run_demo() -> tuple[Any, ...]:
        job = None
        try:
            job = service.create_job(GenerationRequest(character_id="diagnostic_dummy", action_id="idle", provider="fixture", candidate_count=1))
            job = service.generate_job(job.job_id, wait=True)
            visible_diagnostic_jobs.add(job.job_id)
            return _notice("ok", "离线示例已完成", "请到“播放检查”体验后续按钮；这不是游戏美术，也不代表模型质量。"), {"ok": True, "job": job.model_dump(mode="json")}, review_job_update(job.job_id), *review_payload(job.job_id)
        except Exception as exc:
            job_id = job.job_id if job is not None else None
            return _notice("error", "示例没有完成", _human_error(exc)), _error_payload(exc), review_job_update(job_id), *review_payload(job_id)

    characters, actions = official_character_choices(), project_action_choices()
    initial_character = profile.character_id if any(value == profile.character_id for _label, value in characters) else characters[0][1] if characters else None
    initial_action = actions[0][1] if actions else None
    initial_reference, _initial_character_summary = character_projection(initial_character)
    # Startup only builds small catalog rows. Candidate records, frame paths and
    # previews are loaded after the operator explicitly opens a task.
    initial_jobs = job_choices(); initial_job = None; initial_review = review_payload(None)
    initial_tasks = saved_asset_choices(); initial_task_job = initial_tasks[0][1] if initial_tasks else None
    initial_asset_catalog = saved_asset_catalog_projection(initial_task_job)
    initial_asset = saved_asset_projection(None)
    initial_task = task_center_projection(None)
    initial_repairs = job_choices(repair_only=True); initial_repair_job = None; initial_repair = repair_projection(None)
    initial_exports = job_choices(approved_only=True); initial_export_job = None; initial_export = export_projection(None)

    with gr.Blocks(title="像素角色动画工作台", fill_width=True) as demo:
        gr.HTML(
            '<div id="sprite-hero"><h1>像素角色动画工作台</h1><p>先看指引，再在“生成动画”中导入角色原型图、填写提示词并生成；随后依次播放检查、按需修补并导出固定网格 PNG。</p>'
            '<div class="flow-map"><div class="flow-box"><small>1</small>指引示例</div><div class="flow-box"><small>2</small>生成动画<br>导入原图 + 提示词</div>'
            '<div class="flow-box"><small>3</small>播放检查</div><div class="flow-box"><small>4</small>逐帧修补</div><div class="flow-box"><small>5</small>导出 Sheet</div></div></div>'
        )
        header_status = gr.HTML(header_status_html())
        with gr.Tabs(elem_classes=["workflow-tabs"]) as workflow_tabs:
            with gr.Tab("指引与示例", id="example"):
                gr.HTML('<div class="section-intro"><h2>先从这里了解完整流程</h2><p>真正生成时，你需要提供角色原型图、角色外观提示词和本次动作提示词。这里使用流程测试机器人解释动画帧与最终 Sheet；它不联网、不消耗额度，也不代表真实生成质量。待机示例没有位移动作，所以保持原位；其他动作允许自然、连续地移动。</p></div><div class="contract-grid"><div class="contract-card"><small>角色原型图</small><b>模型生成动作时必须保持的角色形象</b></div><div class="contract-card"><small>位置连续性</small><b>允许自然移动，不允许相邻帧突然跳位</b></div><div class="contract-card"><small>Sprite Sheet</small><b>固定大小网格，不逐帧裁剪或强制居中</b></div></div>')
                run_demo_button = gr.Button("运行离线示例", variant="primary", elem_classes=["primary-action"]); demo_status = gr.HTML()
                with gr.Accordion("示例任务详情", open=False): demo_details = gr.JSON()

            with gr.Tab("生成动画", id="generate"):
                gr.HTML('<div class="section-intro"><h2>从角色原型生成动作</h2><p>这一步已经包含“导入”：先上传角色原型 PNG，再填写角色外观提示词和本次动作提示词。生成时会要求模型保持相邻帧的位置轨迹连续，但不会把人物强制钉在画布中央；生成完成后，结果会直接进入“播放检查”。</p><div class="contract-grid"><div class="contract-card"><small>输入 1</small><b>角色原型 PNG</b></div><div class="contract-card"><small>输入 2</small><b>角色外观 + 动作提示词</b></div><div class="contract-card"><small>生成结果</small><b>固定网格、前后连续的动画候选</b></div></div></div>')
                ai_api_banner = gr.HTML(api_banner_html())
                with gr.Row():
                    quota_status = gr.HTML(quota_html(), scale=5)
                    refresh_quota_button = gr.Button("刷新额度（不消耗次数）", scale=1)
                with gr.Accordion("额度原始记录（排错时再看）", open=False):
                    quota_details = gr.JSON(service.get_cached_balance() or {})
                with gr.Row():
                    with gr.Column():
                        gr.Markdown("### 1. 导入角色原型")
                        generation_reference_file = gr.File(
                            label="角色原型 PNG",
                            file_count="single",
                            file_types=[".png"],
                            type="filepath",
                        )
                        gr.Markdown("支持一张 **128×128 透明 PNG**，或当前项目的 **4 列、128×128/格 Sheet**；Sheet 会自动取第一个非空格。")
                        generation_reference_preview = gr.Image(initial_reference, label="实际送给模型的参考帧", type="pil", interactive=False, height=280, elem_classes=["pixel-preview"])
                        generation_reference_status = gr.HTML(_notice("info", "当前使用已保存角色", "上传新的角色原型 PNG 后，会改用上传图片。"))
                        generation_reference_state = gr.State({})
                        generation_character_name = gr.Textbox(label="角色名称（可选）", placeholder="例如：赛博剑士；留空时记为“新角色”")
                        generation_identity_prompt = gr.Textbox(
                            label="角色外观提示词（推荐填写）",
                            placeholder="例如：保持蓝黑色盔甲、青色发光线条、头身比例、头盔和长剑外形不变",
                            lines=3,
                        )
                        with gr.Accordion("没有上传新原图？使用已保存角色", open=False):
                            generate_character = gr.Dropdown(characters, value=initial_character, label="已保存角色", filterable=False, elem_classes=["static-choice"])
                    with gr.Column():
                        gr.Markdown("### 2. 描述动作并生成")
                        generate_action = gr.Dropdown(actions, value=initial_action, label="要生成的动作", filterable=False, elem_classes=["static-choice"])
                        generate_action_summary = gr.HTML(action_projection(initial_action))
                        action_description = gr.Textbox(label="本次动作提示词（可选）", placeholder="例如：起步慢、第三帧开始加速、武器始终朝前；留空使用项目动作规格", lines=4)
                        candidate_count = gr.Slider(1, 5, value=1, step=1, label="生成几个候选？（每个候选单独提交，额度随尺寸和帧数变化）")
                        generation_cost = gr.HTML(generation_cost_html(1, initial_action))
                        with gr.Accordion("复现与调试设置", open=False):
                            seed = gr.Textbox(label="Seed（可选）", placeholder="留空则自动生成并记录")
                generation_request_key = gr.BrowserState(
                    uuid.uuid4().hex,
                    storage_key="sprite_pipeline_generation_request_key_v1",
                    secret="sprite-pipeline-local-idempotency-v1",
                )
                generate_button = gr.Button("开始生成候选", variant="primary", interactive=api_configured(), elem_classes=["primary-action"])
                generation_status = gr.HTML()
                with gr.Accordion("技术详情（排错时再看）", open=False): generation_details = gr.JSON(label="任务记录")

            with gr.Tab("已保存资产", id="assets"):
                gr.HTML(
                    '<div class="section-intro"><h2>已保存资产</h2>'
                    '<p>这里按“一个任务一个文件夹”管理历史结果；一次任务生成的多个候选都收在同一个任务文件夹中。'
                    '每次启动只读取每个任务的轻量摘要，不解码帧图、GIF 或完整任务记录。选择并打开任务后，才读取其中的候选与图片。</p></div>'
                )
                with gr.Row():
                    task_job = gr.Dropdown(initial_tasks, value=initial_task_job, label="任务目录（轻量摘要）", filterable=False, elem_classes=["static-choice"], scale=5)
                    open_asset_button = gr.Button("打开所选任务", variant="primary", scale=1)
                    refresh_asset_catalog_button = gr.Button("刷新目录", scale=1)
                asset_catalog_status = gr.HTML(initial_asset_catalog)
                asset_candidate = gr.Radio(
                    initial_asset[0].get("choices", []),
                    value=initial_asset[0].get("value"),
                    visible=bool(initial_asset[0].get("visible", False)),
                    label="该任务中的候选",
                    elem_classes=["choice-cards"],
                )
                asset_summary = gr.HTML(initial_asset[1])
                with gr.Row():
                    asset_animation_preview = gr.Image(initial_asset[2], label="已保存动画预览", type="filepath", interactive=False, height=360, elem_classes=["pixel-preview"])
                    asset_frame_gallery = gr.Gallery(initial_asset[3], label="已保存逐帧画面", columns=4, rows=2, height=360, object_fit="contain", allow_preview=False, elem_classes=["frame-gallery"])
                with gr.Row():
                    asset_review_button = gr.Button("在播放检查中打开", interactive=bool(initial_asset[4].get("interactive", False)))
                    asset_repair_button = gr.Button("打开待修补帧", interactive=bool(initial_asset[5].get("interactive", False)))
                asset_action_status = gr.HTML()
                with gr.Accordion("任务保存与恢复状态", open=False):
                    gr.Markdown("只有打开任务后才读取完整安全记录。后台只会继续查询已经提交的任务，不会自动创建第二次生成。")
                    refresh_task_button = gr.Button("安全刷新 / 继续取回已有结果")
                    task_status = gr.HTML(initial_task[0])
                    with gr.Accordion("任务完整记录（排错时再看）", open=False):
                        task_details = gr.JSON(initial_task[1])
                    with gr.Accordion("提交结果未知时的人工恢复", open=False):
                        gr.Markdown("只有在 PixelLab 网页或其他记录中能找到此次生成的远端任务编号时才填写。此操作只绑定并查询已有任务，绝不会再次提交生成。")
                        attach_candidate = gr.Dropdown(
                            initial_task[2].get("choices", []),
                            value=initial_task[2].get("value"),
                            label="需要恢复的候选",
                            interactive=bool(initial_task[2].get("interactive", False)),
                            filterable=False,
                            elem_classes=["static-choice"],
                        )
                        attach_provider_id = gr.Textbox(label="PixelLab 远端任务编号")
                        attach_provider_button = gr.Button("绑定并只取回已有结果")
                        attach_status = gr.HTML()

            with gr.Tab("播放检查", id="review"):
                gr.HTML('<div class="section-intro"><h2>播放与检查</h2><p>先按游戏速度看整段，再点击单帧。重点观察前一帧和后一帧的动作与位置能否接上、脸或武器是否突然变化、背景是否透明。角色可以连续移动；只有突变式跳位才会被拦截。画布外框始终保持不变。</p></div>')
                with gr.Accordion("检查一张已有 Sprite Sheet", open=False):
                    gr.Markdown("如果动画不是刚刚由本工具生成，而是你已经拥有的一张 Sheet，请在这里上传。它只会被切分并送入本页检查，不会作为角色原型参与生成。")
                    with gr.Row():
                        with gr.Column():
                            import_file = gr.File(label="已有 Sprite Sheet（PNG）", file_count="single", file_types=[".png"], type="filepath")
                            import_action = gr.Dropdown(actions, value=None, label="这是什么动画？（必须确认）", filterable=False, elem_classes=["static-choice"])
                            gr.Markdown("请按动画含义选择，而不是依靠帧数区分；新的动作合同已经全部统一为 16 帧。")
                            gr.Markdown("检查规格锁定为 **128×128/格、4 列、RGBA**；旧版 5/8/12 帧、尾部透明补格和其他可识别帧数仍可进入检查。")
                        with gr.Column(scale=2):
                            import_grid_preview = gr.Image(label="切分网格预览", type="pil", interactive=False, elem_classes=["sheet-preview"])
                    import_inspection = gr.HTML(_notice("info", "等待已有 Sheet", "上传后先确认网格和动作类型。")); import_state = gr.State({})
                    import_button = gr.Button("切分并加入播放检查", variant="primary", interactive=False, elem_classes=["primary-action"])
                    import_status = gr.HTML()
                    with gr.Accordion("检查素材记录（排错时再看）", open=False): import_details = gr.JSON(label="已有 Sheet 任务记录")
                with gr.Row():
                    review_job = gr.Dropdown(initial_jobs, value=initial_job, label="选择要检查的动画", filterable=False, elem_classes=["static-choice"], scale=5)
                    refresh_review_button = gr.Button("刷新", scale=1, elem_id="refresh-review-button")
                    recover_result_button = gr.Button("取回所选旧结果（不重新生成）", scale=2)
                    recheck_button = gr.Button("重新运行本机检查（不消耗 API）", scale=2, interactive=bool(initial_review[13].get("interactive", False)))
                recovery_status = gr.HTML()
                with gr.Group(visible=bool(initial_review[12].get("visible", False))) as review_candidate_group:
                    review_candidate = gr.Radio(initial_review[0].get("choices", []), value=initial_review[0].get("value"), label="选择 AI 生成结果", elem_classes=["choice-cards"])
                review_summary = gr.HTML(initial_review[3])
                with gr.Row():
                    animation_preview = gr.Image(initial_review[1], label="动画预览（项目 FPS）", type="filepath", interactive=False, height=390, elem_classes=["pixel-preview"])
                    review_issues = gr.Markdown(initial_review[4])
                frame_gallery = gr.Gallery(initial_review[2], label="逐帧画面（点击一帧）", columns=4, rows=2, height=430, object_fit="contain", allow_preview=False, selected_index=0, elem_classes=["frame-gallery"])
                selected_frame_index = gr.State(initial_review[6]); selected_frame_banner = gr.HTML(initial_review[7])
                with gr.Row():
                    issue_type = gr.Dropdown(ISSUE_TYPE_CHOICES, value="other", label="如果有问题，主要是什么？", filterable=False, elem_classes=["static-choice"])
                    review_note = gr.Textbox(label="问题说明（可选）", placeholder="例如：剑在这一帧突然变短")
                with gr.Row():
                    mark_ok_button = gr.Button("当前帧没有问题", interactive=bool(initial_review[14].get("interactive", False)))
                    mark_repair_button = gr.Button("把当前帧送去修补", interactive=bool(initial_review[15].get("interactive", False)))
                with gr.Accordion("位置连续性辅助：参考线与相邻帧叠影", open=False):
                    gr.Markdown("十字线只是项目放置参考，不要求每帧人物都严格压在交点上。相邻帧叠影中，紫红色是前一帧、青色是当前帧；连续的小幅位移是正常的，突然分离很远才是问题。工具不会裁剪、缩放或重新居中任何一帧。")
                    with gr.Row():
                        baseline_preview = gr.Image(initial_review[11], label="项目参考线（不强制居中）", type="filepath", interactive=False, elem_classes=["pixel-preview"])
                        overlay_preview = gr.Image(initial_review[10], label="相邻帧叠影", type="filepath", interactive=False, elem_classes=["pixel-preview"])
                acknowledge = gr.Checkbox(value=bool(initial_review[8].get("value", False)), label="我已查看自动提醒，仍决定采用", visible=bool(initial_review[8].get("visible", False)))
                with gr.Row():
                    approve_button = gr.Button("这组动画可以使用", variant="primary", interactive=bool(initial_review[9].get("interactive", False)))
                    reject_button = gr.Button("放弃这组结果", variant="stop")
                review_action_status = gr.HTML()
                with gr.Accordion("技术详情（排错时再看）", open=False): review_details = gr.JSON(initial_review[5], label="QA 与任务记录")

            with gr.Tab("逐帧修补", id="repair"):
                gr.HTML('<div class="section-intro"><h2>修补问题帧</h2><p>画布会把上一帧显示为洋红色、下一帧显示为青色，便于同时检查动作和位置连续性。可使用铅笔、橡皮擦、吸管、精确填充，以及框选后的整数像素微调；所有参考层都不会写入 PNG。手工修补不消耗 API 次数，每次保存都会建立新版本并保留原图。</p></div>')
                with gr.Row():
                    repair_job = gr.Dropdown(initial_repairs, value=initial_repair_job, label="含待修补帧的动画", filterable=False, elem_classes=["static-choice"], scale=5)
                    refresh_repair_button = gr.Button("刷新", scale=1, elem_id="refresh-repair-button")
                repair_candidate = gr.Dropdown(initial_repair[0].get("choices", []), value=initial_repair[0].get("value"), visible=bool(initial_repair[0].get("visible", False)), label="生成结果", filterable=False, elem_classes=["static-choice"])
                repair_frame = gr.Dropdown(initial_repair[1].get("choices", []), value=initial_repair[1].get("value"), label="当前帧 / 快速跳转", filterable=False, elem_classes=["static-choice"])
                repair_timeline = gr.Gallery(
                    initial_repair[12],
                    label="完整帧条（点击任意帧查看）",
                    columns=8,
                    rows=2,
                    height=330,
                    object_fit="contain",
                    allow_preview=False,
                    elem_classes=["frame-gallery"],
                )
                with gr.Row():
                    previous_problem_button = gr.Button(
                        "← 上一个问题帧",
                        interactive=bool(initial_repair[13].get("interactive", False)),
                    )
                    next_problem_button = gr.Button(
                        "下一个问题帧 →",
                        interactive=bool(initial_repair[14].get("interactive", False)),
                    )
                repair_summary = gr.HTML(initial_repair[4])
                repair_editor = gr.HTML(initial_repair[8])
                repair_base_sha256 = gr.State(initial_repair[9])
                with gr.Accordion("相邻帧与问题记录", open=False):
                    with gr.Row():
                        repair_current = gr.Image(initial_repair[2], label="当前版本", type="filepath", interactive=False, height=330, elem_classes=["pixel-preview"])
                        repair_neighbors = gr.Gallery(initial_repair[3], label="上一帧 / 当前帧 / 下一帧", columns=3, height=330, allow_preview=False, elem_classes=["frame-gallery"])
                    with gr.Row():
                        repair_issue_type = gr.Dropdown(ISSUE_TYPE_CHOICES, value=initial_repair[6].get("value", "other"), label="问题类型（记录用）", interactive=False, filterable=False, elem_classes=["static-choice"])
                        repair_note = gr.Textbox(value=initial_repair[7].get("value", ""), label="原问题说明", interactive=False)
                with gr.Accordion("使用外部绘图软件替换（备用）", open=False):
                    gr.Markdown("如需使用 Aseprite、Krita 等外部工具，可上传相同尺寸的透明 PNG。这个入口仍保留两次替换限制；内置手工像素版本没有该限制。")
                    replacement_file = gr.File(label="修补后的透明 PNG（必须仍为 128×128）", file_count="single", file_types=[".png"], type="filepath")
                    repair_upload_context = gr.State({})
                    replace_button = gr.Button("保存外部替换并重新检查", variant="primary", interactive=bool(initial_repair[5].get("interactive", False)), elem_classes=["primary-action"])
                repair_action_status = gr.HTML()

            with gr.Tab("导出", id="export"):
                gr.HTML(f'<div class="section-intro"><h2>导出 Sprite Sheet</h2><p>把已通过检查的帧按固定网格合成一张透明 PNG，供 Godot SpriteFrames 使用。默认写入用户文档中的独立导出目录，不会写回软件代码，也不会直接覆盖你的游戏工程。</p><p>当前导出目录：<code>{_escape(service.settings.exports_dir)}</code></p></div>')
                with gr.Row():
                    export_job = gr.Dropdown(initial_exports, value=initial_export_job, label="已通过检查的动画", filterable=False, elem_classes=["static-choice"], scale=5)
                    refresh_export_button = gr.Button("刷新", scale=1)
                export_candidate = gr.Radio(initial_export[0].get("choices", []), value=initial_export[0].get("value"), visible=bool(initial_export[0].get("visible", False)), label="已采用结果", elem_classes=["choice-cards"])
                export_summary = gr.HTML(initial_export[1]); export_sheet_preview = gr.Image(initial_export[2], label="主要交付物预览", type="filepath", interactive=False, elem_classes=["sheet-preview"])
                export_filename = gr.Textbox(value=initial_export[3].get("value", ""), label="文件名", placeholder="例如：赛博人物行走.png")
                with gr.Accordion("覆盖设置", open=False): export_overwrite = gr.Checkbox(label="允许覆盖工具暂存区内的同名文件")
                export_button = gr.Button("导出 PNG Sprite Sheet", variant="primary", interactive=bool(initial_export[4].get("interactive", False)), elem_classes=["primary-action"])
                export_status = gr.HTML(); exported_sheet = gr.File(label="Sprite Sheet PNG", interactive=False)
                with gr.Accordion("附加文件（预览、配方与 QA 报告）", open=False):
                    export_attachments = gr.File(label="附加文件", file_count="multiple", interactive=False); export_details = gr.JSON(label="导出记录")

            with gr.Tab("API 与项目", id="settings"):
                gr.HTML('<div class="section-intro"><h2>PixelLab API</h2><p>只用于“生成动画”。Key 使用 Windows DPAPI 绑定当前系统用户后加密保存，不再写入软件项目目录、任务记录、导出文件或日志，页面也不会回显完整内容。</p></div>')
                api_status = gr.HTML(api_settings_status()); api_key = gr.Textbox(label="API Key", type="password", placeholder="粘贴后点击保存；保存成功会自动清空输入框")
                with gr.Row(): save_api_button = gr.Button("保存并立即生效", variant="primary"); clear_api_button = gr.Button("清除已保存的 Key")
                storage_status = gr.HTML(storage_status_html())
                refresh_storage_button = gr.Button("刷新存储与迁移状态")
                with gr.Accordion("迁移与存储技术记录", open=False):
                    storage_details = gr.JSON(service.storage_status())
                gr.HTML(
                    '<div class="section-intro"><h2>游戏项目</h2>'
                    f'<p>这里展示的是当前 Harness 采用的项目输出合同。项目：{_escape(profile.project_name)}；引擎：{_escape(profile.engine)}；目标角色：{_escape(profile.character_name)}。</p>'
                    f'<div class="contract-grid"><div class="contract-card"><small>单帧</small><b>{profile.cell_width}×{profile.cell_height} RGBA</b></div><div class="contract-card"><small>统一网格</small><b>所有动作 16 帧 · {profile.columns} 列×4 行</b></div><div class="contract-card"><small>参考锚点 / 运行时偏移</small><b>({profile.anchor_x},{profile.anchor_ground_y}) / ({profile.sprite_offset_x},{profile.sprite_offset_y})</b></div></div></div>'
                    + '<table class="project-table"><thead><tr><th>动画</th><th>输出规格</th><th>播放</th><th>文件名</th><th>工程状态</th></tr></thead><tbody>'
                    + "".join(
                        f"<tr><td>{_escape(item.display_name)}</td>"
                        f"<td>{item.sheet_size[0]}×{item.sheet_size[1]} · {item.frame_count} 帧</td>"
                        f"<td>{item.fps:g} FPS{'（资源场景 ' + format(item.scene_fps, 'g') + '）' if item.scene_fps != item.fps else ''} · {'循环' if item.loop else '单次'}</td>"
                        f"<td>{_escape(item.filename)}</td>"
                        f"<td>{_escape(PROJECT_INTEGRATION_STATUS_CN.get(item.integration_status, item.integration_status))}</td></tr>"
                        for item in profile.actions
                    )
                    + '</tbody></table>'
                    + _notice("info", "新生成规格已统一为 16 帧", "所有动作都生成并导出完整 4×4 Sheet，不再为攻击、跳跃、受击或闪避降低默认帧数。旧 Sheet 仍可导入检查；替换旧资产时需要同步 Godot 的动画帧列表。")
                )

        asset_outputs = [asset_candidate, asset_summary, asset_animation_preview, asset_frame_gallery, asset_review_button, asset_repair_button]
        task_outputs = [task_status, task_details, attach_candidate]
        review_outputs = [review_candidate, animation_preview, frame_gallery, review_summary, review_issues, review_details, selected_frame_index, selected_frame_banner, acknowledge, approve_button, overlay_preview, baseline_preview, review_candidate_group, recheck_button, mark_ok_button, mark_repair_button]
        repair_outputs = [repair_candidate, repair_frame, repair_current, repair_neighbors, repair_summary, replace_button, repair_issue_type, repair_note, repair_editor, repair_base_sha256, replacement_file, repair_upload_context, repair_timeline, previous_problem_button, next_problem_button]
        export_outputs = [export_candidate, export_summary, export_sheet_preview, export_filename, export_button]

        generation_reference_file.change(
            prepare_generation_reference,
            inputs=[generation_reference_file, generate_character],
            outputs=[generation_reference_preview, generation_reference_status, generation_reference_state],
            queue=False,
        )
        generate_character.input(
            prepare_generation_reference,
            inputs=[generation_reference_file, generate_character],
            outputs=[generation_reference_preview, generation_reference_status, generation_reference_state],
            queue=False,
        )
        generate_action.input(action_projection, inputs=generate_action, outputs=generate_action_summary, queue=False)
        candidate_count.change(
            generation_cost_html,
            inputs=[candidate_count, generate_action],
            outputs=generation_cost,
            queue=False,
        )
        generate_action.input(
            generation_cost_html,
            inputs=[candidate_count, generate_action],
            outputs=generation_cost,
            queue=False,
        )
        refresh_quota_button.click(refresh_quota, outputs=[quota_status, quota_details])
        generate_button.click(
            generate_animation,
            inputs=[
                generation_reference_file,
                generation_reference_state,
                generation_character_name,
                generation_identity_prompt,
                generate_character,
                generate_action,
                candidate_count,
                action_description,
                seed,
                generation_request_key,
            ],
            outputs=[
                generation_status,
                generation_details,
                generation_reference_state,
                generate_character,
                generation_request_key,
                task_job,
                asset_catalog_status,
                *asset_outputs,
                *task_outputs,
                review_job,
                *review_outputs,
            ],
            trigger_mode="once",
            concurrency_limit=1,
            concurrency_id="pixellab_generation_submission",
        )
        task_job.input(
            select_saved_asset_summary,
            inputs=task_job,
            outputs=[asset_catalog_status, *asset_outputs, *task_outputs],
            queue=False,
        )
        open_asset_button.click(
            open_saved_asset,
            inputs=[task_job, asset_candidate],
            outputs=[asset_catalog_status, *asset_outputs, *task_outputs],
            queue=False,
        )
        asset_candidate.input(
            saved_asset_projection,
            inputs=[task_job, asset_candidate],
            outputs=asset_outputs,
            queue=False,
        )
        refresh_asset_catalog_button.click(
            reload_saved_asset_catalog,
            inputs=task_job,
            outputs=[task_job, asset_catalog_status],
            queue=False,
        )
        refresh_task_button.click(
            refresh_saved_assets,
            inputs=[task_job, asset_candidate],
            outputs=[task_job, asset_catalog_status, *asset_outputs, *task_outputs],
        )
        asset_review_button.click(
            load_saved_asset_in_review,
            inputs=[task_job, asset_candidate],
            outputs=[asset_action_status, workflow_tabs, review_job, *review_outputs],
        )
        asset_repair_button.click(
            load_saved_asset_in_repair,
            inputs=[task_job, asset_candidate],
            outputs=[asset_action_status, workflow_tabs, repair_job, *repair_outputs],
        )
        attach_provider_button.click(
            attach_remote_job,
            inputs=[task_job, attach_candidate, attach_provider_id],
            outputs=[
                attach_status,
                task_job,
                task_status,
                task_details,
                attach_candidate,
                attach_provider_id,
            ],
        )
        demo.load(
            reload_saved_asset_catalog,
            inputs=task_job,
            outputs=[task_job, asset_catalog_status],
            queue=False,
        )
        demo.load(
            fn=None,
            js=PIXEL_EDITOR_BRIDGE_JS,
            queue=False,
            api_visibility="private",
        )
        task_timer = gr.Timer(value=5.0, active=True)
        task_timer.tick(
            reload_saved_asset_catalog,
            inputs=task_job,
            outputs=[task_job, asset_catalog_status],
            queue=False,
        )
        import_file.change(inspect_uploaded_sheet, inputs=[import_file, import_action], outputs=[import_grid_preview, import_inspection, import_state, import_button], queue=False)
        import_action.input(inspect_uploaded_sheet, inputs=[import_file, import_action], outputs=[import_grid_preview, import_inspection, import_state, import_button], queue=False)
        import_button.click(import_sheet, inputs=[import_file, import_action, import_state], outputs=[import_status, import_details, review_job, *review_outputs])

        refresh_review_button.click(refresh_review, inputs=review_job, outputs=[review_job, *review_outputs], queue=False)
        recover_result_button.click(
            recover_provider_result,
            inputs=[review_job, review_candidate],
            outputs=[recovery_status, review_job, *review_outputs],
        )
        review_job.input(review_payload, inputs=review_job, outputs=review_outputs, queue=False)
        review_candidate.input(review_payload, inputs=[review_job, review_candidate], outputs=review_outputs, queue=False)
        recheck_button.click(recheck_candidate, inputs=[review_job, review_candidate], outputs=[review_action_status, *review_outputs])
        frame_gallery.select(select_frame, inputs=[review_job, review_candidate], outputs=[selected_frame_index, selected_frame_banner], queue=False)
        mark_ok_button.click(lambda j, c, f, i, n: mark_frame(j, c, f, "approved", i, n), inputs=[review_job, review_candidate, selected_frame_index, issue_type, review_note], outputs=[review_action_status, *review_outputs, repair_job, *repair_outputs])
        mark_repair_button.click(lambda j, c, f, i, n: mark_frame(j, c, f, "repair_requested", i, n), inputs=[review_job, review_candidate, selected_frame_index, issue_type, review_note], outputs=[review_action_status, *review_outputs, repair_job, *repair_outputs])
        approve_button.click(approve_candidate, inputs=[review_job, review_candidate, acknowledge], outputs=[review_action_status, *review_outputs, export_job, *export_outputs])
        reject_button.click(reject_candidate, inputs=[review_job, review_candidate, review_note], outputs=[review_action_status, *review_outputs])

        refresh_repair_button.click(
            refresh_repairs,
            inputs=[repair_job, repair_candidate, repair_frame],
            outputs=[repair_job, *repair_outputs],
            queue=False,
        )
        repair_job.input(repair_projection, inputs=repair_job, outputs=repair_outputs, queue=False)
        repair_candidate.input(repair_projection, inputs=[repair_job, repair_candidate], outputs=repair_outputs, queue=False)
        repair_frame.input(repair_projection, inputs=[repair_job, repair_candidate, repair_frame], outputs=repair_outputs, queue=False)
        repair_timeline.select(
            select_repair_timeline_frame,
            inputs=[repair_job, repair_candidate],
            outputs=repair_outputs,
            queue=False,
        )
        previous_problem_button.click(
            lambda job_id, candidate_index, frame_index: navigate_problem_frame(
                job_id, candidate_index, frame_index, -1
            ),
            inputs=[repair_job, repair_candidate, repair_frame],
            outputs=repair_outputs,
            queue=False,
        )
        next_problem_button.click(
            lambda job_id, candidate_index, frame_index: navigate_problem_frame(
                job_id, candidate_index, frame_index, 1
            ),
            inputs=[repair_job, repair_candidate, repair_frame],
            outputs=repair_outputs,
            queue=False,
        )
        replacement_file.change(
            capture_repair_upload_context,
            inputs=[replacement_file, repair_job, repair_candidate, repair_frame, repair_base_sha256],
            outputs=repair_upload_context,
            queue=False,
        )
        replace_button.click(
            replace_repair_frame,
            inputs=[repair_job, repair_candidate, repair_frame, replacement_file, repair_base_sha256, repair_upload_context],
            outputs=[repair_action_status, repair_job, *repair_outputs],
        )

        refresh_export_button.click(refresh_exports, inputs=export_job, outputs=[export_job, *export_outputs], queue=False)
        export_job.input(export_projection, inputs=export_job, outputs=export_outputs, queue=False)
        export_candidate.input(export_projection, inputs=[export_job, export_candidate], outputs=export_outputs, queue=False)
        export_button.click(export_one, inputs=[export_job, export_candidate, export_filename, export_overwrite], outputs=[export_status, exported_sheet, export_attachments, export_details])

        save_api_button.click(save_api_key, inputs=api_key, outputs=[header_status, api_status, ai_api_banner, generate_button, api_key])
        clear_api_button.click(clear_api_key, outputs=[header_status, api_status, ai_api_banner, generate_button, api_key])
        refresh_storage_button.click(
            refresh_storage_status,
            outputs=[storage_status, storage_details],
            queue=False,
        )
        run_demo_button.click(run_demo, outputs=[demo_status, demo_details, review_job, *review_outputs])

    return demo


def create_ui_app(
    *,
    root: str | Path | None = None,
    host: str = "127.0.0.1",
    port: int = 7860,
) -> Any:
    """Mount the workflow UI and its exact-pixel REST endpoints together."""

    try:
        import gradio as gr
    except ImportError as exc:  # pragma: no cover
        raise ProviderConfigurationError(
            "operator UI requires Gradio; install requirements.txt",
            details={"dependency": "gradio"},
        ) from exc
    from .api_app import create_api

    service = SpritePipelineService(root)
    app = create_api(root, service=service)
    return gr.mount_gradio_app(
        app,
        build_ui(root, service=service),
        path="/",
        server_name=host,
        server_port=port,
        css=UI_CSS,
        footer_links=[],
        max_file_size="32mb",
    )


def run_ui(*, root: str | Path | None = None, host: str = "127.0.0.1", port: int = 7860) -> None:
    try:
        import uvicorn
    except ImportError as exc:  # pragma: no cover
        raise ProviderConfigurationError(
            "operator UI server requires uvicorn; install requirements.txt",
            details={"dependency": "uvicorn"},
        ) from exc
    uvicorn.run(create_ui_app(root=root, host=host, port=port), host=host, port=port)
