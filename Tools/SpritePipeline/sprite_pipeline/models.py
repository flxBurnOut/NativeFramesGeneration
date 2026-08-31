from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)


class Anchor(StrictModel):
    x: int = Field(ge=0)
    ground_y: int = Field(ge=0)


class QAThresholds(StrictModel):
    """Per-character QA policy; values live in the preset, not processing code."""

    duplicate_run_length: int = Field(default=3, ge=2, le=16)
    area_change_ratio: float = Field(default=0.35, ge=0, le=5)
    centroid_shift_px: float = Field(default=20.0, ge=0)
    palette_mismatch_ratio: float = Field(default=0.35, ge=0, le=1)
    palette_distance: float = Field(default=48.0, ge=0, le=442)
    loop_difference_ratio: float = Field(default=0.35, ge=0, le=1)
    ground_y_tolerance_px: int = Field(default=4, ge=0)
    rigid_translation_tolerance_px: int = Field(default=0, ge=0, le=16)
    alpha_visible_threshold: int = Field(default=1, ge=1, le=255)


class CharacterPreset(StrictModel):
    schema_version: Literal[1] = 1
    character_id: str
    display_name: str = Field(min_length=1, max_length=200)
    cell_width: int
    cell_height: int
    facing: Literal["left", "right"] = "right"
    reference_frame: str = Field(min_length=1, max_length=260)
    master: str | None = Field(default=None, max_length=260)
    palette: str | None = Field(default=None, max_length=260)
    silhouette: str | None = Field(default=None, max_length=260)
    identity_description: str = Field(default="", max_length=1000)
    anchor: Anchor
    safe_margin: int = Field(default=4, ge=0)
    sheet_columns: int = Field(default=8, ge=1, le=64)
    transparent_background: bool = True
    qa: QAThresholds = Field(default_factory=QAThresholds)

    @field_validator("character_id")
    @classmethod
    def validate_id(cls, value: str) -> str:
        if not value or not all(ch.islower() or ch.isdigit() or ch == "_" for ch in value):
            raise ValueError("character_id must contain only lowercase letters, digits, and underscores")
        return value

    @model_validator(mode="after")
    def validate_cell(self) -> "CharacterPreset":
        if self.cell_width != self.cell_height or self.cell_width not in (64, 128):
            raise ValueError("cell size must be exactly 64x64 or 128x128")
        if self.anchor.x >= self.cell_width or self.anchor.ground_y >= self.cell_height:
            raise ValueError("anchor must be inside the frame")
        if self.safe_margin * 2 >= self.cell_width:
            raise ValueError("safe_margin leaves no usable canvas")
        return self


class ActionPreset(StrictModel):
    schema_version: Literal[1] = 1
    action_id: str
    display_name: str | None = Field(default=None, max_length=200)
    frame_count: int = Field(ge=4, le=16)
    fps: float = Field(default=12, gt=0, le=60)
    loop: bool = False
    grounded: bool = True
    action_description: str = Field(min_length=8, max_length=1000)
    locked_constraints: list[str] = Field(default_factory=list, max_length=32)
    loop_constraint: str | None = Field(default=None, max_length=500)

    @field_validator("action_id")
    @classmethod
    def validate_id(cls, value: str) -> str:
        if not value or not all(ch.islower() or ch.isdigit() or ch == "_" for ch in value):
            raise ValueError("action_id must contain only lowercase letters, digits, and underscores")
        return value

    @field_validator("frame_count")
    @classmethod
    def validate_frame_count(cls, value: int) -> int:
        if value % 2:
            raise ValueError("frame_count must be even")
        return value

    @model_validator(mode="after")
    def validate_loop(self) -> "ActionPreset":
        if self.loop and not self.loop_constraint:
            raise ValueError("looping actions require loop_constraint")
        return self


class GenerationRequest(StrictModel):
    schema_version: Literal[1] = 1
    character_id: str
    action_id: str
    provider: Literal["pixellab", "fixture", "import"] = "pixellab"
    candidate_count: int = Field(default=3, ge=1, le=8)
    seed: int | None = Field(default=None, ge=0, le=2**31 - 1)
    frame_count: int | None = Field(default=None, ge=4, le=16)
    action_description: str | None = Field(default=None, max_length=1000)
    loop: bool | None = None

    @field_validator("frame_count")
    @classmethod
    def validate_frame_count(cls, value: int | None) -> int | None:
        if value is not None and value % 2:
            raise ValueError("frame_count must be even")
        return value


class IssueSeverity(str, Enum):
    hard_failure = "hard_failure"
    warning = "warning"


class QAIssue(StrictModel):
    code: str
    severity: IssueSeverity
    message: str
    frame_index: int | None = None
    metrics: dict[str, Any] = Field(default_factory=dict)


class ReviewStatus(str, Enum):
    pending = "pending"
    approved = "approved"
    repair_requested = "repair_requested"
    rejected = "rejected"


class IssueType(str, Enum):
    identity_drift = "identity_drift"
    clothing_error = "clothing_error"
    weapon_error = "weapon_error"
    limb_error = "limb_error"
    pose_error = "pose_error"
    alpha_background_error = "alpha_background_error"
    scale_baseline_error = "scale_baseline_error"
    other = "other"


class FrameRecord(StrictModel):
    index: int = Field(ge=0)
    raw_path: str
    active_path: str
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    hard_failures: list[QAIssue] = Field(default_factory=list)
    warnings: list[QAIssue] = Field(default_factory=list)
    review_status: ReviewStatus = ReviewStatus.pending
    issue_type: IssueType | None = None
    review_note: str = ""
    reviewed_by: str | None = None
    reviewed_at: datetime | None = None
    repair_attempts: int = Field(default=0, ge=0, le=2)


class CandidateStatus(str, Enum):
    created = "created"
    submitting = "submitting"
    provider_pending = "provider_pending"
    received = "received"
    check_failed = "check_failed"
    review_ready = "review_ready"
    approved = "approved"
    rejected = "rejected"
    failed = "failed"


class CandidateRecord(StrictModel):
    candidate_index: int = Field(ge=1)
    candidate_id: str = Field(pattern=r"^candidate_[0-9]{2}$")
    seed: int | None = None
    status: CandidateStatus = CandidateStatus.created
    provider_name: str | None = None
    provider_model: str | None = None
    diagnostic_only: bool = False
    provider_job_id: str | None = None
    provider_status: str | None = None
    raw_request_path: str | None = None
    raw_response_path: str | None = None
    frames: list[FrameRecord] = Field(default_factory=list)
    hard_failures: list[QAIssue] = Field(default_factory=list)
    warnings: list[QAIssue] = Field(default_factory=list)
    qa_completed_at: datetime | None = None
    qa_input_sha256: str | None = None
    usage: dict[str, Any] = Field(default_factory=dict)
    error: dict[str, Any] | None = None


class JobStatus(str, Enum):
    created = "created"
    provider_pending = "provider_pending"
    review_required = "review_required"
    approved = "approved"
    exported = "exported"
    failed = "failed"


class ExportRecord(StrictModel):
    exported_at: datetime
    candidate_index: int
    sheet_path: str
    preview_path: str
    recipe_path: str
    qa_path: str
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class JobRecord(StrictModel):
    schema_version: Literal[1] = 1
    harness_version: str = "0.1.0"
    revision: int = Field(default=0, ge=0)
    job_id: str
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)
    status: JobStatus = JobStatus.created
    request: GenerationRequest
    character: CharacterPreset
    action: ActionPreset
    character_preset_path: str
    action_preset_path: str
    reference_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    input_sha256: dict[str, str] = Field(default_factory=dict)
    full_prompt: str
    candidates: list[CandidateRecord]
    export: ExportRecord | None = None
    events: list[dict[str, Any]] = Field(default_factory=list)

    def touch(self, event: str | None = None, **data: Any) -> None:
        self.updated_at = utc_now()
        if event:
            self.events.append({"at": self.updated_at.isoformat(), "event": event, **data})

    @model_validator(mode="after")
    def validate_indices(self) -> "JobRecord":
        for filename, digest in self.input_sha256.items():
            if not filename or Path(filename).name != filename:
                raise ValueError("input_sha256 keys must be plain filenames")
            if len(digest) != 64 or any(ch not in "0123456789abcdef" for ch in digest):
                raise ValueError("input_sha256 values must be lowercase SHA-256 digests")
        candidate_indices = [candidate.candidate_index for candidate in self.candidates]
        if candidate_indices != list(range(1, len(self.candidates) + 1)):
            raise ValueError("candidate indices must be unique and contiguous from 1")
        for candidate in self.candidates:
            frame_indices = [frame.index for frame in candidate.frames]
            if frame_indices != list(range(len(frame_indices))):
                raise ValueError(f"{candidate.candidate_id} frame indices must be unique and contiguous from 0")
        return self


class FrameReviewRequest(StrictModel):
    frame_index: int = Field(ge=0)
    status: ReviewStatus
    issue_type: IssueType | None = None
    note: str = Field(default="", max_length=2000)
    reviewer: str = Field(default="operator", min_length=1, max_length=100)

    @model_validator(mode="after")
    def validate_issue(self) -> "FrameReviewRequest":
        if self.status == ReviewStatus.repair_requested and self.issue_type is None:
            raise ValueError("repair_requested requires issue_type")
        return self


class ExportOptions(StrictModel):
    columns: int | None = Field(default=None, ge=1, le=64)
    overwrite: bool = False
    filename: str | None = Field(default=None, min_length=5, max_length=200)

    @field_validator("filename")
    @classmethod
    def validate_filename(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        if cleaned != value:
            raise ValueError("filename cannot begin or end with whitespace")
        if Path(cleaned).name != cleaned or not cleaned.casefold().endswith(".png"):
            raise ValueError("filename must be a plain .png filename")
        if any(ord(character) < 32 or ord(character) == 127 for character in cleaned):
            raise ValueError("filename cannot contain control characters")
        if any(character in '<>:"/\\|?*' for character in cleaned):
            raise ValueError("filename contains characters that are invalid on Windows")
        device_name = cleaned.split(".", 1)[0].casefold()
        reserved_names = {"con", "prn", "aux", "nul"}
        reserved_names.update(f"com{index}" for index in range(1, 10))
        reserved_names.update(f"lpt{index}" for index in range(1, 10))
        if device_name in reserved_names:
            raise ValueError("filename uses a reserved Windows device name")
        return cleaned


class CommandResult(StrictModel):
    schema_version: Literal[1] = 1
    ok: bool = True
    operation: str
    data: dict[str, Any] = Field(default_factory=dict)
