from __future__ import annotations

import base64
import binascii
import tempfile
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from .errors import (
    ConflictError,
    ExportBlockedError,
    HarnessError,
    NotFoundError,
    ProviderConfigurationError,
    ValidationHarnessError,
)
from .models import ExportOptions, FrameReviewRequest, GenerationRequest
from .service import SpritePipelineService


class _Body(BaseModel):
    model_config = ConfigDict(extra="forbid")


class GenerateBody(_Body):
    wait: bool = False
    candidate_index: int | None = Field(default=None, ge=1)


class FramesBody(_Body):
    frames: list[str] = Field(min_length=1, max_length=64)


class ApproveBody(_Body):
    reviewer: str = Field(default="api", min_length=1, max_length=100)
    acknowledge_warnings: bool = False


class RejectBody(_Body):
    reviewer: str = Field(default="api", min_length=1, max_length=100)
    note: str = Field(default="", max_length=2000)


class ReplacementBody(_Body):
    png_base64: str


class PixelEditBody(_Body):
    width: int = Field(ge=1, le=512)
    height: int = Field(ge=1, le=512)
    rgba_base64: str = Field(min_length=4, max_length=2_000_000)
    base_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    reviewer: str = Field(default="web_pixel_editor", min_length=1, max_length=100)


class AttachProviderJobBody(_Body):
    provider_job_id: str = Field(min_length=6, max_length=200)


def _job(job: Any) -> dict[str, Any]:
    return job.model_dump(mode="json")


def create_api(
    root: str | Path | None = None,
    *,
    service: SpritePipelineService | None = None,
) -> Any:
    """Create the FastAPI app lazily so CLI/offline processing needs no FastAPI."""

    try:
        from fastapi import FastAPI, Header, Request
        from fastapi.exceptions import RequestValidationError
        from fastapi.responses import FileResponse, JSONResponse
        from fastapi.staticfiles import StaticFiles
    except ImportError as exc:  # pragma: no cover - depends on optional install
        raise ProviderConfigurationError(
            "REST API requires FastAPI; install requirements.txt",
            details={"dependency": "fastapi"},
        ) from exc

    service = service or SpritePipelineService(root)
    from .recovery import RecoveryWorker

    recovery_worker = RecoveryWorker(service)

    @asynccontextmanager
    async def lifespan(_app: Any) -> Any:
        recovery_worker.start()
        try:
            yield
        finally:
            recovery_worker.stop()

    app = FastAPI(
        title="Sprite Generation Harness API",
        version="0.1.0",
        description="Local API for the same durable workflow used by Codex and Gradio.",
        lifespan=lifespan,
    )
    app.state.sprite_pipeline_service = service
    app.state.sprite_pipeline_recovery = recovery_worker
    static_dir = Path(__file__).resolve().parent / "static"
    app.mount(
        "/pixel-editor-assets",
        StaticFiles(directory=static_dir),
        name="pixel-editor-assets",
    )

    @app.get("/pixel-editor", include_in_schema=False)
    def pixel_editor_page() -> FileResponse:
        return FileResponse(
            static_dir / "pixel_editor.html",
            media_type="text/html",
            headers={"Cache-Control": "no-store"},
        )

    @app.exception_handler(HarnessError)
    async def harness_error_handler(_request: Request, exc: HarnessError) -> JSONResponse:
        if isinstance(exc, NotFoundError):
            status = 404
        elif isinstance(exc, (ConflictError, ExportBlockedError)):
            status = 409
        elif isinstance(exc, (ValidationHarnessError, ProviderConfigurationError)):
            status = 422
        else:
            status = 502
        return JSONResponse(
            status_code=status,
            content={"schema_version": 1, "ok": False, "error": exc.as_dict()},
        )

    @app.exception_handler(RequestValidationError)
    async def request_validation_handler(_request: Request, exc: RequestValidationError) -> JSONResponse:
        errors = [
            {"location": list(item.get("loc", ())), "message": item.get("msg", "invalid input"), "type": item.get("type")}
            for item in exc.errors()
        ]
        return JSONResponse(
            status_code=422,
            content={
                "schema_version": 1,
                "ok": False,
                "error": {"code": "validation_error", "message": "request validation failed", "details": {"errors": errors}},
            },
        )

    @app.exception_handler(Exception)
    async def unexpected_error_handler(_request: Request, exc: Exception) -> JSONResponse:
        return JSONResponse(
            status_code=500,
            content={
                "schema_version": 1,
                "ok": False,
                "error": {
                    "code": "internal_error",
                    "message": "unexpected harness failure",
                    "details": {"type": type(exc).__name__},
                },
            },
        )

    @app.get("/health")
    def health() -> dict[str, Any]:
        return {
            "schema_version": 1,
            "ok": True,
            "version": "0.1.0",
            "pixellab_configured": bool(service.settings.pixellab_api_key),
            "data_root": str(service.settings.data_root),
            "recovery_worker": recovery_worker.snapshot(),
        }

    @app.get("/v1/system/storage")
    def storage_status() -> dict[str, Any]:
        return {"schema_version": 1, "ok": True, "data": service.storage_status()}

    @app.get("/v1/account/balance")
    def account_balance(refresh: bool = True) -> dict[str, Any]:
        snapshot = (
            service.refresh_pixellab_balance()
            if refresh
            else service.get_cached_balance()
        )
        return {"schema_version": 1, "ok": True, "data": {"balance": snapshot}}

    @app.get("/v1/account/estimate")
    def account_estimate(
        character_id: str,
        action_id: str,
        candidate_count: int = 1,
    ) -> dict[str, Any]:
        estimate = service.estimate_pixellab_generation_units(
            character_id,
            action_id,
            candidate_count=candidate_count,
        )
        return {"schema_version": 1, "ok": True, "data": {"estimate": estimate}}

    @app.post("/v1/recovery/run")
    def run_recovery() -> dict[str, Any]:
        return {
            "schema_version": 1,
            "ok": True,
            "data": {"recovery": service.recover_pending_jobs()},
        }

    @app.get("/v1/recovery/status")
    def recovery_status() -> dict[str, Any]:
        return {
            "schema_version": 1,
            "ok": True,
            "data": {"worker": recovery_worker.snapshot()},
        }

    @app.get("/v1/presets")
    def list_presets() -> dict[str, Any]:
        return {"schema_version": 1, "ok": True, "data": service.list_presets()}

    @app.get("/v1/jobs")
    def list_jobs() -> dict[str, Any]:
        return {"schema_version": 1, "ok": True, "data": {"jobs": service.list_jobs()}}

    @app.post("/v1/jobs", status_code=201)
    def create_job(
        body: GenerationRequest,
        idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    ) -> dict[str, Any]:
        if idempotency_key is not None:
            normalized_key = idempotency_key.strip()
            if not normalized_key:
                raise ValidationHarnessError("Idempotency-Key cannot be blank")
            if body.request_key and body.request_key != normalized_key:
                raise ConflictError(
                    "body request_key and Idempotency-Key header do not match"
                )
            body = GenerationRequest.model_validate(
                {
                    **body.model_dump(mode="python"),
                    "request_key": normalized_key,
                }
            )
        return {"schema_version": 1, "ok": True, "data": {"job": _job(service.create_job(body))}}

    @app.get("/v1/jobs/{job_id}")
    def get_job(job_id: str) -> dict[str, Any]:
        return {"schema_version": 1, "ok": True, "data": {"job": _job(service.get_job(job_id))}}

    @app.get("/v1/jobs/{job_id}/candidates/{candidate_index}/safety")
    def candidate_safety(job_id: str, candidate_index: int) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "ok": True,
            "data": {"safety": service.candidate_safety(job_id, candidate_index)},
        }

    @app.post("/v1/jobs/{job_id}/generate")
    def generate(job_id: str, body: GenerateBody) -> dict[str, Any]:
        job = service.generate_job(job_id, wait=body.wait, candidate_index=body.candidate_index)
        return {"schema_version": 1, "ok": True, "data": {"job": _job(job)}}

    @app.post("/v1/jobs/{job_id}/candidates/{candidate_index}/recover")
    def recover(job_id: str, candidate_index: int) -> dict[str, Any]:
        job = service.recover_completed_candidate(job_id, candidate_index)
        return {"schema_version": 1, "ok": True, "data": {"job": _job(job)}}

    @app.post("/v1/jobs/{job_id}/candidates/{candidate_index}/attach-provider-job")
    def attach_provider_job(
        job_id: str,
        candidate_index: int,
        body: AttachProviderJobBody,
    ) -> dict[str, Any]:
        job = service.attach_provider_job_id(
            job_id,
            candidate_index,
            body.provider_job_id,
        )
        return {"schema_version": 1, "ok": True, "data": {"job": _job(job)}}

    @app.post("/v1/jobs/{job_id}/candidates/{candidate_index}/frames")
    def ingest_frames(job_id: str, candidate_index: int, body: FramesBody) -> dict[str, Any]:
        job = service.ingest_candidate_base64(job_id, candidate_index, body.frames)
        return {"schema_version": 1, "ok": True, "data": {"job": _job(job)}}

    @app.post("/v1/jobs/{job_id}/candidates/{candidate_index}/check")
    def check(job_id: str, candidate_index: int) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "ok": True,
            "data": {"job": _job(service.check_candidate(job_id, candidate_index))},
        }

    @app.post("/v1/jobs/{job_id}/candidates/{candidate_index}/reviews/frame")
    def review_frame(job_id: str, candidate_index: int, body: FrameReviewRequest) -> dict[str, Any]:
        job = service.review_frame(job_id, candidate_index, body)
        return {"schema_version": 1, "ok": True, "data": {"job": _job(job)}}

    @app.post("/v1/jobs/{job_id}/candidates/{candidate_index}/approve")
    def approve(job_id: str, candidate_index: int, body: ApproveBody) -> dict[str, Any]:
        job = service.approve_candidate(
            job_id,
            candidate_index,
            reviewer=body.reviewer,
            acknowledge_warnings=body.acknowledge_warnings,
        )
        return {"schema_version": 1, "ok": True, "data": {"job": _job(job)}}

    @app.post("/v1/jobs/{job_id}/candidates/{candidate_index}/reject")
    def reject(job_id: str, candidate_index: int, body: RejectBody) -> dict[str, Any]:
        job = service.reject_candidate(job_id, candidate_index, reviewer=body.reviewer, note=body.note)
        return {"schema_version": 1, "ok": True, "data": {"job": _job(job)}}

    @app.post("/v1/jobs/{job_id}/candidates/{candidate_index}/frames/{frame_index}/replace")
    def replace_frame(
        job_id: str,
        candidate_index: int,
        frame_index: int,
        body: ReplacementBody,
    ) -> dict[str, Any]:
        encoded = body.png_base64.split(",", 1)[1] if body.png_base64.startswith("data:") and "," in body.png_base64 else body.png_base64
        max_encoded = ((service.settings.max_download_bytes + 2) // 3) * 4 + 16
        if len(encoded) > max_encoded:
            raise ValidationHarnessError("replacement base64 exceeds configured size limit")
        try:
            payload = base64.b64decode(encoded, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise ValidationHarnessError("invalid replacement base64") from exc
        if len(payload) > service.settings.max_download_bytes or not payload.startswith(b"\x89PNG\r\n\x1a\n"):
            raise ValidationHarnessError("replacement must be a bounded PNG")
        with tempfile.TemporaryDirectory(prefix="replacement_", dir=service.store.job_dir(job_id) / "input") as temp_name:
            path = Path(temp_name) / "replacement.png"
            path.write_bytes(payload)
            job = service.replace_frame(job_id, candidate_index, frame_index, path)
        return {"schema_version": 1, "ok": True, "data": {"job": _job(job)}}

    @app.get("/v1/jobs/{job_id}/candidates/{candidate_index}/frames/{frame_index}/pixel-edit")
    def get_pixel_edit_session(
        job_id: str,
        candidate_index: int,
        frame_index: int,
    ) -> dict[str, Any]:
        session = service.get_frame_edit_session(job_id, candidate_index, frame_index)
        rgba = session.pop("rgba")
        session["rgba_base64"] = base64.b64encode(rgba).decode("ascii")
        return {"schema_version": 1, "ok": True, "data": {"session": session}}

    @app.post("/v1/jobs/{job_id}/candidates/{candidate_index}/frames/{frame_index}/pixel-edit")
    def save_pixel_edit(
        job_id: str,
        candidate_index: int,
        frame_index: int,
        body: PixelEditBody,
    ) -> dict[str, Any]:
        try:
            rgba = base64.b64decode(body.rgba_base64, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise ValidationHarnessError("invalid pixel edit RGBA base64") from exc
        expected_bytes = body.width * body.height * 4
        if len(rgba) != expected_bytes:
            raise ValidationHarnessError(
                "pixel edit RGBA byte count is invalid",
                details={"actual": len(rgba), "expected": expected_bytes},
            )
        job = service.edit_frame_pixels(
            job_id,
            candidate_index,
            frame_index,
            rgba=rgba,
            width=body.width,
            height=body.height,
            base_sha256=body.base_sha256,
            reviewer=body.reviewer,
        )
        candidate = next(item for item in job.candidates if item.candidate_index == candidate_index)
        frame = next(item for item in candidate.frames if item.index == frame_index)
        return {
            "schema_version": 1,
            "ok": True,
            "data": {
                "job": _job(job),
                "edit": {
                    "frame_index": frame.index,
                    "sha256": frame.sha256,
                    "manual_edit_versions": frame.manual_edit_versions,
                    "review_status": frame.review_status.value,
                },
            },
        }

    @app.post("/v1/jobs/{job_id}/candidates/{candidate_index}/export")
    def export(job_id: str, candidate_index: int, body: ExportOptions) -> dict[str, Any]:
        job = service.export_candidate(job_id, candidate_index, body)
        return {"schema_version": 1, "ok": True, "data": {"job": _job(job)}}

    return app


def run_api(
    *,
    root: str | Path | None = None,
    host: str = "127.0.0.1",
    port: int = 8765,
) -> None:
    try:
        import uvicorn
    except ImportError as exc:  # pragma: no cover - depends on optional install
        raise ProviderConfigurationError(
            "REST API server requires uvicorn; install requirements.txt",
            details={"dependency": "uvicorn"},
        ) from exc
    uvicorn.run(create_api(root), host=host, port=port)
