from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
UI_SOURCE = PROJECT_ROOT / "sprite_pipeline" / "ui.py"


def test_pixel_editor_core_node_suite() -> None:
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node.js is not installed; browser editor core test skipped")
    completed = subprocess.run(
        [node, str(PROJECT_ROOT / "tests" / "test_pixel_editor_core.mjs")],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert "pixel-editor-core: ok" in completed.stdout


def test_outer_ui_contains_trusted_pixel_editor_refresh_bridge() -> None:
    from sprite_pipeline.ui import PIXEL_EDITOR_BRIDGE_JS

    source = (PROJECT_ROOT / "sprite_pipeline" / "ui.py").read_text(encoding="utf-8")
    assert 'event.origin !== window.location.origin' in PIXEL_EDITOR_BRIDGE_JS
    assert 'event.data?.type !== "sprite-pixel-editor-saved"' in PIXEL_EDITOR_BRIDGE_JS
    assert 'frame.contentWindow === event.source' in PIXEL_EDITOR_BRIDGE_JS
    assert "frame.contentWindow === sourceFrame" in PIXEL_EDITOR_BRIDGE_JS
    assert 'clickButton("refresh-repair-button")' in PIXEL_EDITOR_BRIDGE_JS
    assert 'clickButton("refresh-review-button")' in PIXEL_EDITOR_BRIDGE_JS
    assert 'sandbox="allow-scripts allow-same-origin allow-downloads allow-modals"' in source


def test_external_repair_upload_is_bound_to_and_cleared_with_frame_context() -> None:
    source = UI_SOURCE.read_text(encoding="utf-8")
    assert "capture_repair_upload_context" in source
    assert "upload_context != expected_upload_context" in source
    assert "repair_base_sha256, replacement_file, repair_upload_context" in source
    assert "replacement_file.change(" in source


def test_review_ui_exposes_local_qa_retry_without_generation() -> None:
    source = (PROJECT_ROOT / "sprite_pipeline" / "ui.py").read_text(encoding="utf-8")
    assert "重新运行本机检查（不消耗 API）" in source
    assert "service.check_candidate" in source
    assert "旧版本的动画预览和问题计数已隐藏" in source


def test_repair_frame_state_priority_and_problem_navigation() -> None:
    from sprite_pipeline.ui import _adjacent_problem_frame_index, _repair_frame_state

    candidate = SimpleNamespace(
        qa_completed_at="now",
        qa_input_sha256="digest",
        qa_algorithm_version="sprite-pipeline-qa-v3",
        error=None,
    )

    def frame(
        status: str,
        *,
        hard: bool = False,
        manual: int = 0,
        external: int = 0,
    ) -> SimpleNamespace:
        return SimpleNamespace(
            review_status=SimpleNamespace(value=status),
            hard_failures=["problem"] if hard else [],
            manual_edit_versions=manual,
            repair_attempts=external,
        )

    assert _repair_frame_state(candidate, frame("repair_requested", hard=True))[0] == "blocked"
    assert _repair_frame_state(candidate, frame("repair_requested"))[0] == "repair"
    assert _repair_frame_state(candidate, frame("pending", manual=1))[0] == "modified"
    assert _repair_frame_state(candidate, frame("approved", manual=1))[0] == "approved"
    assert _repair_frame_state(candidate, frame("approved"))[0] == "approved"
    assert _repair_frame_state(candidate, frame("pending"))[0] == "pending"

    problems = [2, 6, 11]
    assert _adjacent_problem_frame_index(problems, 2, 1) == 6
    assert _adjacent_problem_frame_index(problems, 11, 1) == 2
    assert _adjacent_problem_frame_index(problems, 2, -1) == 11
    assert _adjacent_problem_frame_index(problems, 5, 1) == 6
    assert _adjacent_problem_frame_index(problems, 5, -1) == 2
    assert _adjacent_problem_frame_index([], 5, 1) is None


def test_repair_ui_has_full_timeline_navigation_and_context_preservation() -> None:
    source = UI_SOURCE.read_text(encoding="utf-8")
    assert "完整帧条（点击任意帧查看）" in source
    assert "上一个问题帧" in source
    assert "下一个问题帧" in source
    assert "repair_job_choices_with_context" in source
    assert "inputs=[repair_job, repair_candidate, repair_frame]" in source
    assert "candidate.frames[position].index" in source
    assert "循环上一帧" in source
    assert "循环下一帧" in source


def test_saved_assets_is_separate_and_startup_catalog_stays_lazy() -> None:
    source = UI_SOURCE.read_text(encoding="utf-8")
    generate_section = source.split('with gr.Tab("生成动画", id="generate"):', 1)[1].split(
        'with gr.Tab("已保存资产", id="assets"):', 1
    )[0]
    assets_section = source.split('with gr.Tab("已保存资产", id="assets"):', 1)[1].split(
        'with gr.Tab("播放检查", id="review"):', 1
    )[0]
    job_choices_source = source.split("def job_choices(", 1)[1].split(
        "def saved_asset_choices()", 1
    )[0]

    assert "任务安全中心" not in generate_section
    assert "一个任务一个文件夹" in assets_section
    assert "打开所选任务" in assets_section
    assert "在播放检查中打开" in assets_section
    assert "打开待修补帧" in assets_section
    assert "service.get_job" not in job_choices_source
    assert ".stat()" not in job_choices_source
    assert "task_job.input(\n            select_saved_asset_summary" in source
    select_source = source.split("def select_saved_asset_summary(", 1)[1].split(
        "def reload_saved_asset_catalog", 1
    )[0]
    assert "saved_asset_projection(None)" in select_source
    assert "task_center_projection(None)" in select_source
    assert "saved_asset_projection(job_id" not in select_source
    assert "initial_review = review_payload(None)" in source
    assert "initial_asset = saved_asset_projection(None)" in source
    assert "initial_repair = repair_projection(None)" in source
    assert "initial_export = export_projection(None)" in source
    timer_wiring = source.split("task_timer.tick(", 1)[1].split(")\n", 1)[0]
    assert "reload_saved_asset_catalog" in timer_wiring
    assert "task_center_projection" not in timer_wiring


def test_pixel_editor_loads_recovery_draft_before_dirty_state_cleanup() -> None:
    script = (PROJECT_ROOT / "sprite_pipeline" / "static" / "pixel_editor.js").read_text(
        encoding="utf-8"
    )
    load_session = script.split("async function loadSession()", 1)[1].split(
        'elements.overlayCanvas.addEventListener("pointerdown"', 1
    )[0]
    assert load_session.index("loadDraftCandidate();") < load_session.index("updateDirtyState();")
    assert "if (state.draftCandidate) return;" in script
    assert "sprite-pixel-draft-tab-id" in script
    assert "`${legacyDraftKey()}:${draftPageId}`" in script
    assert "new BroadcastChannel" in script
    assert 'const framePrefix = legacyDraftKey() + ":";' in script
    assert "preserveForeignDraft" in script
    assert "sprite-pixel-ignored-foreign-drafts" in script
    assert "maxHistoryChangedPixels" in script
    assert 'window.addEventListener("pagehide", flushDraftBeforeExit)' in script
    assert 'state.pointerMode === "stroke"' in script
    assert 'state.pointerMode === "stroke" && !state.saving' in script
    assert 'elements.overlayCanvas.addEventListener("lostpointercapture"' in script
    save_version = script.split("async function saveVersion()", 1)[1].split(
        "function loadDraftCandidate()", 1
    )[0]
    assert save_version.index("finishStroke();") < save_version.index("const submittedPixels")
    assert "state.alphaVisibleThreshold" in script
    assert "state.alphaVisibleThreshold," in script.split("function selectVisiblePixels()", 1)[1].split("}", 1)[0]


def test_pixel_editor_loading_has_timeout_retry_and_boot_failure_fallback() -> None:
    html = (PROJECT_ROOT / "sprite_pipeline" / "static" / "pixel_editor.html").read_text(
        encoding="utf-8"
    )
    styles = (PROJECT_ROOT / "sprite_pipeline" / "static" / "pixel_editor.css").read_text(
        encoding="utf-8"
    )
    script = (PROJECT_ROOT / "sprite_pipeline" / "static" / "pixel_editor.js").read_text(
        encoding="utf-8"
    )

    assert 'id="retryLoadButton"' in html
    assert "__spritePixelEditorBoot" in html
    assert "像素画布启动超时" in html
    assert 'pixel_editor.css?v=5' in html
    assert 'pixel_editor.js?v=5' in html
    assert 'pixel_editor_core.js?v=5' in script
    assert "sessionLoadTimeoutMs = 8_000" in script
    assert "maxSessionLoadAttempts = 2" in script
    assert "new AbortController()" in script
    assert "首次读取未完成，正在自动重试" in script
    assert "window.__spritePixelEditorRetry" in script
    assert ".finally(loadSession)" not in script
    assert "if (!state.loaded || !state.pixels || !state.basePixels) return false;" in script
    assert ".loading[hidden]" in styles
    assert "display: none !important;" in styles.split(".loading[hidden]", 1)[1].split("}", 1)[0]
