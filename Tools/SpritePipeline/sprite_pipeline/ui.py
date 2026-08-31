import html
import math
import re
from pathlib import Path
from typing import Any

from PIL import Image

from .errors import HarnessError, ProviderConfigurationError, ValidationHarnessError
from .models import ExportOptions, FrameReviewRequest, GenerationRequest
from .project_profile import DREAMWEAVER_PROFILE, ProjectAction, project_action_choices
from .service import SpritePipelineService
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
.contract-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:10px;margin-top:12px}.contract-card{padding:12px 14px;border-radius:12px;background:rgba(255,255,255,.035)}.contract-card small{display:block;color:var(--muted);margin-bottom:4px}.contract-card b{color:#f2eefb}
.qa-counts{display:flex;gap:8px;flex-wrap:wrap;margin-top:10px}.qa-count{padding:6px 10px;border-radius:999px;background:rgba(255,255,255,.05)}.qa-count.hard{color:#ff9caf}.qa-count.warn{color:#ffd486}.diagnostic-badge{display:inline-block;margin-top:8px;padding:4px 9px;border-radius:999px;color:#2a210f;background:var(--warn);font-size:12px;font-weight:800}
.project-table{width:100%;border-collapse:collapse;margin-top:12px}.project-table th,.project-table td{padding:9px 10px;border-bottom:1px solid var(--border);text-align:left}.project-table th{color:#dcd5ef}.project-table td{color:var(--muted)}
.choice-cards,.static-choice,.workflow-tabs{caret-color:transparent!important}.choice-cards label,.choice-cards label *,.static-choice label,.static-choice label *,.workflow-tabs button,.workflow-tabs button *{cursor:pointer!important;user-select:none!important;-webkit-user-select:none!important;caret-color:transparent!important}.static-choice input[role="combobox"],.static-choice input[readonly]{cursor:pointer!important;user-select:none!important;-webkit-user-select:none!important;caret-color:transparent!important}.choice-cards>div>div{gap:9px!important}.choice-cards label{padding:11px 13px!important;border:1px solid var(--border)!important;border-radius:13px!important;background:rgba(255,255,255,.025)!important}.choice-cards label:hover{border-color:rgba(159,131,255,.72)!important;background:rgba(159,131,255,.09)!important}.choice-cards label:has(input:checked){border-color:var(--accent)!important;background:rgba(159,131,255,.14)!important}
.primary-action button{min-height:48px;font-weight:750;border-radius:13px!important}.pixel-preview img,.frame-gallery img,.sheet-preview img{image-rendering:pixelated!important}
@media(max-width:760px){.flow-map{grid-template-columns:repeat(2,minmax(0,1fr))}.contract-grid{grid-template-columns:1fr}#sprite-hero{padding:21px 19px}}
"""


JOB_STATUS_CN = {"created": "等待开始", "provider_pending": "模型处理中", "review_required": "等待检查", "approved": "已确认", "exported": "已导出", "failed": "处理失败"}
CANDIDATE_STATUS_CN = {"created": "等待素材", "submitting": "正在提交", "provider_pending": "模型处理中", "received": "已收到", "check_failed": "检查未通过", "review_ready": "等待确认", "approved": "已采用", "rejected": "已放弃", "failed": "生成失败"}
REVIEW_STATUS_CN = {"pending": "未判断", "approved": "已通过", "repair_requested": "待修补", "rejected": "不采用"}
QA_CODE_CN = {
    "no_frames": "没有找到序列帧", "frame_count_mismatch": "画面数量与动作规格不一致", "frame_size_mismatch": "画面尺寸不一致",
    "missing_alpha": "缺少透明通道", "blank_frame": "画面完全透明", "corrupt_frame": "图片无法读取",
    "consecutive_duplicate_frames": "连续画面完全重复", "touches_canvas_edge": "角色碰到画布边缘", "safe_margin_violation": "角色离画布边缘过近",
    "area_change": "角色可见面积变化较大", "centroid_jump": "角色重心跳动较大", "palette_deviation": "颜色变化较大",
    "loop_endpoint_difference": "循环首尾差异较大", "ground_baseline_drift": "脚底位置发生跳动", "reference_unavailable": "参考图检查被跳过",
    "frame_position_jump": "整个人物在相邻帧之间发生突变式跳位",
    "centroid_velocity_jump": "相邻帧的位置运动趋势发生突变",
    "palette_unavailable": "色板检查被跳过", "preview_generation_failed": "预览图生成失败",
}
ISSUE_TYPE_CHOICES = [
    ("角色长得不一致", "identity_drift"), ("衣服或配饰变化", "clothing_error"), ("武器不对", "weapon_error"),
    ("肢体异常", "limb_error"), ("动作姿势不对", "pose_error"), ("背景或透明度错误", "alpha_background_error"),
    ("大小或脚底位置跳动", "scale_baseline_error"), ("其他", "other"),
]


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


def build_ui(root: str | Path | None = None) -> Any:
    """Build a project-guided UI backed by the shared service used by API/CLI."""
    try:
        import gradio as gr
    except ImportError as exc:  # pragma: no cover
        raise ProviderConfigurationError("operator UI requires Gradio; install requirements.txt", details={"dependency": "gradio"}) from exc

    service = SpritePipelineService(root)
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
            return _notice("ok", "已保存，尚未调用验证", "Key 已在本机生效，页面不会回显完整内容。")
        return _notice("info", "未配置", "只有“生成动画”需要 PixelLab API；其他功能仍可使用。")

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
            sheet_columns=profile.columns,
            anchor_x=profile.anchor_x,
            anchor_ground_y=profile.anchor_ground_y,
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

    def job_choices(*, approved_only: bool = False, repair_only: bool = False) -> list[tuple[str, str]]:
        result: list[tuple[str, str]] = []
        for row in service.list_jobs():
            try:
                job = service.get_job(row["job_id"])
                if job.character.character_id == "diagnostic_dummy" and job.job_id not in visible_diagnostic_jobs:
                    continue
                # A previously interrupted process can leave a Windows ACL or
                # partial frame directory behind.  Do not let one unreadable
                # historical task prevent the whole UI from opening.
                for candidate in job.candidates:
                    for frame in candidate.frames:
                        service.store.resolve_job_path(job.job_id, frame.active_path).stat()
            except Exception:
                continue
            if approved_only and not any(candidate.status.value == "approved" for candidate in job.candidates):
                continue
            if repair_only and not any(frame.review_status.value == "repair_requested" for candidate in job.candidates for frame in candidate.frames):
                continue
            result.append((job_label(job), job.job_id))
        return result

    def candidate_choices(job: Any, *, approved_only: bool = False, repair_only: bool = False) -> list[tuple[str, int]]:
        result: list[tuple[str, int]] = []
        for candidate in job.candidates:
            if approved_only and candidate.status.value != "approved":
                continue
            if repair_only and not any(frame.review_status.value == "repair_requested" for frame in candidate.frames):
                continue
            result.append((f"生成结果 {_candidate_letter(candidate.candidate_index)} · {CANDIDATE_STATUS_CN.get(candidate.status.value, candidate.status.value)}", candidate.candidate_index))
        return result

    def default_candidate(job: Any, *, approved_only: bool = False, repair_only: bool = False) -> int | None:
        choices = candidate_choices(job, approved_only=approved_only, repair_only=repair_only)
        if not choices:
            return None
        if job.export and any(value == job.export.candidate_index for _label, value in choices):
            return job.export.candidate_index
        return int(choices[0][1])

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
        return _notice("info", f"第 {frame.index + 1} 帧", f"人工状态：{REVIEW_STATUS_CN.get(frame.review_status.value, frame.review_status.value)}；自动提示 {issues} 项；已替换 {frame.repair_attempts}/2 次。")

    def review_payload(job_id: str | None, candidate_index: int | None = None) -> tuple[Any, ...]:
        empty = (
            gr.update(choices=[], value=None, visible=False), None, [], _notice("info", "还没有可检查的动画", "请先到“生成动画”生成，或在本页上传一张已有 Sheet。"),
            "### 自动检查明细\n\n任务完成后会显示在这里。", {}, 0, _notice("info", "尚未选择画面", "点击下方任意帧查看。"),
            gr.update(visible=False, value=False), gr.update(interactive=False), None, None, gr.update(visible=False),
        )
        if not job_id:
            return empty
        try:
            job = service.get_job(str(job_id))
            selected = int(candidate_index) if candidate_index else default_candidate(job)
            if selected is None:
                return empty
            candidate = next(item for item in job.candidates if item.candidate_index == selected)
            choices = candidate_choices(job)
            prefix = service.store.job_dir(job.job_id) / "previews" / candidate.candidate_id
            gallery = [
                (str(service.store.resolve_job_path(job.job_id, frame.active_path)), f"第 {frame.index + 1} 帧 · {REVIEW_STATUS_CN.get(frame.review_status.value, frame.review_status.value)}")
                for frame in candidate.frames
            ]
            hard_count, warning_count = len(candidate.hard_failures), len(candidate.warnings)
            source = {"pixellab": "AI 生成", "import": "已有 Sheet", "fixture": "流程示例"}.get(job.request.provider, job.request.provider)
            diagnostic = '<span class="diagnostic-badge">仅供流程测试，不可作为游戏美术</span>' if candidate.diagnostic_only else ""
            summary = (
                '<div class="section-intro">'
                f"<h3>{_escape(job.action.display_name or job.action.action_id)} · {_escape(CANDIDATE_STATUS_CN.get(candidate.status.value, candidate.status.value))}</h3>"
                f"<p>来源：{_escape(source)} · {len(candidate.frames)} 帧 · {job.action.fps:g} FPS · {'循环' if job.action.loop else '单次'}</p>"
                f'<div class="qa-counts"><span class="qa-count hard">{hard_count} 个阻止问题</span><span class="qa-count warn">{warning_count} 条提醒</span></div>{diagnostic}</div>'
            )
            return (
                gr.update(choices=choices, value=selected, visible=len(choices) > 1),
                str(prefix.with_suffix(".zoom.gif")) if prefix.with_suffix(".zoom.gif").is_file() else None,
                gallery, summary, issue_markdown(candidate), {"ok": True, "job": job.model_dump(mode="json")}, 0,
                selected_frame_html(job, candidate, 0), gr.update(visible=warning_count > 0, value=False),
                gr.update(interactive=candidate.status.value == "review_ready" and hard_count == 0),
                str(prefix.with_suffix(".overlay.png")) if prefix.with_suffix(".overlay.png").is_file() else None,
                str(prefix.with_suffix(".baseline.png")) if prefix.with_suffix(".baseline.png").is_file() else None,
                gr.update(visible=len(choices) > 1),
            )
        except Exception as exc:
            return gr.update(), None, [], _notice("error", "动画无法加载", _human_error(exc)), "", _error_payload(exc), 0, _notice("error", "无法选择画面", _human_error(exc)), gr.update(visible=False, value=False), gr.update(interactive=False), None, None, gr.update(visible=False)

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
            ))
            job = service.generate_job(job.job_id, wait=True)
            pending = any(item.status.value == "provider_pending" for item in job.candidates)
            return (
                _notice("ok", "PixelLab 已接受任务" if pending else "生成完成", "模型仍在处理，稍后到“播放检查”刷新。" if pending else "结果已进入“播放检查”，请播放整段动画并逐帧确认。"),
                {"ok": True, "job": job.model_dump(mode="json")},
                updated_reference_state,
                gr.update(choices=official_character_choices(), value=character_id),
                review_job_update(job.job_id),
                *review_payload(job.job_id),
            )
        except Exception as exc:
            job_id = job.job_id if job is not None else None
            return (
                _notice("error", "生成没有完成", _human_error(exc)),
                _error_payload(exc),
                updated_reference_state,
                gr.update(),
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
            if action is None:
                problems.append("还没有选择动画类型")
            else:
                expected_width, expected_height = action.sheet_size
                if (result["width"], result["height"]) != (expected_width, expected_height):
                    problems.append(
                        f"图片是 {result['width']}×{result['height']}，但“{action.display_name}”必须是 "
                        f"{expected_width}×{expected_height}"
                    )
                cell_bounds = result["cell_bounds"]
                expected_cells = set(action.frame_cells)
                missing_frames = [
                    index + 1
                    for index, (column, row) in enumerate(action.frame_cells)
                    if row * result["columns"] + column >= len(cell_bounds)
                    or cell_bounds[row * result["columns"] + column] is None
                ]
                occupied_cells = {
                    (index % result["columns"], index // result["columns"])
                    for index, bounds in enumerate(cell_bounds)
                    if bounds is not None
                }
                unexpected_cells = sorted(occupied_cells - expected_cells, key=lambda cell: (cell[1], cell[0]))
                if missing_frames:
                    problems.append("项目播放帧 F" + "、F".join(str(index) for index in missing_frames) + " 为空")
                if unexpected_cells:
                    labels = "、".join(f"第 {row + 1} 行第 {column + 1} 格" for column, row in unexpected_cells)
                    problems.append(f"应为透明空格的位置仍有画面：{labels}")
            occupied_count = sum(bounds is not None for bounds in result["cell_bounds"])
            order_text = (
                " → ".join(
                    f"F{index + 1}=第{row + 1}行第{column + 1}格"
                    for index, (column, row) in enumerate(action.frame_cells)
                )
                if action is not None
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
            else:
                assert action is not None
                summary += f'<div class="notice ok"><strong>与项目规格一致</strong>将按“{_escape(action.display_name)}”的 {action.fps:g} FPS、{"循环" if action.loop else "单次"}方式进入检查。</div>'
            summary += "</div>"
            state = {**result, "valid": not problems, "action_id": action_id}
            return build_grid_overlay(
                source,
                result,
                frame_cells=action.frame_cells if action is not None else None,
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
            job = service.create_job(GenerationRequest(
                character_id=profile.character_id, action_id=action_id, provider="import", candidate_count=1,
            ))
            job = service.ingest_candidate(job.job_id, 1, source, source_kind="sheet", columns=profile.columns)
            return _notice("ok", "Sheet 已切分并加入检查", "请继续在本页播放整段动画，再决定采用或修补。"), {"ok": True, "job": job.model_dump(mode="json")}, review_job_update(job.job_id), *review_payload(job.job_id)
        except Exception as exc:
            job_id = job.job_id if job is not None else None
            return _notice("error", "已有 Sheet 没有加入检查", _human_error(exc)), _error_payload(exc), review_job_update(job_id), *review_payload(job_id)

    def refresh_review(current: str | None) -> tuple[Any, ...]:
        choices = job_choices()
        values = {value for _label, value in choices}
        selected = current if current in values else choices[0][1] if choices else None
        return gr.update(choices=choices, value=selected), *review_payload(selected)

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

    def repair_projection(job_id: str | None, candidate_index: int | None = None, frame_index: int | None = None) -> tuple[Any, ...]:
        empty = (
            gr.update(choices=[], value=None, visible=False), gr.update(choices=[], value=None), None, [],
            _notice("info", "当前没有待修补帧", "先到“播放检查”选择问题帧并点击“把当前帧送去修补”。"),
            gr.update(interactive=False), gr.update(value="other"), gr.update(value=""),
        )
        if not job_id:
            return empty
        try:
            job = service.get_job(str(job_id))
            candidates = candidate_choices(job, repair_only=True)
            selected_candidate = int(candidate_index) if candidate_index else default_candidate(job, repair_only=True)
            if selected_candidate is None:
                return empty
            candidate = next(item for item in job.candidates if item.candidate_index == selected_candidate)
            frames = [frame for frame in candidate.frames if frame.review_status.value == "repair_requested"]
            selected_frame = int(frame_index) if frame_index is not None and any(frame.index == int(frame_index) for frame in frames) else frames[0].index
            frame = next(item for item in frames if item.index == selected_frame)
            current = service.store.resolve_job_path(job.job_id, frame.active_path)
            neighbors = [
                (str(service.store.resolve_job_path(job.job_id, candidate.frames[index].active_path)), f"第 {index + 1} 帧")
                for index in range(max(0, selected_frame - 1), min(len(candidate.frames), selected_frame + 2))
            ]
            frame_choices = [(f"第 {item.index + 1} 帧 · {item.review_note or '待修补'}", item.index) for item in frames]
            return (
                gr.update(choices=candidates, value=selected_candidate, visible=len(candidates) > 1), gr.update(choices=frame_choices, value=selected_frame),
                str(current), neighbors, _notice("warn", f"正在修补第 {selected_frame + 1} 帧", f"只替换这一格；其他 {len(candidate.frames) - 1} 帧不变。当前已替换 {frame.repair_attempts}/2 次。"),
                gr.update(interactive=frame.repair_attempts < 2), gr.update(value=frame.issue_type.value if frame.issue_type else "other"), gr.update(value=frame.review_note),
            )
        except Exception as exc:
            return (*empty[:4], _notice("error", "修补任务无法加载", _human_error(exc)), *empty[5:])

    def refresh_repairs(current: str | None) -> tuple[Any, ...]:
        choices = job_choices(repair_only=True)
        values = {value for _label, value in choices}
        selected = current if current in values else choices[0][1] if choices else None
        return gr.update(choices=choices, value=selected), *repair_projection(selected)

    def replace_repair_frame(job_id: str | None, candidate_index: int | None, frame_index: int | None, replacement: Any) -> tuple[Any, ...]:
        try:
            if replacement is None:
                raise ValidationHarnessError("请上传修补后的透明 PNG")
            service.replace_frame(str(job_id), int(candidate_index), int(frame_index), _uploaded_path(replacement))
            choices = job_choices(repair_only=True)
            selected = str(job_id) if any(value == str(job_id) for _label, value in choices) else choices[0][1] if choices else None
            return _notice("ok", "替换帧已保存并重新检查", "原图仍保留；请回到“播放检查”重新播放整段动画。"), gr.update(choices=choices, value=selected), *repair_projection(selected), gr.update(value=None)
        except Exception as exc:
            return _notice("error", "替换没有生效", _human_error(exc)), gr.update(choices=job_choices(repair_only=True), value=job_id), *repair_projection(job_id, candidate_index, frame_index), gr.update()

    def export_projection(job_id: str | None, candidate_index: int | None = None) -> tuple[Any, ...]:
        empty = gr.update(choices=[], value=None, visible=False), _notice("info", "还没有可导出的动画", "先在“播放检查”确认采用一组动画。"), None, gr.update(value=""), gr.update(interactive=False)
        if not job_id:
            return empty
        try:
            job = service.get_job(str(job_id))
            choices, selected = candidate_choices(job, approved_only=True), int(candidate_index) if candidate_index else default_candidate(job, approved_only=True)
            if selected is None:
                return empty
            candidate = next(item for item in job.candidates if item.candidate_index == selected)
            columns = job.action.sheet_columns or job.character.sheet_columns
            rows = job.action.sheet_rows or math.ceil(len(candidate.frames) / columns)
            width, height = job.character.cell_width * columns, job.character.cell_height * rows
            frame_cells = job.action.frame_cells
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
            summary = (
                '<div class="section-intro"><h3>最终 Sprite Sheet</h3>'
                f"<p>输出尺寸：{width}×{height}；单帧：{job.character.cell_width}×{job.character.cell_height}；"
                f"排列：{columns} 列×{rows} 行；顺序：{order_text}；背景：透明 RGBA。</p>"
                '<div class="notice info"><strong>关于位置对齐</strong>每帧保留完整画布，不会紧贴角色裁切，也不会逐帧自动居中。导出会保持你在检查页确认过的坐标。</div></div>'
            )
            prefix = service.store.job_dir(job.job_id) / "previews" / candidate.candidate_id
            preview = prefix.with_suffix(".sheet.png")
            return gr.update(choices=choices, value=selected, visible=len(choices) > 1), summary, str(preview) if preview.is_file() else None, gr.update(value=filename), gr.update(interactive=True)
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
            root_path = service.settings.root
            return _notice("ok", "Sprite Sheet 已导出到工具暂存区", "不会自动覆盖游戏工程。确认无误后再由你复制到 Godot 素材目录。"), str(root_path / job.export.sheet_path), [str(root_path / job.export.preview_path), str(root_path / job.export.recipe_path), str(root_path / job.export.qa_path)], {"ok": True, "job": job.model_dump(mode="json")}
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
    initial_jobs = job_choices(); initial_job = initial_jobs[0][1] if initial_jobs else None; initial_review = review_payload(initial_job)
    initial_repairs = job_choices(repair_only=True); initial_repair_job = initial_repairs[0][1] if initial_repairs else None; initial_repair = repair_projection(initial_repair_job)
    initial_exports = job_choices(approved_only=True); initial_export_job = initial_exports[0][1] if initial_exports else None; initial_export = export_projection(initial_export_job)

    with gr.Blocks(title="像素角色动画工作台", fill_width=True) as demo:
        gr.HTML(
            '<div id="sprite-hero"><h1>像素角色动画工作台</h1><p>先看指引，再在“生成动画”中导入角色原型图、填写提示词并生成；随后依次播放检查、按需修补并导出固定网格 PNG。</p>'
            '<div class="flow-map"><div class="flow-box"><small>1</small>指引示例</div><div class="flow-box"><small>2</small>生成动画<br>导入原图 + 提示词</div>'
            '<div class="flow-box"><small>3</small>播放检查</div><div class="flow-box"><small>4</small>逐帧修补</div><div class="flow-box"><small>5</small>导出 Sheet</div></div></div>'
        )
        header_status = gr.HTML(header_status_html())
        with gr.Tabs(elem_classes=["workflow-tabs"]):
            with gr.Tab("指引与示例", id="example"):
                gr.HTML('<div class="section-intro"><h2>先从这里了解完整流程</h2><p>真正生成时，你需要提供角色原型图、角色外观提示词和本次动作提示词。这里使用流程测试机器人解释动画帧与最终 Sheet；它不联网、不消耗额度，也不代表真实生成质量。待机示例没有位移动作，所以保持原位；其他动作允许自然、连续地移动。</p></div><div class="contract-grid"><div class="contract-card"><small>角色原型图</small><b>模型生成动作时必须保持的角色形象</b></div><div class="contract-card"><small>位置连续性</small><b>允许自然移动，不允许相邻帧突然跳位</b></div><div class="contract-card"><small>Sprite Sheet</small><b>固定大小网格，不逐帧裁剪或强制居中</b></div></div>')
                run_demo_button = gr.Button("运行离线示例", variant="primary", elem_classes=["primary-action"]); demo_status = gr.HTML()
                with gr.Accordion("示例任务详情", open=False): demo_details = gr.JSON()

            with gr.Tab("生成动画", id="generate"):
                gr.HTML('<div class="section-intro"><h2>从角色原型生成动作</h2><p>这一步已经包含“导入”：先上传角色原型 PNG，再填写角色外观提示词和本次动作提示词。生成时会要求模型保持相邻帧的位置轨迹连续，但不会把人物强制钉在画布中央；生成完成后，结果会直接进入“播放检查”。</p><div class="contract-grid"><div class="contract-card"><small>输入 1</small><b>角色原型 PNG</b></div><div class="contract-card"><small>输入 2</small><b>角色外观 + 动作提示词</b></div><div class="contract-card"><small>生成结果</small><b>固定网格、前后连续的动画候选</b></div></div></div>')
                ai_api_banner = gr.HTML(api_banner_html())
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
                        candidate_count = gr.Slider(1, 5, value=3, step=1, label="生成几个候选？")
                        with gr.Accordion("复现与调试设置", open=False):
                            seed = gr.Textbox(label="Seed（可选）", placeholder="留空则自动生成并记录")
                generate_button = gr.Button("开始生成候选", variant="primary", interactive=api_configured(), elem_classes=["primary-action"])
                generation_status = gr.HTML()
                with gr.Accordion("技术详情（排错时再看）", open=False): generation_details = gr.JSON(label="任务记录")

            with gr.Tab("播放检查", id="review"):
                gr.HTML('<div class="section-intro"><h2>播放与检查</h2><p>先按游戏速度看整段，再点击单帧。重点观察前一帧和后一帧的动作与位置能否接上、脸或武器是否突然变化、背景是否透明。角色可以连续移动；只有突变式跳位才会被拦截。画布外框始终保持不变。</p></div>')
                with gr.Accordion("检查一张已有 Sprite Sheet", open=False):
                    gr.Markdown("如果动画不是刚刚由本工具生成，而是你已经拥有的一张 Sheet，请在这里上传。它只会被切分并送入本页检查，不会作为角色原型参与生成。")
                    with gr.Row():
                        with gr.Column():
                            import_file = gr.File(label="已有 Sprite Sheet（PNG）", file_count="single", file_types=[".png"], type="filepath")
                            import_action = gr.Dropdown(actions, value=None, label="这是什么动画？（必须确认）", filterable=False, elem_classes=["static-choice"])
                            gr.Markdown("请按动画含义选择，不能只看帧数：16 帧可能是待机或行走，12 帧可能是跳跃或受击。")
                            gr.Markdown("检查规格锁定为 **128×128/格、4 列、RGBA**；图片高度、透明空格和实际播放格位会随所选动作自动核对。")
                        with gr.Column(scale=2):
                            import_grid_preview = gr.Image(label="切分网格预览", type="pil", interactive=False, elem_classes=["sheet-preview"])
                    import_inspection = gr.HTML(_notice("info", "等待已有 Sheet", "上传后先确认网格和动作类型。")); import_state = gr.State({})
                    import_button = gr.Button("切分并加入播放检查", variant="primary", interactive=False, elem_classes=["primary-action"])
                    import_status = gr.HTML()
                    with gr.Accordion("检查素材记录（排错时再看）", open=False): import_details = gr.JSON(label="已有 Sheet 任务记录")
                with gr.Row():
                    review_job = gr.Dropdown(initial_jobs, value=initial_job, label="选择要检查的动画", filterable=False, elem_classes=["static-choice"], scale=5)
                    refresh_review_button = gr.Button("刷新", scale=1)
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
                with gr.Row(): mark_ok_button = gr.Button("当前帧没有问题"); mark_repair_button = gr.Button("把当前帧送去修补")
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
                gr.HTML('<div class="section-intro"><h2>修补问题帧</h2><p>适合整段基本可用、只有 1–2 帧出错的情况。当前版本采用版本化替换：请先在外部图像工具修好单帧，再上传相同尺寸的透明 PNG；原图会保留。</p></div>')
                with gr.Row():
                    repair_job = gr.Dropdown(initial_repairs, value=initial_repair_job, label="含待修补帧的动画", filterable=False, elem_classes=["static-choice"], scale=5)
                    refresh_repair_button = gr.Button("刷新", scale=1)
                repair_candidate = gr.Dropdown(initial_repair[0].get("choices", []), value=initial_repair[0].get("value"), visible=bool(initial_repair[0].get("visible", False)), label="生成结果", filterable=False, elem_classes=["static-choice"])
                repair_frame = gr.Dropdown(initial_repair[1].get("choices", []), value=initial_repair[1].get("value"), label="待修补帧", filterable=False, elem_classes=["static-choice"])
                repair_summary = gr.HTML(initial_repair[4])
                with gr.Row():
                    repair_current = gr.Image(initial_repair[2], label="当前版本", type="filepath", interactive=False, height=330, elem_classes=["pixel-preview"])
                    repair_neighbors = gr.Gallery(initial_repair[3], label="上一帧 / 当前帧 / 下一帧", columns=3, height=330, allow_preview=False, elem_classes=["frame-gallery"])
                with gr.Row():
                    repair_issue_type = gr.Dropdown(ISSUE_TYPE_CHOICES, value=initial_repair[6].get("value", "other"), label="问题类型（记录用）", interactive=False, filterable=False, elem_classes=["static-choice"])
                    repair_note = gr.Textbox(value=initial_repair[7].get("value", ""), label="原问题说明", interactive=False)
                replacement_file = gr.File(label="修补后的透明 PNG（必须仍为 128×128）", file_count="single", file_types=[".png"], type="filepath")
                replace_button = gr.Button("保存替换并重新检查", variant="primary", interactive=bool(initial_repair[5].get("interactive", False)), elem_classes=["primary-action"])
                repair_action_status = gr.HTML()

            with gr.Tab("导出", id="export"):
                gr.HTML('<div class="section-intro"><h2>导出 Sprite Sheet</h2><p>把已通过检查的帧按固定网格合成一张透明 PNG，供 Godot SpriteFrames 使用。首版只写入工具暂存区，不直接覆盖你的游戏工程。</p></div>')
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
                gr.HTML('<div class="section-intro"><h2>PixelLab API</h2><p>只用于“生成动画”。Key 保存在本机 Tools/SpritePipeline/.env，不会写入任务记录、导出文件或日志，页面也不会回显完整内容。</p></div>')
                api_status = gr.HTML(api_settings_status()); api_key = gr.Textbox(label="API Key", type="password", placeholder="粘贴后点击保存；保存成功会自动清空输入框")
                with gr.Row(): save_api_button = gr.Button("保存并立即生效", variant="primary"); clear_api_button = gr.Button("清除已保存的 Key")
                gr.HTML(
                    '<div class="section-intro"><h2>游戏项目</h2>'
                    f'<p>这里展示的是资产清单中的项目合同，不是模型默认值。项目：{_escape(profile.project_name)}；引擎：{_escape(profile.engine)}；目标角色：{_escape(profile.character_name)}。</p>'
                    f'<div class="contract-grid"><div class="contract-card"><small>单帧</small><b>{profile.cell_width}×{profile.cell_height} RGBA</b></div><div class="contract-card"><small>网格</small><b>每行 {profile.columns} 格；高度和播放格位按动作</b></div><div class="contract-card"><small>参考锚点 / 运行时偏移</small><b>({profile.anchor_x},{profile.anchor_ground_y}) / ({profile.sprite_offset_x},{profile.sprite_offset_y})</b></div></div></div>'
                    + '<table class="project-table"><thead><tr><th>动画</th><th>输出规格</th><th>播放</th><th>文件名</th><th>工程状态</th></tr></thead><tbody>'
                    + "".join(
                        f"<tr><td>{_escape(item.display_name)}</td>"
                        f"<td>{item.sheet_size[0]}×{item.sheet_size[1]} · {item.frame_count} 帧{' · 稀疏格位' if item.is_sparse else ''}</td>"
                        f"<td>{item.fps:g} FPS{'（资源场景 ' + format(item.scene_fps, 'g') + '）' if item.scene_fps != item.fps else ''} · {'循环' if item.loop else '单次'}</td>"
                        f"<td>{_escape(item.filename)}</td>"
                        f"<td>{'现有资产合同' if item.integration_status == 'existing' else '新增，待 Godot 接线'}</td></tr>"
                        for item in profile.actions
                    )
                    + '</tbody></table>'
                    + _notice("info", "攻击动作已按项目格位适配", "地面攻击和空中攻击会导出 5 个播放帧及项目要求的透明空格；向后闪避是新增资产，导出后仍需在 Godot 状态机中接线。")
                )

        review_outputs = [review_candidate, animation_preview, frame_gallery, review_summary, review_issues, review_details, selected_frame_index, selected_frame_banner, acknowledge, approve_button, overlay_preview, baseline_preview, review_candidate_group]
        repair_outputs = [repair_candidate, repair_frame, repair_current, repair_neighbors, repair_summary, replace_button, repair_issue_type, repair_note]
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
            ],
            outputs=[generation_status, generation_details, generation_reference_state, generate_character, review_job, *review_outputs],
        )
        import_file.change(inspect_uploaded_sheet, inputs=[import_file, import_action], outputs=[import_grid_preview, import_inspection, import_state, import_button], queue=False)
        import_action.input(inspect_uploaded_sheet, inputs=[import_file, import_action], outputs=[import_grid_preview, import_inspection, import_state, import_button], queue=False)
        import_button.click(import_sheet, inputs=[import_file, import_action, import_state], outputs=[import_status, import_details, review_job, *review_outputs])

        refresh_review_button.click(refresh_review, inputs=review_job, outputs=[review_job, *review_outputs], queue=False)
        review_job.input(review_payload, inputs=review_job, outputs=review_outputs, queue=False)
        review_candidate.input(review_payload, inputs=[review_job, review_candidate], outputs=review_outputs, queue=False)
        frame_gallery.select(select_frame, inputs=[review_job, review_candidate], outputs=[selected_frame_index, selected_frame_banner], queue=False)
        mark_ok_button.click(lambda j, c, f, i, n: mark_frame(j, c, f, "approved", i, n), inputs=[review_job, review_candidate, selected_frame_index, issue_type, review_note], outputs=[review_action_status, *review_outputs, repair_job, *repair_outputs])
        mark_repair_button.click(lambda j, c, f, i, n: mark_frame(j, c, f, "repair_requested", i, n), inputs=[review_job, review_candidate, selected_frame_index, issue_type, review_note], outputs=[review_action_status, *review_outputs, repair_job, *repair_outputs])
        approve_button.click(approve_candidate, inputs=[review_job, review_candidate, acknowledge], outputs=[review_action_status, *review_outputs, export_job, *export_outputs])
        reject_button.click(reject_candidate, inputs=[review_job, review_candidate, review_note], outputs=[review_action_status, *review_outputs])

        refresh_repair_button.click(refresh_repairs, inputs=repair_job, outputs=[repair_job, *repair_outputs], queue=False)
        repair_job.input(repair_projection, inputs=repair_job, outputs=repair_outputs, queue=False)
        repair_candidate.input(repair_projection, inputs=[repair_job, repair_candidate], outputs=repair_outputs, queue=False)
        repair_frame.input(repair_projection, inputs=[repair_job, repair_candidate, repair_frame], outputs=repair_outputs, queue=False)
        replace_button.click(replace_repair_frame, inputs=[repair_job, repair_candidate, repair_frame, replacement_file], outputs=[repair_action_status, repair_job, *repair_outputs, replacement_file])

        refresh_export_button.click(refresh_exports, inputs=export_job, outputs=[export_job, *export_outputs], queue=False)
        export_job.input(export_projection, inputs=export_job, outputs=export_outputs, queue=False)
        export_candidate.input(export_projection, inputs=[export_job, export_candidate], outputs=export_outputs, queue=False)
        export_button.click(export_one, inputs=[export_job, export_candidate, export_filename, export_overwrite], outputs=[export_status, exported_sheet, export_attachments, export_details])

        save_api_button.click(save_api_key, inputs=api_key, outputs=[header_status, api_status, ai_api_banner, generate_button, api_key])
        clear_api_button.click(clear_api_key, outputs=[header_status, api_status, ai_api_banner, generate_button, api_key])
        run_demo_button.click(run_demo, outputs=[demo_status, demo_details, review_job, *review_outputs])

    return demo


def run_ui(*, root: str | Path | None = None, host: str = "127.0.0.1", port: int = 7860) -> None:
    build_ui(root).launch(server_name=host, server_port=port, share=False, css=UI_CSS, footer_links=[], max_file_size="32mb")
