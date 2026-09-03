from __future__ import annotations

import os
import secrets
import shutil
import tempfile
import base64
import binascii
import hashlib
import io
import json
import math
import re
from pathlib import Path
from typing import Any

from PIL import Image

from .errors import (
    ConflictError,
    ExportBlockedError,
    HarnessError,
    NotFoundError,
    ProviderError,
    ProviderTemporaryError,
    ValidationHarnessError,
)
from .jsonio import atomic_write_json, relative_posix, sha256_file
from .models import (
    ActionPreset,
    Anchor,
    CandidateRecord,
    CandidateStatus,
    CharacterPreset,
    ExportOptions,
    ExportRecord,
    FrameRecord,
    FrameReviewRequest,
    GenerationRequest,
    IssueSeverity,
    JobRecord,
    JobStatus,
    QAIssue,
    ReviewStatus,
    utc_now,
)
from .presets import PresetRepository
from .prompts import compose_generation_prompt
from .settings import HarnessSettings
from .store import JobStore


QA_ALGORITHM_VERSION = "sprite-pipeline-qa-v2"


class SpritePipelineService:
    """The only application layer used by CLI, REST API, and Gradio."""

    def __init__(self, root: str | Path | None = None) -> None:
        self.settings = HarnessSettings.load(root)
        self.settings.ensure_directories()
        self.presets = PresetRepository(self.settings)
        self.store = JobStore(self.settings)

    def list_presets(self) -> dict[str, Any]:
        return {
            "characters": self.presets.list_characters(),
            "actions": self.presets.list_actions(),
        }

    def list_jobs(self) -> list[dict[str, str]]:
        return self.store.list_jobs()

    def create_character_preset(
        self,
        *,
        display_name: str,
        reference_image: str | Path,
        facing: str = "right",
        identity_description: str = "",
        character_id: str | None = None,
        sheet_columns: int = 4,
        anchor_x: int | None = None,
        anchor_ground_y: int | None = None,
    ) -> CharacterPreset:
        """Create a minimal reusable character package from one approved idle PNG."""

        name = display_name.strip()
        if not name:
            raise ValidationHarnessError("character display name is required")
        source = Path(reference_image).resolve()
        if not source.is_file():
            raise NotFoundError("character reference image not found", details={"path": str(source)})
        try:
            with Image.open(source) as image:
                image.load()
                if image.format != "PNG":
                    raise ValidationHarnessError("character reference must be a PNG")
                if image.size not in ((64, 64), (128, 128)):
                    raise ValidationHarnessError(
                        "character reference must be exactly 64x64 or 128x128",
                        details={"actual": list(image.size)},
                    )
                if "A" not in image.getbands() and "transparency" not in image.info:
                    raise ValidationHarnessError("character reference must contain an alpha channel")
                alpha_box = image.convert("RGBA").getchannel("A").getbbox()
                if alpha_box is None:
                    raise ValidationHarnessError("character reference cannot be completely transparent")
                width, height = image.size
        except ValidationHarnessError:
            raise
        except Exception as exc:
            raise ValidationHarnessError(
                "character reference cannot be decoded",
                details={"path": str(source), "error": str(exc)},
            ) from exc

        if character_id:
            base_id = character_id.strip().lower()
        else:
            base_id = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_") or "character"
        if not base_id or not all(ch.islower() or ch.isdigit() or ch == "_" for ch in base_id):
            raise ValidationHarnessError(
                "character ID may contain only lowercase letters, digits, and underscores",
                details={"character_id": base_id},
            )
        if base_id == "diagnostic_dummy":
            raise ConflictError("the diagnostic character ID is reserved")

        characters_dir = self.settings.presets_dir / "characters"
        characters_dir.mkdir(parents=True, exist_ok=True)
        selected_id = base_id
        for suffix in range(1, 1000):
            candidate_id = base_id if suffix == 1 else f"{base_id}_{suffix:03d}"
            if not (characters_dir / candidate_id).exists():
                selected_id = candidate_id
                break
        else:
            raise ConflictError("character ID space is exhausted", details={"base_id": base_id})

        if (anchor_x is None) != (anchor_ground_y is None):
            raise ValidationHarnessError("anchor_x and anchor_ground_y must be provided together")
        left, _top, right, bottom = alpha_box
        resolved_anchor_x = (
            max(0, min(width - 1, (left + right - 1) // 2))
            if anchor_x is None
            else anchor_x
        )
        resolved_ground_y = (
            max(0, min(height - 1, bottom - 1))
            if anchor_ground_y is None
            else anchor_ground_y
        )
        if not 0 <= resolved_anchor_x < width or not 0 <= resolved_ground_y < height:
            raise ValidationHarnessError(
                "character anchor must be inside the reference frame",
                details={
                    "anchor": [resolved_anchor_x, resolved_ground_y],
                    "frame_size": [width, height],
                },
            )
        description = identity_description.strip() or (
            "Preserve the exact identity, outfit, proportions, equipment, silhouette, and colors from the approved reference image."
        )
        preset = CharacterPreset(
            character_id=selected_id,
            display_name=name,
            cell_width=width,
            cell_height=height,
            facing=facing,
            reference_frame="idle_reference.png",
            identity_description=description,
            anchor=Anchor(x=resolved_anchor_x, ground_y=resolved_ground_y),
            safe_margin=4,
            sheet_columns=sheet_columns,
            transparent_background=True,
        )

        staging_dir = Path(tempfile.mkdtemp(prefix=f".{selected_id}.", dir=characters_dir))
        destination = characters_dir / selected_id
        try:
            shutil.copy2(source, staging_dir / "idle_reference.png")
            atomic_write_json(staging_dir / "character.json", preset.model_dump(mode="json"))
            os.replace(staging_dir, destination)
        except Exception:
            shutil.rmtree(staging_dir, ignore_errors=True)
            raise
        return preset

    def create_character_preset_from_sheet(
        self,
        *,
        display_name: str,
        sprite_sheet: str | Path,
        cell_size: int = 128,
        reference_frame_index: int = 0,
        facing: str = "right",
        identity_description: str = "",
        character_id: str | None = None,
        sheet_columns: int = 4,
        anchor_x: int | None = None,
        anchor_ground_y: int | None = None,
    ) -> CharacterPreset:
        """Create a reusable character package from one cell of a regular PNG sheet."""

        if cell_size not in (64, 128):
            raise ValidationHarnessError("sheet cell size must be 64 or 128")
        if reference_frame_index < 0:
            raise ValidationHarnessError("reference frame index cannot be negative")
        source = Path(sprite_sheet).resolve()
        if not source.is_file():
            raise NotFoundError("character sprite sheet not found", details={"path": str(source)})
        try:
            with Image.open(source) as image:
                image.load()
                if image.format != "PNG":
                    raise ValidationHarnessError("character sprite sheet must be a PNG")
                if "A" not in image.getbands() and "transparency" not in image.info:
                    raise ValidationHarnessError("character sprite sheet must contain an alpha channel")
                if image.width % cell_size or image.height % cell_size:
                    raise ValidationHarnessError(
                        "sprite sheet dimensions must be exact multiples of the cell size",
                        details={"actual": [image.width, image.height], "cell_size": cell_size},
                    )
                columns = image.width // cell_size
                rows = image.height // cell_size
                if columns != sheet_columns:
                    raise ValidationHarnessError(
                        "sprite sheet column count differs from the requested project grid",
                        details={"actual": columns, "expected": sheet_columns},
                    )
                if reference_frame_index >= columns * rows:
                    raise ValidationHarnessError(
                        "reference frame index is outside the sprite sheet",
                        details={"frame_index": reference_frame_index, "frame_count": columns * rows},
                    )
                left = (reference_frame_index % columns) * cell_size
                top = (reference_frame_index // columns) * cell_size
                reference = image.convert("RGBA").crop((left, top, left + cell_size, top + cell_size))
                if reference.getchannel("A").getbbox() is None:
                    raise ValidationHarnessError("selected reference frame is completely transparent")
        except ValidationHarnessError:
            raise
        except Exception as exc:
            raise ValidationHarnessError(
                "character sprite sheet cannot be decoded",
                details={"path": str(source), "error": str(exc)},
            ) from exc

        with tempfile.TemporaryDirectory(prefix="sprite_reference_") as temp_name:
            reference_path = Path(temp_name) / "reference.png"
            reference.save(reference_path, format="PNG", optimize=False)
            return self.create_character_preset(
                display_name=display_name,
                reference_image=reference_path,
                facing=facing,
                identity_description=identity_description,
                character_id=character_id,
                sheet_columns=sheet_columns,
                anchor_x=anchor_x,
                anchor_ground_y=anchor_ground_y,
            )

    def configure_pixellab_api_key(self, api_key: str | None) -> bool:
        """Persist the PixelLab key without returning or logging its value."""

        key = (api_key or "").strip()
        if key and (len(key) < 8 or any(char.isspace() for char in key)):
            raise ValidationHarnessError("PixelLab API key format is invalid")
        env_path = self.settings.root / ".env"
        lines = env_path.read_text(encoding="utf-8").splitlines() if env_path.is_file() else []
        updated: list[str] = []
        replaced = False
        for line in lines:
            if line.strip().startswith("PIXELLAB_API_KEY="):
                if key:
                    updated.append(f"PIXELLAB_API_KEY={key}")
                replaced = True
            else:
                updated.append(line)
        if key and not replaced:
            if updated and updated[-1].strip():
                updated.append("")
            updated.append(f"PIXELLAB_API_KEY={key}")
        payload = "\n".join(updated).rstrip() + "\n" if updated else ""
        descriptor, temp_name = tempfile.mkstemp(prefix=".env.", suffix=".tmp", dir=self.settings.root)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_name, env_path)
        except Exception:
            try:
                os.unlink(temp_name)
            except FileNotFoundError:
                pass
            raise
        loaded = HarnessSettings.load(self.settings.root)
        object.__setattr__(loaded, "pixellab_api_key", key or None)
        self.settings = loaded
        self.presets.settings = loaded
        self.store.settings = loaded
        return bool(key)

    def get_job(self, job_id: str) -> JobRecord:
        return self.store.load(job_id)

    def create_job(self, request: GenerationRequest | dict[str, Any]) -> JobRecord:
        if not isinstance(request, GenerationRequest):
            request = GenerationRequest.model_validate(request)
        character, character_path = self.presets.load_character(request.character_id)
        base_action, action_path = self.presets.load_action(request.action_id)
        updates: dict[str, Any] = {}
        if request.frame_count is not None:
            updates["frame_count"] = request.frame_count
            if request.frame_count != base_action.frame_count:
                # A caller override describes a custom regular sequence. Do not
                # silently reuse a project-specific provider reduction or sparse
                # sheet layout that was authored for a different frame count.
                updates.update(
                    {
                        "provider_frame_count": None,
                        "provider_frame_selection": [],
                        "sheet_columns": None,
                        "sheet_rows": None,
                        "sheet_frame_cells": [],
                        "critical_frame_indices": [],
                    }
                )
        if request.action_description is not None:
            updates["action_description"] = request.action_description
        if request.loop is not None:
            updates["loop"] = request.loop
            if request.loop and not base_action.loop_constraint:
                updates["loop_constraint"] = "The last frame must transition smoothly back to the unchanged first frame."
            if not request.loop:
                updates["loop_constraint"] = None
        action = ActionPreset.model_validate({**base_action.model_dump(), **updates})
        if request.provider != "import":
            provider_count = action.generation_frame_count
            if provider_count < 4 or provider_count > 16 or provider_count % 2:
                raise ValidationHarnessError(
                    "model generation requires an even source frame count between 4 and 16",
                    details={
                        "project_frame_count": action.frame_count,
                        "provider_frame_count": provider_count,
                        "action_id": action.action_id,
                    },
                )
        full_prompt = compose_generation_prompt(character, action)
        if request.provider == "pixellab" and len(full_prompt) > 1000:
            raise ValidationHarnessError(
                "composed PixelLab action prompt exceeds the 1000 character API limit",
                details={"length": len(full_prompt), "limit": 1000},
            )

        reference_source = (character_path.parent / character.reference_frame).resolve()
        self._validate_reference_image(reference_source, character.cell_width, character.cell_height)
        job_id, job_dir = self.store.create_layout(character.character_id, action.action_id)
        try:
            reference_dest = job_dir / "input" / "reference.png"
            shutil.copy2(reference_source, reference_dest)
            for field, filename in (
                ("master", character.master),
                ("palette", character.palette),
                ("silhouette", character.silhouette),
            ):
                if filename:
                    shutil.copy2(character_path.parent / filename, job_dir / "input" / f"{field}{Path(filename).suffix.lower()}")
            atomic_write_json(job_dir / "input" / "character.json", character.model_dump(mode="json"))
            atomic_write_json(job_dir / "input" / "action.json", action.model_dump(mode="json"))
            input_sha256 = {
                path.name: sha256_file(path)
                for path in sorted((job_dir / "input").iterdir(), key=lambda item: item.name)
                if path.is_file()
            }

            base_seed = request.seed if request.seed is not None else secrets.randbelow(2**31 - request.candidate_count - 1) + 1
            candidates = [
                CandidateRecord(
                    candidate_index=index,
                    candidate_id=f"candidate_{index:02d}",
                    seed=(
                        index - 1
                        if base_seed == 0
                        else ((base_seed - 1 + index - 1) % (2**31 - 1)) + 1
                    ),
                )
                for index in range(1, request.candidate_count + 1)
            ]
            job = JobRecord(
                job_id=job_id,
                request=request,
                character=character,
                action=action,
                character_preset_path=relative_posix(character_path, self.settings.root),
                action_preset_path=relative_posix(action_path, self.settings.root),
                reference_sha256=sha256_file(reference_dest),
                input_sha256=input_sha256,
                full_prompt=full_prompt,
                candidates=candidates,
            )
            job.touch("job_created", provider=request.provider, candidate_count=request.candidate_count)
            self.store.save(job)
            return job
        except Exception:
            shutil.rmtree(job_dir, ignore_errors=True)
            raise

    @staticmethod
    def _validate_reference_image(path: Path, width: int, height: int) -> None:
        try:
            with Image.open(path) as image:
                image.load()
                if image.format != "PNG":
                    raise ValidationHarnessError("reference frame must be PNG", details={"path": str(path)})
                if image.size != (width, height):
                    raise ValidationHarnessError(
                        "reference frame size differs from character preset",
                        details={"path": str(path), "actual": list(image.size), "expected": [width, height]},
                    )
                if "A" not in image.getbands() and "transparency" not in image.info:
                    raise ValidationHarnessError("reference frame has no alpha channel", details={"path": str(path)})
                alpha = image.convert("RGBA").getchannel("A")
                if alpha.getbbox() is None:
                    raise ValidationHarnessError("reference frame is completely transparent", details={"path": str(path)})
        except ValidationHarnessError:
            raise
        except Exception as exc:
            raise ValidationHarnessError("reference frame cannot be decoded", details={"path": str(path), "error": str(exc)}) from exc

    def ingest_candidate(
        self,
        job_id: str,
        candidate_index: int,
        source: str | Path,
        *,
        source_kind: str = "auto",
        columns: int | None = None,
    ) -> JobRecord:
        source_path = Path(source).resolve()
        if not source_path.exists():
            raise NotFoundError("candidate source not found", details={"path": str(source_path)})
        normalized_kind = source_kind.strip().casefold()
        sheet_kind = normalized_kind in {"sheet", "spritesheet", "sprite_sheet"} or (
            normalized_kind == "auto"
            and source_path.is_file()
            and source_path.suffix.casefold() != ".gif"
        )
        with self.store.locked_job(job_id) as job:
            candidate = self._candidate(job, candidate_index)
            if job.request.provider != "import":
                raise ConflictError(
                    "manual candidate ingestion is only allowed for import jobs",
                    details={"provider": job.request.provider},
                )
            if candidate.status != CandidateStatus.created:
                raise ConflictError(
                    "candidate is not in the created state",
                    details={"candidate_index": candidate_index, "status": candidate.status.value},
                )
            output_dir = self.store.job_dir(job_id) / "raw" / candidate.candidate_id
            if output_dir.exists() and any(output_dir.iterdir()):
                raise ConflictError(
                    "candidate raw directory already contains immutable files",
                    details={"candidate_index": candidate_index},
                )
            from .processing import ingest_frames

            raw_root = output_dir.parent
            raw_root.mkdir(parents=True, exist_ok=True)
            if output_dir.exists():
                output_dir.rmdir()
            staging_dir = Path(tempfile.mkdtemp(prefix=f".{candidate.candidate_id}.", dir=raw_root))
            try:
                locked_columns = job.action.sheet_columns if sheet_kind else None
                if locked_columns is not None and columns is not None and columns != locked_columns:
                    raise ValidationHarnessError(
                        "sheet columns differ from the selected action contract",
                        details={"actual": columns, "expected": locked_columns},
                    )
                effective_columns = (
                    locked_columns or columns or job.character.sheet_columns
                ) if sheet_kind else columns
                frame_cells = job.action.frame_cells if sheet_kind and job.action.sheet_columns else []
                if sheet_kind and job.action.sheet_rows is not None:
                    expected_size = (
                        job.character.cell_width * int(effective_columns),
                        job.character.cell_height * job.action.sheet_rows,
                    )
                    with Image.open(source_path) as opened:
                        opened.load()
                        if opened.size != expected_size:
                            raise ValidationHarnessError(
                                "sheet dimensions differ from the selected action contract",
                                details={"actual": list(opened.size), "expected": list(expected_size)},
                            )
                staged_paths = ingest_frames(
                    source_path,
                    staging_dir,
                    job.character.cell_width,
                    job.character.cell_height,
                    len(frame_cells) if frame_cells else None,
                    source_kind=source_kind,
                    columns=effective_columns,
                    frame_cells=frame_cells or None,
                    auto_detect_sheet_count=sheet_kind and not frame_cells,
                )
                staged_records = [
                    (index, path.name, sha256_file(path)) for index, path in enumerate(staged_paths)
                ]
                os.replace(staging_dir, output_dir)
            except Exception:
                if staging_dir.exists():
                    shutil.rmtree(staging_dir, ignore_errors=True)
                raise
            candidate.frames = [
                FrameRecord(
                    index=index,
                    raw_path=relative_posix(output_dir / filename, self.store.job_dir(job_id)),
                    active_path=relative_posix(output_dir / filename, self.store.job_dir(job_id)),
                    sha256=digest,
                )
                for index, filename, digest in staged_records
            ]
            candidate.status = CandidateStatus.received
            candidate.qa_completed_at = None
            candidate.qa_input_sha256 = None
            candidate.error = None
            job.touch(
                "candidate_ingested",
                candidate_index=candidate_index,
                source_kind=source_kind,
                frame_count=len(candidate.frames),
            )
        return self.check_candidate(job_id, candidate_index)

    def ingest_candidate_base64(
        self,
        job_id: str,
        candidate_index: int,
        frames: list[str],
    ) -> JobRecord:
        """Ingest API-friendly base64 PNG frames through the same immutable path."""

        job = self.store.load(job_id)
        if not frames or len(frames) > 16:
            raise ValidationHarnessError("frames must contain between 1 and 16 images")
        total_encoded = sum(len(value) for value in frames if isinstance(value, str))
        max_encoded = ((self.settings.max_download_bytes + 2) // 3) * 4 + 16
        if total_encoded > max_encoded:
            raise ValidationHarnessError(
                "combined base64 frame payload exceeds configured request limit",
                details={"encoded_length": total_encoded, "maximum": max_encoded},
            )
        incoming_root = self.store.job_dir(job_id) / "input"
        with tempfile.TemporaryDirectory(prefix="api_frames_", dir=incoming_root) as temp_name:
            temp_dir = Path(temp_name)
            for index, value in enumerate(frames):
                if not isinstance(value, str):
                    raise ValidationHarnessError("each API frame must be a base64 string", details={"index": index})
                encoded = value.split(",", 1)[1] if value.startswith("data:") and "," in value else value
                if len(encoded) > max_encoded:
                    raise ValidationHarnessError("base64 frame exceeds configured size limit", details={"index": index})
                try:
                    decoded = base64.b64decode(encoded, validate=True)
                except (binascii.Error, ValueError) as exc:
                    raise ValidationHarnessError("invalid base64 frame", details={"index": index}) from exc
                if not decoded.startswith(b"\x89PNG\r\n\x1a\n"):
                    raise ValidationHarnessError("API frame must decode to PNG", details={"index": index})
                (temp_dir / f"frame_{index:03d}.png").write_bytes(decoded)
            return self.ingest_candidate(job.job_id, candidate_index, temp_dir, source_kind="png_dir")

    def generate_job(
        self,
        job_id: str,
        *,
        wait: bool = True,
        candidate_index: int | None = None,
    ) -> JobRecord:
        """Generate candidates serially, or advance one async unit when ``wait`` is false."""

        from .providers import get_provider

        job = self.store.load(job_id)
        if job.request.provider == "import":
            raise ValidationHarnessError("import jobs accept frames through ingest, not generate")
        provider = get_provider(job.request.provider, self.settings)
        if candidate_index is not None:
            targets = [self._candidate(job, candidate_index).candidate_index]
        else:
            targets = [candidate.candidate_index for candidate in job.candidates]

        pending_other = [
            candidate.candidate_index
            for candidate in job.candidates
            if candidate.status in (CandidateStatus.submitting, CandidateStatus.provider_pending)
            and candidate.candidate_index not in targets
        ]
        if pending_other:
            raise ConflictError("another candidate is already pending", details={"candidate_indices": pending_other})

        for index in targets:
            current = self.store.load(job_id)
            candidate = self._candidate(current, index)
            if candidate.status in (
                CandidateStatus.received,
                CandidateStatus.check_failed,
                CandidateStatus.review_ready,
                CandidateStatus.approved,
                CandidateStatus.rejected,
            ):
                continue
            if candidate.status == CandidateStatus.failed:
                continue
            if candidate.status == CandidateStatus.submitting:
                raise ConflictError(
                    "submission outcome is unknown; automatic resubmission is disabled",
                    details={"candidate_index": index},
                )
            if candidate.status == CandidateStatus.created:
                self._submit_candidate(job_id, index, provider)
                current = self.store.load(job_id)
                candidate = self._candidate(current, index)
            if candidate.status != CandidateStatus.provider_pending or not candidate.provider_job_id:
                continue
            should_wait = wait or provider.diagnostic_only
            self._poll_candidate(job_id, index, provider, wait=should_wait)
            advanced = self._candidate(self.store.load(job_id), index)
            if advanced.status == CandidateStatus.provider_pending:
                break
            if not wait:
                break
        return self.store.load(job_id)

    def recover_completed_candidate(
        self,
        job_id: str,
        candidate_index: int,
    ) -> JobRecord:
        """Poll an existing PixelLab job again without submitting a new generation."""

        from .providers import get_provider

        snapshot = self.store.load(job_id)
        if snapshot.request.provider != "pixellab":
            raise ValidationHarnessError(
                "only PixelLab candidates can be recovered from an existing provider job"
            )
        candidate = self._candidate(snapshot, candidate_index)
        if not candidate.provider_job_id:
            raise ConflictError(
                "candidate has no existing provider job to recover",
                details={"candidate_index": candidate_index},
            )
        if candidate.frames:
            raise ConflictError(
                "candidate already contains usable frames",
                details={"candidate_index": candidate_index},
            )
        recoverable_failure = (
            candidate.status == CandidateStatus.failed
            and candidate.provider_status == "completed"
            and (candidate.error or {}).get("code")
            in {"provider_contract_error", "provider_frame_storage_error", "validation_error"}
        )
        if candidate.status != CandidateStatus.provider_pending and not recoverable_failure:
            raise ConflictError(
                "candidate is not a recoverable completed or pending provider job",
                details={
                    "candidate_index": candidate_index,
                    "status": candidate.status.value,
                    "provider_status": candidate.provider_status,
                    "error_code": (candidate.error or {}).get("code"),
                },
            )

        provider = get_provider("pixellab", self.settings)
        provider_job_id = candidate.provider_job_id
        with self.store.locked_job(job_id) as job:
            current = self._candidate(job, candidate_index)
            if current.frames:
                return job
            if current.provider_job_id != provider_job_id:
                raise ConflictError(
                    "candidate provider job changed before recovery",
                    details={"candidate_index": candidate_index},
                )
            current.status = CandidateStatus.provider_pending
            current.error = None
            self._refresh_job_status(job)
            job.touch(
                "candidate_recovery_started",
                candidate_index=candidate_index,
                provider_job_id=provider_job_id,
                submission_created=False,
            )

        # This path deliberately calls only poll/GET. It never invokes
        # provider.submit, so recovering paid output cannot create another job.
        self._poll_candidate(job_id, candidate_index, provider, wait=False)
        return self.store.load(job_id)

    def _submit_candidate(self, job_id: str, candidate_index: int, provider: Any) -> None:
        from .providers import ProviderRequest

        snapshot = self.store.load(job_id)
        snapshot_candidate = self._candidate(snapshot, candidate_index)
        reference_bytes = (self.store.job_dir(job_id) / "input" / "reference.png").read_bytes()
        actual_reference_sha = hashlib.sha256(reference_bytes).hexdigest()
        if actual_reference_sha != snapshot.reference_sha256:
            raise ValidationHarnessError(
                "reference snapshot changed after job creation",
                details={
                    "expected_sha256": snapshot.reference_sha256,
                    "actual_sha256": actual_reference_sha,
                },
            )
        request = ProviderRequest(
            reference_image=reference_bytes,
            prompt=snapshot.full_prompt,
            frame_count=snapshot.action.generation_frame_count,
            seed=snapshot_candidate.seed,
            transparent_background=snapshot.character.transparent_background,
        )
        with self.store.locked_job(job_id) as job:
            candidate = self._candidate(job, candidate_index)
            if candidate.status != CandidateStatus.created:
                raise ConflictError("candidate is not ready for submission", details={"status": candidate.status.value})
            pending_other = [
                item.candidate_index
                for item in job.candidates
                if item.candidate_index != candidate_index
                and item.status in (CandidateStatus.submitting, CandidateStatus.provider_pending)
            ]
            if pending_other:
                raise ConflictError(
                    "another candidate is already pending",
                    details={"candidate_indices": pending_other},
                )
            candidate.status = CandidateStatus.submitting
            candidate.provider_name = provider.name
            candidate.provider_model = "animate-with-text-v3" if provider.name == "pixellab" else "diagnostic-continuity-v2"
            job.status = JobStatus.provider_pending
            job.touch("candidate_submitting", candidate_index=candidate_index, provider=provider.name)
        try:
            submission = provider.submit(request)
        except ProviderError as exc:
            with self.store.locked_job(job_id) as failed_job:
                failed = self._candidate(failed_job, candidate_index)
                submission_unknown = bool(exc.details.get("submission_unknown"))
                failed.status = CandidateStatus.submitting if submission_unknown else CandidateStatus.failed
                failed.error = exc.as_dict()
                self._refresh_job_status(failed_job)
                failed_job.touch(
                    "candidate_submission_unknown" if submission_unknown else "candidate_submission_failed",
                    candidate_index=candidate_index,
                    error=exc.as_dict(),
                )
            raise
        with self.store.locked_job(job_id) as submitted_job:
            submitted = self._candidate(submitted_job, candidate_index)
            provider_dir = self.store.job_dir(job_id) / "provider"
            request_path = provider_dir / f"{submitted.candidate_id}.submit.request.json"
            response_path = provider_dir / f"{submitted.candidate_id}.submit.response.json"
            atomic_write_json(request_path, submission.request_record)
            atomic_write_json(response_path, submission.raw_response)
            submitted.raw_request_path = relative_posix(request_path, self.store.job_dir(job_id))
            submitted.raw_response_path = relative_posix(response_path, self.store.job_dir(job_id))
            submitted.provider_job_id = submission.provider_job_id
            submitted.provider_status = submission.status
            submitted.diagnostic_only = submission.diagnostic_only
            submitted.status = CandidateStatus.provider_pending
            submitted_job.status = JobStatus.provider_pending
            submitted_job.touch(
                "candidate_submitted",
                candidate_index=candidate_index,
                provider_job_id=submission.provider_job_id,
                diagnostic_only=submission.diagnostic_only,
            )

    def _poll_candidate(self, job_id: str, candidate_index: int, provider: Any, *, wait: bool) -> None:
        from .providers import PollStatus

        operation = f"candidate_{candidate_index:02d}.poll"
        with self.store.operation_lock(job_id, operation):
            job = self.store.load(job_id)
            candidate = self._candidate(job, candidate_index)
            if candidate.status != CandidateStatus.provider_pending or not candidate.provider_job_id:
                return
            provider_job_id = candidate.provider_job_id
            candidate_id = candidate.candidate_id
            try:
                result = provider.wait(provider_job_id) if wait else provider.poll(provider_job_id)
            except ProviderTemporaryError as exc:
                updated = False
                with self.store.locked_job(job_id) as pending_job:
                    pending = self._candidate(pending_job, candidate_index)
                    if self._is_current_poll_target(pending, provider_job_id):
                        pending.error = exc.as_dict()
                        pending_job.status = JobStatus.provider_pending
                        pending_job.touch("candidate_poll_deferred", candidate_index=candidate_index, error=exc.as_dict())
                        updated = True
                if wait and updated:
                    raise
                return
            except ProviderError as exc:
                updated = False
                with self.store.locked_job(job_id) as failed_job:
                    failed = self._candidate(failed_job, candidate_index)
                    if self._is_current_poll_target(failed, provider_job_id):
                        failed.error = exc.as_dict()
                        failed.status = CandidateStatus.failed
                        self._refresh_job_status(failed_job)
                        failed_job.touch("candidate_poll_failed", candidate_index=candidate_index, error=exc.as_dict())
                        updated = True
                if updated:
                    raise
                return

            response_path = self.store.job_dir(job_id) / "provider" / f"{candidate_id}.poll.response.json"
            atomic_write_json(response_path, result.raw_response)
            with self.store.locked_job(job_id) as polled_job:
                polled = self._candidate(polled_job, candidate_index)
                if not self._is_current_poll_target(polled, provider_job_id):
                    return
                polled.raw_response_path = relative_posix(response_path, self.store.job_dir(job_id))
                polled.provider_status = result.provider_status
                polled.usage = result.usage
                polled.error = result.error
                if result.status == PollStatus.pending:
                    self._refresh_job_status(polled_job)
                    polled_job.touch("candidate_provider_pending", candidate_index=candidate_index)
                    return
                if result.status == PollStatus.failed:
                    retryable = bool((result.error or {}).get("details", {}).get("retryable"))
                    polled.status = CandidateStatus.provider_pending if retryable else CandidateStatus.failed
                    self._refresh_job_status(polled_job)
                    polled_job.touch(
                        "candidate_provider_wait_incomplete" if retryable else "candidate_provider_failed",
                        candidate_index=candidate_index,
                        error=result.error,
                    )
                    return

            try:
                stored = self._store_provider_frames(
                    job_id,
                    candidate_index,
                    result.images,
                    diagnostic_only=result.diagnostic_only,
                    expected_provider_job_id=provider_job_id,
                )
            except Exception as exc:
                error = (
                    exc.as_dict()
                    if isinstance(exc, HarnessError)
                    else {
                        "code": "provider_frame_storage_error",
                        "message": str(exc),
                        "details": {"type": type(exc).__name__},
                    }
                )
                with self.store.locked_job(job_id) as failed_job:
                    failed = self._candidate(failed_job, candidate_index)
                    if self._is_current_poll_target(failed, provider_job_id):
                        failed.status = CandidateStatus.failed
                        failed.error = error
                        self._refresh_job_status(failed_job)
                        failed_job.touch("provider_frame_storage_failed", candidate_index=candidate_index, error=error)
                raise
            if stored:
                self.check_candidate(job_id, candidate_index)

    @staticmethod
    def _is_current_poll_target(candidate: CandidateRecord, provider_job_id: str) -> bool:
        return (
            candidate.status == CandidateStatus.provider_pending
            and candidate.provider_job_id == provider_job_id
        )

    def _store_provider_frames(
        self,
        job_id: str,
        candidate_index: int,
        images: list[bytes],
        *,
        diagnostic_only: bool,
        expected_provider_job_id: str,
    ) -> bool:
        with self.store.locked_job(job_id) as job:
            candidate = self._candidate(job, candidate_index)
            if not self._is_current_poll_target(candidate, expected_provider_job_id):
                return False
            requested_provider_frame_count = job.action.generation_frame_count
            returned_provider_frame_count = len(images)
            count_matches_preset = returned_provider_frame_count == requested_provider_frame_count
            selection = (
                job.action.generation_frame_selection
                if count_matches_preset
                else list(range(returned_provider_frame_count))
            )
            if count_matches_preset and len(selection) != job.action.frame_count:
                raise ValidationHarnessError(
                    "provider frame selection does not match the project action",
                    details={"selection": selection, "project_frame_count": job.action.frame_count},
                )
            output_dir = self.store.job_dir(job_id) / "raw" / candidate.candidate_id
            raw_root = output_dir.parent
            raw_root.mkdir(parents=True, exist_ok=True)
            staging_dir = Path(tempfile.mkdtemp(prefix=f".{candidate.candidate_id}.", dir=raw_root))
            frames: list[FrameRecord] = []
            manifest_frames: list[dict[str, Any]] = []
            source_manifest_frames: list[dict[str, Any]] = []
            staged_records: list[tuple[int, str, str]] = []
            try:
                source_dir = staging_dir / "provider_source"
                source_dir.mkdir(parents=True, exist_ok=True)
                source_alpha: dict[int, bool] = {}
                for source_index, payload in enumerate(images):
                    path = source_dir / f"source_frame_{source_index:03d}.png"
                    self._atomic_write_bytes(path, payload)
                    with Image.open(path) as opened:
                        opened.load()
                        if opened.format != "PNG":
                            raise ValidationHarnessError(
                                "provider source frame is not PNG",
                                details={"source_index": source_index, "format": opened.format},
                            )
                        has_alpha = "A" in opened.getbands() or "transparency" in opened.info
                    source_alpha[source_index] = has_alpha
                    source_manifest_frames.append(
                        {
                            "source_index": source_index,
                            "output_name": f"provider_source/{path.name}",
                            "source_has_alpha": has_alpha,
                            "sha256": sha256_file(path),
                        }
                    )

                for index, source_index in enumerate(selection):
                    path = staging_dir / f"frame_{index:03d}.png"
                    self._atomic_write_bytes(path, images[source_index])
                    digest = sha256_file(path)
                    staged_records.append((index, path.name, digest))
                    manifest_frames.append(
                        {
                            "index": index,
                            "output_name": path.name,
                            "provider_source_index": source_index,
                            "source_has_alpha": source_alpha[source_index],
                            "sha256": digest,
                        }
                    )
                atomic_write_json(
                    staging_dir / "frames_manifest.json",
                    {
                        "schema_version": 1,
                        "source_kind": "provider",
                        "diagnostic_only": diagnostic_only,
                        "provider_frame_count": returned_provider_frame_count,
                        "requested_provider_frame_count": requested_provider_frame_count,
                        "project_frame_count": len(selection),
                        "expected_project_frame_count": job.action.frame_count,
                        "frame_count_policy": (
                            "preset_selection" if count_matches_preset else "preserve_all_returned"
                        ),
                        "provider_frame_selection": selection,
                        "provider_source_frames": source_manifest_frames,
                        "frames": manifest_frames,
                    },
                )
                if output_dir.exists() and any(output_dir.iterdir()):
                    existing_fingerprints = [
                        (path.relative_to(output_dir).as_posix(), sha256_file(path))
                        for path in sorted(output_dir.rglob("*"))
                        if path.is_file()
                    ]
                    staged_fingerprints = [
                        (path.relative_to(staging_dir).as_posix(), sha256_file(path))
                        for path in sorted(staging_dir.rglob("*"))
                        if path.is_file()
                    ]
                    if existing_fingerprints != staged_fingerprints:
                        raise ConflictError(
                            "provider raw frame directory contains different immutable files",
                            details={"candidate_index": candidate_index},
                        )
                    shutil.rmtree(staging_dir)
                else:
                    if output_dir.exists():
                        output_dir.rmdir()
                    os.replace(staging_dir, output_dir)
            except Exception as exc:
                if staging_dir.exists():
                    shutil.rmtree(staging_dir, ignore_errors=True)
                if isinstance(exc, HarnessError):
                    raise
                raise ValidationHarnessError(
                    "provider frames could not be validated and stored",
                    details={"error": str(exc), "type": type(exc).__name__},
                ) from exc
            for index, filename, digest in staged_records:
                path = output_dir / filename
                relative = relative_posix(path, self.store.job_dir(job_id))
                frames.append(FrameRecord(index=index, raw_path=relative, active_path=relative, sha256=digest))
            candidate.frames = frames
            candidate.diagnostic_only = diagnostic_only
            candidate.status = CandidateStatus.received
            candidate.qa_completed_at = None
            candidate.qa_input_sha256 = None
            candidate.error = None
            job.touch(
                "provider_frames_saved",
                candidate_index=candidate_index,
                frame_count=len(frames),
                provider_frame_count=returned_provider_frame_count,
                requested_provider_frame_count=requested_provider_frame_count,
                provider_frame_selection=selection,
                frame_count_policy=(
                    "preset_selection" if count_matches_preset else "preserve_all_returned"
                ),
                diagnostic_only=diagnostic_only,
            )
            return True

    @staticmethod
    def _atomic_write_bytes(path: Path, payload: bytes) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
        try:
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_name, path)
        except Exception:
            try:
                os.unlink(temp_name)
            except FileNotFoundError:
                pass
            raise

    def check_candidate(self, job_id: str, candidate_index: int) -> JobRecord:
        failure: Exception | None = None
        with self.store.locked_job(job_id) as job:
            candidate = self._candidate(job, candidate_index)
            allowed = {
                CandidateStatus.received,
                CandidateStatus.check_failed,
                CandidateStatus.review_ready,
            }
            if not candidate.frames:
                raise ValidationHarnessError("candidate has no frames", details={"candidate_index": candidate_index})
            if candidate.status not in allowed:
                raise ConflictError(
                    "candidate is not ready for QA",
                    details={"candidate_index": candidate_index, "status": candidate.status.value},
                )
            try:
                self._run_candidate_qa(job_id, job, candidate)
            except Exception as exc:
                failure = exc
                error = (
                    exc.as_dict()
                    if isinstance(exc, HarnessError)
                    else {
                        "code": "qa_execution_error",
                        "message": str(exc),
                        "details": {"type": type(exc).__name__},
                    }
                )
                candidate.status = CandidateStatus.check_failed
                candidate.qa_completed_at = None
                candidate.qa_input_sha256 = None
                candidate.error = error
                self._refresh_job_status(job)
                job.touch("candidate_check_failed", candidate_index=candidate_index, error=error)
        if failure is not None:
            raise failure
        return self.store.load(job_id)

    def _run_candidate_qa(self, job_id: str, job: JobRecord, candidate: CandidateRecord) -> None:
        candidate.qa_completed_at = None
        candidate.qa_input_sha256 = None
        input_digest_before = self._verified_frame_digest(
            job_id,
            job,
            candidate,
            error_class=ValidationHarnessError,
            require_png_contract=False,
            require_expected_indices=False,
        )
        frame_paths = [self.store.resolve_job_path(job_id, frame.active_path) for frame in candidate.frames]
        reference_path = self.store.job_dir(job_id) / "input" / "reference.png"
        palette_candidates = sorted((self.store.job_dir(job_id) / "input").glob("palette.*"))
        palette_path = palette_candidates[0] if palette_candidates else None
        from .processing import build_baseline_grid, build_gif, build_overlay, build_review_grid, build_sprite_sheet, run_qa

        report = run_qa(
            frame_paths,
            self._candidate_expected_frame_count(job, candidate),
            job.character.cell_width,
            job.character.cell_height,
            reference_path=reference_path,
            palette_path=palette_path,
            safe_margin=job.character.safe_margin,
            grounded=job.action.grounded,
            anchor_ground_y=job.character.anchor.ground_y,
            loop=job.action.loop,
            thresholds=self._qa_thresholds(job),
        )
        self._apply_qa_report(candidate, report)
        if job.request.provider != "import" and len(candidate.frames) != job.action.frame_count:
            candidate.warnings.insert(
                0,
                QAIssue(
                    code="provider_frame_count_adjusted",
                    severity=IssueSeverity.warning,
                    message=(
                        f"The provider returned {len(candidate.frames)} usable frames; "
                        f"the action preset expected {job.action.frame_count}. All returned frames were preserved."
                    ),
                    metrics={
                        "expected": job.action.frame_count,
                        "actual": len(candidate.frames),
                        "policy": "preserve_all_returned",
                    },
                ),
            )
        preview_dir = self.store.job_dir(job_id) / "previews"
        prefix = preview_dir / candidate.candidate_id
        sheet_columns, sheet_rows, sheet_cells = self._candidate_sheet_layout(job, candidate)
        preview_builders = (
            (
                "sheet",
                lambda: build_sprite_sheet(
                    frame_paths,
                    prefix.with_suffix(".sheet.png"),
                    sheet_columns,
                    rows=sheet_rows,
                    frame_cells=sheet_cells,
                ),
            ),
            (
                "gif",
                lambda: build_gif(
                    frame_paths,
                    prefix.with_suffix(".preview.gif"),
                    job.action.fps,
                    scale=1,
                    loop=job.action.loop,
                ),
            ),
            (
                "zoom_gif",
                lambda: build_gif(
                    frame_paths,
                    prefix.with_suffix(".zoom.gif"),
                    job.action.fps,
                    scale=4,
                    loop=job.action.loop,
                ),
            ),
            ("grid", lambda: build_review_grid(frame_paths, prefix.with_suffix(".grid.png"), scale=4)),
            (
                "baseline",
                lambda: build_baseline_grid(
                    frame_paths,
                    prefix.with_suffix(".baseline.png"),
                    anchor_x=job.character.anchor.x,
                    ground_y=job.character.anchor.ground_y,
                    scale=4,
                ),
            ),
            ("overlay", lambda: build_overlay(frame_paths, prefix.with_suffix(".overlay.png"), scale=4)),
        )
        for artifact, builder in preview_builders:
            try:
                builder()
            except (OSError, ValueError, SyntaxError) as exc:
                candidate.warnings.append(
                    QAIssue(
                        code="preview_generation_failed",
                        severity=IssueSeverity.warning,
                        message=f"Could not build {artifact} preview: {exc}",
                        metrics={"artifact": artifact, "error_type": type(exc).__name__},
                    )
                )
        input_digest_after = self._verified_frame_digest(
            job_id,
            job,
            candidate,
            error_class=ValidationHarnessError,
            require_png_contract=False,
            require_expected_indices=False,
        )
        if input_digest_after != input_digest_before:
            raise ValidationHarnessError(
                "QA inputs changed while the candidate was being checked",
                details={"before": input_digest_before, "after": input_digest_after},
            )
        candidate.qa_input_sha256 = input_digest_after
        candidate.qa_completed_at = utc_now()
        candidate.error = None
        candidate.status = CandidateStatus.check_failed if candidate.hard_failures else CandidateStatus.review_ready
        self._refresh_job_status(job)
        job.touch(
            "candidate_checked",
            candidate_index=candidate.candidate_index,
            hard_failure_count=len(candidate.hard_failures),
            warning_count=len(candidate.warnings),
        )

    @staticmethod
    def _qa_thresholds(job: JobRecord) -> dict[str, int | float | None]:
        qa = job.character.qa
        return {
            "duplicate_min_run": qa.duplicate_run_length,
            "area_change_ratio": qa.area_change_ratio,
            "centroid_jump_pixels": (
                job.action.centroid_shift_px
                if job.action.centroid_shift_px is not None
                else qa.centroid_shift_px
            ),
            "palette_deviation_ratio": qa.palette_mismatch_ratio,
            "palette_color_distance": qa.palette_distance,
            "loop_difference_ratio": qa.loop_difference_ratio,
            "ground_baseline_tolerance": qa.ground_y_tolerance_px,
            "rigid_translation_tolerance_px": qa.rigid_translation_tolerance_px,
            # Processing treats alpha > threshold as visible.
            "alpha_threshold": max(0, qa.alpha_visible_threshold - 1),
        }

    @staticmethod
    def _issue(raw: dict[str, Any] | str, default_severity: IssueSeverity) -> QAIssue:
        if isinstance(raw, str):
            return QAIssue(code=raw, severity=default_severity, message=raw)
        known = {"code", "message", "frame_index", "severity", "metrics"}
        metrics = dict(raw.get("metrics") or {})
        metrics.update({key: value for key, value in raw.items() if key not in known})
        return QAIssue(
            code=str(raw.get("code", "qa_issue")),
            severity=raw.get("severity", default_severity.value),
            message=str(raw.get("message", raw.get("code", "QA issue"))),
            frame_index=raw.get("frame_index"),
            metrics=metrics,
        )

    def _apply_qa_report(self, candidate: CandidateRecord, report: dict[str, Any]) -> None:
        old_reviews = {frame.index: frame for frame in candidate.frames}
        candidate.hard_failures = [self._issue(item, IssueSeverity.hard_failure) for item in report.get("hard_failures", [])]
        candidate.warnings = [self._issue(item, IssueSeverity.warning) for item in report.get("warnings", [])]
        by_frame = {int(item.get("index", item.get("frame_index", -1))): item for item in report.get("frames", [])}
        for frame in candidate.frames:
            raw = by_frame.get(frame.index, {})
            frame.hard_failures = [
                item
                for item in candidate.hard_failures
                if item.frame_index == frame.index or frame.index in item.metrics.get("frame_indices", [])
            ]
            frame.warnings = [item for item in candidate.warnings if item.frame_index == frame.index]
            previous = old_reviews.get(frame.index)
            if previous and previous.sha256 == frame.sha256:
                frame.review_status = previous.review_status
                frame.issue_type = previous.issue_type
                frame.review_note = previous.review_note
                frame.reviewed_by = previous.reviewed_by
                frame.reviewed_at = previous.reviewed_at
                frame.repair_attempts = previous.repair_attempts
            elif previous:
                frame.repair_attempts = previous.repair_attempts

    def review_frame(self, job_id: str, candidate_index: int, review: FrameReviewRequest | dict[str, Any]) -> JobRecord:
        if not isinstance(review, FrameReviewRequest):
            review = FrameReviewRequest.model_validate(review)
        with self.store.locked_job(job_id) as job:
            candidate = self._candidate(job, candidate_index)
            frame = self._frame(candidate, review.frame_index)
            if review.status in (ReviewStatus.approved, ReviewStatus.repair_requested):
                self._assert_qa_current(job_id, job, candidate)
            if review.status == ReviewStatus.approved:
                if candidate.status != CandidateStatus.review_ready:
                    raise ExportBlockedError(
                        "only a review_ready candidate can approve frames",
                        details={"candidate_status": candidate.status.value},
                    )
                if frame.hard_failures:
                    raise ExportBlockedError("a frame with hard failures cannot be approved", details={"frame_index": frame.index})
            frame.review_status = review.status
            frame.issue_type = review.issue_type
            frame.review_note = review.note
            frame.reviewed_by = review.reviewer
            frame.reviewed_at = utc_now()
            self._refresh_approval(job, candidate)
            job.touch(
                "frame_reviewed",
                candidate_index=candidate_index,
                frame_index=frame.index,
                status=review.status.value,
                issue_type=review.issue_type.value if review.issue_type else None,
                note=review.note,
                reviewer=review.reviewer,
            )
        return self.store.load(job_id)

    def approve_candidate(
        self,
        job_id: str,
        candidate_index: int,
        *,
        reviewer: str,
        acknowledge_warnings: bool = False,
    ) -> JobRecord:
        with self.store.locked_job(job_id) as job:
            candidate = self._candidate(job, candidate_index)
            if candidate.status != CandidateStatus.review_ready:
                raise ExportBlockedError(
                    "only a review_ready candidate can be approved",
                    details={"candidate_index": candidate_index, "status": candidate.status.value},
                )
            self._assert_qa_current(job_id, job, candidate)
            if candidate.hard_failures or any(frame.hard_failures for frame in candidate.frames):
                raise ExportBlockedError("candidate has hard failures", details={"candidate_index": candidate_index})
            unresolved = [
                frame.index
                for frame in candidate.frames
                if frame.review_status in (ReviewStatus.repair_requested, ReviewStatus.rejected)
            ]
            if unresolved:
                raise ExportBlockedError(
                    "candidate contains rejected or repair-requested frames",
                    details={"frame_indices": unresolved},
                )
            # The candidate list is the canonical sequence-wide list and already
            # includes frame-indexed warnings; do not count those twice.
            warning_count = len(candidate.warnings)
            if warning_count and not acknowledge_warnings:
                raise ExportBlockedError(
                    "candidate has warnings; explicit acknowledgement is required",
                    details={"candidate_index": candidate_index, "warning_count": warning_count},
                )
            if not candidate.frames:
                raise ExportBlockedError("candidate has no checked frames")
            now = utc_now()
            for frame in candidate.frames:
                frame.review_status = ReviewStatus.approved
                frame.reviewed_by = reviewer
                frame.reviewed_at = now
                frame.issue_type = None
                frame.review_note = "warnings acknowledged" if warning_count else ""
            candidate.status = CandidateStatus.approved
            self._refresh_job_status(job)
            job.touch("candidate_approved", candidate_index=candidate_index, reviewer=reviewer, warnings_acknowledged=bool(warning_count))
        return self.store.load(job_id)

    def reject_candidate(self, job_id: str, candidate_index: int, *, reviewer: str, note: str = "") -> JobRecord:
        with self.store.locked_job(job_id) as job:
            candidate = self._candidate(job, candidate_index)
            rejectable = {
                CandidateStatus.received,
                CandidateStatus.check_failed,
                CandidateStatus.review_ready,
            }
            if candidate.status not in rejectable:
                raise ConflictError(
                    "candidate can only be rejected after provider receipt and before approval",
                    details={"candidate_index": candidate_index, "status": candidate.status.value},
                )
            candidate.status = CandidateStatus.rejected
            now = utc_now()
            for frame in candidate.frames:
                if frame.review_status == ReviewStatus.pending:
                    frame.review_status = ReviewStatus.rejected
                    frame.reviewed_by = reviewer
                    frame.reviewed_at = now
                    frame.review_note = note
            self._refresh_job_status(job)
            job.touch("candidate_rejected", candidate_index=candidate_index, reviewer=reviewer, note=note)
        return self.store.load(job_id)

    def replace_frame(self, job_id: str, candidate_index: int, frame_index: int, source: str | Path) -> JobRecord:
        source_path = Path(source).resolve()
        if not source_path.is_file():
            raise NotFoundError("replacement frame not found", details={"path": str(source_path)})
        with self.store.locked_job(job_id) as job:
            candidate = self._candidate(job, candidate_index)
            frame = self._frame(candidate, frame_index)
            if frame.repair_attempts >= 2:
                raise ConflictError("frame repair limit reached", details={"frame_index": frame_index, "limit": 2})
            if frame.review_status != ReviewStatus.repair_requested:
                raise ConflictError(
                    "frame must be explicitly marked repair_requested before replacement",
                    details={"frame_index": frame_index, "review_status": frame.review_status.value},
                )
            version = frame.repair_attempts + 1
            destination = (
                self.store.job_dir(job_id)
                / "repaired"
                / candidate.candidate_id
                / f"frame_{frame_index:03d}_v{version}.png"
            )
            destination.parent.mkdir(parents=True, exist_ok=True)
            from .processing import clean_rgba_file

            try:
                with Image.open(source_path) as replacement:
                    replacement.load()
                    if replacement.format != "PNG":
                        raise ValidationHarnessError("replacement frame must be PNG")
                    if "A" not in replacement.getbands() and "transparency" not in replacement.info:
                        raise ValidationHarnessError("replacement frame must retain source alpha")
            except ValidationHarnessError:
                raise
            except Exception as exc:
                raise ValidationHarnessError(
                    "replacement frame cannot be decoded",
                    details={"path": str(source_path), "error": str(exc)},
                ) from exc
            clean_meta = clean_rgba_file(source_path, destination)
            actual_size = (int(clean_meta["width"]), int(clean_meta["height"]))
            expected_size = (job.character.cell_width, job.character.cell_height)
            if actual_size != expected_size:
                destination.unlink(missing_ok=True)
                raise ValidationHarnessError(
                    "replacement frame has the wrong size",
                    details={"actual": list(actual_size), "expected": list(expected_size)},
                )
            frame.active_path = relative_posix(destination, self.store.job_dir(job_id))
            frame.sha256 = sha256_file(destination)
            frame.repair_attempts = version
            frame.review_status = ReviewStatus.pending
            frame.reviewed_by = None
            frame.reviewed_at = None
            frame.review_note = ""
            candidate.status = CandidateStatus.received
            candidate.qa_completed_at = None
            candidate.qa_input_sha256 = None
            job.status = JobStatus.review_required
            job.touch("frame_replaced", candidate_index=candidate_index, frame_index=frame_index, repair_attempt=version)
        return self.check_candidate(job_id, candidate_index)

    def export_candidate(
        self,
        job_id: str,
        candidate_index: int,
        options: ExportOptions | dict[str, Any] | None = None,
    ) -> JobRecord:
        if options is None:
            options = ExportOptions()
        elif not isinstance(options, ExportOptions):
            options = ExportOptions.model_validate(options)
        with self.store.locked_job(job_id) as job:
            candidate = self._candidate(job, candidate_index)
            self._assert_exportable(job_id, job, candidate)
            locked_columns = job.action.sheet_columns
            if locked_columns is not None and options.columns is not None and options.columns != locked_columns:
                raise ConflictError(
                    "export columns are locked by the selected project action",
                    details={"actual": options.columns, "expected": locked_columns},
                )
            columns = locked_columns or options.columns or job.character.sheet_columns
            _layout_columns, rows, frame_cells = self._candidate_sheet_layout(
                job,
                candidate,
                columns=columns,
            )
            export_dir = self.settings.exports_dir / job.character.character_id / job.action.action_id
            export_dir.mkdir(parents=True, exist_ok=True)
            stem = Path(options.filename).stem if options.filename else f"{job.character.character_id}_{job.action.action_id}"
            destinations = {
                "sheet": export_dir / f"{stem}.png",
                "preview": export_dir / f"{stem}.preview.gif",
                "recipe": export_dir / f"{stem}.recipe.json",
                "qa": export_dir / f"{stem}.qa.json",
            }
            existing = [str(path) for path in destinations.values() if path.exists()]
            if existing and not options.overwrite:
                raise ConflictError("export files already exist", details={"paths": existing, "hint": "pass overwrite=true explicitly"})

            staging = self.store.job_dir(job_id) / "export" / candidate.candidate_id
            staging.mkdir(parents=True, exist_ok=True)
            staged_sheet = staging / destinations["sheet"].name
            staged_preview = staging / destinations["preview"].name
            snapshot_dir = staging / ".verified_frames"
            if snapshot_dir.exists():
                shutil.rmtree(snapshot_dir)
            frame_paths = self._snapshot_verified_frames(job_id, job, candidate, snapshot_dir)
            from .processing import build_gif, build_sprite_sheet

            sheet_meta = build_sprite_sheet(
                frame_paths,
                staged_sheet,
                columns,
                rows=rows,
                frame_cells=frame_cells,
            )
            build_gif(frame_paths, staged_preview, job.action.fps, scale=1, loop=job.action.loop)
            recipe = {
                "schema_version": 1,
                "job_id": job.job_id,
                "candidate_index": candidate_index,
                "provider": candidate.provider_name,
                "provider_model": candidate.provider_model,
                "diagnostic_only": candidate.diagnostic_only,
                "character_id": job.character.character_id,
                "action_id": job.action.action_id,
                "manifest_action_name": job.action.manifest_action_name,
                "cell_width": job.character.cell_width,
                "cell_height": job.character.cell_height,
                "columns": columns,
                "rows": sheet_meta["rows"],
                "sheet_width": sheet_meta["sheet_width"],
                "sheet_height": sheet_meta["sheet_height"],
                "frame_count": len(frame_paths),
                "frame_order": [frame.index for frame in candidate.frames],
                "frame_cells": sheet_meta["frame_cells"],
                "unused_cells": sheet_meta["unused_cells"],
                "source_region_px": [
                    [
                        int(column) * job.character.cell_width,
                        int(row) * job.character.cell_height,
                        job.character.cell_width,
                        job.character.cell_height,
                    ]
                    for column, row in sheet_meta["frame_cells"]
                ],
                "fps": job.action.fps,
                "runtime_fps": job.action.fps,
                "scene_fps": job.action.scene_fps or job.action.fps,
                "loop": job.action.loop,
                "critical_frame_indices": job.action.critical_frame_indices,
                "alpha": True,
                "qa_input_sha256": candidate.qa_input_sha256,
                "source_frames": [
                    {"index": frame.index, "path": frame.active_path, "sha256": frame.sha256}
                    for frame in candidate.frames
                ],
                "sheet_sha256": sha256_file(staged_sheet),
            }
            qa_report = {
                "schema_version": 1,
                "job_id": job.job_id,
                "candidate_index": candidate_index,
                "diagnostic_only": candidate.diagnostic_only,
                "qa_completed_at": candidate.qa_completed_at.isoformat() if candidate.qa_completed_at else None,
                "qa_input_sha256": candidate.qa_input_sha256,
                "hard_failures": [item.model_dump(mode="json") for item in candidate.hard_failures],
                "warnings": [item.model_dump(mode="json") for item in candidate.warnings],
                "frames": [
                    {
                        "index": frame.index,
                        "sha256": frame.sha256,
                        "review_status": frame.review_status.value,
                        "reviewed_by": frame.reviewed_by,
                        "reviewed_at": frame.reviewed_at.isoformat() if frame.reviewed_at else None,
                        "repair_attempts": frame.repair_attempts,
                        "hard_failures": [item.model_dump(mode="json") for item in frame.hard_failures],
                        "warnings": [item.model_dump(mode="json") for item in frame.warnings],
                    }
                    for frame in candidate.frames
                ],
            }
            staged_recipe = staging / destinations["recipe"].name
            staged_qa = staging / destinations["qa"].name
            atomic_write_json(staged_recipe, recipe)
            atomic_write_json(staged_qa, qa_report)
            # Recheck the immutable QA sources before publishing. The rendered
            # files above use only the verified snapshots, never live frames.
            self._assert_qa_current(job_id, job, candidate)
            # Recipe is the commit marker and is published last. If any copy
            # fails, restore the previous complete bundle (when present).
            self._publish_export_bundle(
                (
                    (staged_sheet, destinations["sheet"]),
                    (staged_preview, destinations["preview"]),
                    (staged_qa, destinations["qa"]),
                    (staged_recipe, destinations["recipe"]),
                )
            )
            shutil.rmtree(snapshot_dir, ignore_errors=True)
            job.export = ExportRecord(
                exported_at=utc_now(),
                candidate_index=candidate_index,
                sheet_path=relative_posix(destinations["sheet"], self.settings.root),
                preview_path=relative_posix(destinations["preview"], self.settings.root),
                recipe_path=relative_posix(destinations["recipe"], self.settings.root),
                qa_path=relative_posix(destinations["qa"], self.settings.root),
                sha256=sha256_file(destinations["sheet"]),
            )
            job.status = JobStatus.exported
            job.touch("candidate_exported", candidate_index=candidate_index, columns=columns)
        return self.store.load(job_id)

    def _snapshot_verified_frames(
        self,
        job_id: str,
        job: JobRecord,
        candidate: CandidateRecord,
        destination: Path,
    ) -> list[Path]:
        destination.mkdir(parents=False, exist_ok=False)
        snapshots: list[Path] = []
        try:
            for frame in candidate.frames:
                source = self.store.resolve_job_path(job_id, frame.active_path)
                payload = source.read_bytes()
                actual_sha = hashlib.sha256(payload).hexdigest()
                if actual_sha != frame.sha256:
                    raise ExportBlockedError(
                        "candidate frame changed while preparing the export snapshot",
                        details={
                            "frame_index": frame.index,
                            "expected_sha256": frame.sha256,
                            "actual_sha256": actual_sha,
                        },
                    )
                with Image.open(io.BytesIO(payload)) as image:
                    image.load()
                    valid_contract = (
                        image.format == "PNG"
                        and image.size == (job.character.cell_width, job.character.cell_height)
                        and ("A" in image.getbands() or "transparency" in image.info)
                    )
                if not valid_contract:
                    raise ExportBlockedError(
                        "candidate frame does not match the export PNG contract",
                        details={"frame_index": frame.index},
                    )
                snapshot = destination / f"frame_{frame.index:03d}.png"
                self._atomic_write_bytes(snapshot, payload)
                if sha256_file(snapshot) != frame.sha256:
                    raise ExportBlockedError(
                        "verified export snapshot checksum mismatch",
                        details={"frame_index": frame.index},
                    )
                snapshots.append(snapshot)
            return snapshots
        except Exception:
            shutil.rmtree(destination, ignore_errors=True)
            raise

    @staticmethod
    def _atomic_copy(source: Path, destination: Path) -> None:
        descriptor, temp_name = tempfile.mkstemp(prefix=f".{destination.name}.", suffix=".tmp", dir=destination.parent)
        os.close(descriptor)
        try:
            shutil.copyfile(source, temp_name)
            os.replace(temp_name, destination)
        except Exception:
            try:
                os.unlink(temp_name)
            except FileNotFoundError:
                pass
            raise

    def _publish_export_bundle(self, files: tuple[tuple[Path, Path], ...]) -> None:
        parent = files[0][1].parent
        backup_dir = Path(tempfile.mkdtemp(prefix=".export_backup.", dir=parent))
        backups: dict[Path, Path] = {}
        try:
            for _source, destination in files:
                if destination.is_file():
                    backup = backup_dir / destination.name
                    shutil.copyfile(destination, backup)
                    backups[destination] = backup
            try:
                for source, destination in files:
                    self._atomic_copy(source, destination)
            except Exception:
                for _source, destination in files:
                    backup = backups.get(destination)
                    if backup and backup.is_file():
                        self._atomic_copy(backup, destination)
                    elif destination.exists():
                        destination.unlink()
                raise
        finally:
            shutil.rmtree(backup_dir, ignore_errors=True)

    @staticmethod
    def _candidate(job: JobRecord, candidate_index: int) -> CandidateRecord:
        for candidate in job.candidates:
            if candidate.candidate_index == candidate_index:
                return candidate
        raise NotFoundError("candidate not found", details={"candidate_index": candidate_index})

    @staticmethod
    def _candidate_expected_frame_count(job: JobRecord, candidate: CandidateRecord) -> int:
        """Check the usable sequence that was actually received."""

        return len(candidate.frames)

    @staticmethod
    def _candidate_sheet_layout(
        job: JobRecord,
        candidate: CandidateRecord,
        *,
        columns: int | None = None,
    ) -> tuple[int, int | None, list[tuple[int, int]] | None]:
        """Keep the project grid when possible and pad variable results safely."""

        columns = columns or job.action.sheet_columns or job.character.sheet_columns
        if len(candidate.frames) == job.action.frame_count:
            return columns, job.action.sheet_rows, job.action.frame_cells or None

        required_rows = math.ceil(len(candidate.frames) / columns)
        rows = max(job.action.sheet_rows or 0, required_rows)
        return columns, rows, None

    @staticmethod
    def _frame(candidate: CandidateRecord, frame_index: int) -> FrameRecord:
        for frame in candidate.frames:
            if frame.index == frame_index:
                return frame
        raise NotFoundError("frame not found", details={"frame_index": frame_index})

    def _verified_frame_digest(
        self,
        job_id: str,
        job: JobRecord,
        candidate: CandidateRecord,
        *,
        error_class: type[HarnessError],
        require_png_contract: bool = True,
        require_expected_indices: bool = True,
    ) -> str:
        expected_frame_count = self._candidate_expected_frame_count(job, candidate)
        expected_indices = list(range(expected_frame_count))
        actual_indices = [frame.index for frame in candidate.frames]
        if require_expected_indices and actual_indices != expected_indices:
            raise error_class(
                "candidate frame order/count is not valid",
                details={"actual_indices": actual_indices, "expected_indices": expected_indices},
            )
        policy = {
            "qa_algorithm_version": QA_ALGORITHM_VERSION,
            "frame_count": expected_frame_count,
            "cell_width": job.character.cell_width,
            "cell_height": job.character.cell_height,
            "safe_margin": job.character.safe_margin,
            "anchor_ground_y": job.character.anchor.ground_y,
            "loop": job.action.loop,
            "grounded": job.action.grounded,
            "qa": job.character.qa.model_dump(mode="json"),
        }
        digest = hashlib.sha256(json.dumps(policy, sort_keys=True, separators=(",", ":")).encode("utf-8"))
        input_dir = self.store.job_dir(job_id) / "input"
        expected_inputs = dict(job.input_sha256)
        if "reference.png" in expected_inputs and expected_inputs["reference.png"] != job.reference_sha256:
            raise error_class("job reference checksums disagree")
        expected_inputs["reference.png"] = job.reference_sha256
        if job.input_sha256:
            actual_names = {path.name for path in input_dir.iterdir() if path.is_file()}
            expected_names = set(expected_inputs)
            if actual_names != expected_names:
                raise error_class(
                    "job input snapshot files changed after creation",
                    details={
                        "missing": sorted(expected_names - actual_names),
                        "unexpected": sorted(actual_names - expected_names),
                    },
                )
        else:
            for palette_path in sorted(input_dir.glob("palette.*"), key=lambda item: item.name):
                if palette_path.is_file():
                    expected_inputs[palette_path.name] = sha256_file(palette_path)
        for filename, expected_sha in sorted(expected_inputs.items()):
            path = input_dir / filename
            try:
                actual_sha = sha256_file(path)
            except Exception as exc:
                raise error_class(
                    "job QA input cannot be verified",
                    details={"filename": filename, "error": str(exc)},
                ) from exc
            if actual_sha != expected_sha:
                raise error_class(
                    "job QA input changed after creation",
                    details={"filename": filename, "expected_sha256": expected_sha, "actual_sha256": actual_sha},
                )
            digest.update(f"\ninput:{filename}:{actual_sha}".encode("utf-8"))

        manifest_paths: set[Path] = set()
        for frame in candidate.frames:
            try:
                path = self.store.resolve_job_path(job_id, frame.active_path)
                actual_sha = sha256_file(path)
                with Image.open(path) as image:
                    image.load()
                    image_format = image.format
                    image_size = image.size
                    has_alpha = "A" in image.getbands() or "transparency" in image.info
            except Exception as exc:
                raise error_class(
                    "candidate frame cannot be verified",
                    details={"frame_index": frame.index, "path": frame.active_path, "error": str(exc)},
                ) from exc
            if actual_sha != frame.sha256:
                raise error_class(
                    "candidate frame bytes changed after ingestion or repair",
                    details={"frame_index": frame.index, "expected_sha256": frame.sha256, "actual_sha256": actual_sha},
                )
            if require_png_contract and (
                image_format != "PNG"
                or image_size != (job.character.cell_width, job.character.cell_height)
                or not has_alpha
            ):
                raise error_class(
                    "candidate frame no longer matches the approved PNG contract",
                    details={
                        "frame_index": frame.index,
                        "format": image_format,
                        "size": list(image_size),
                        "has_alpha": has_alpha,
                    },
                )
            digest.update(f"\nframe:{frame.index}:{frame.active_path}:{actual_sha}".encode("utf-8"))
            manifest_paths.add(path.parent / "frames_manifest.json")
        for manifest_path in sorted(manifest_paths, key=lambda item: str(item)):
            relative_manifest = relative_posix(manifest_path, self.store.job_dir(job_id))
            manifest_sha = sha256_file(manifest_path) if manifest_path.is_file() else "missing"
            digest.update(f"\nmanifest:{relative_manifest}:{manifest_sha}".encode("utf-8"))
        return digest.hexdigest()

    def _assert_qa_current(self, job_id: str, job: JobRecord, candidate: CandidateRecord) -> None:
        if candidate.qa_completed_at is None or not candidate.qa_input_sha256:
            raise ExportBlockedError("candidate has no completed QA record")
        current_digest = self._verified_frame_digest(
            job_id,
            job,
            candidate,
            error_class=ExportBlockedError,
        )
        if current_digest != candidate.qa_input_sha256:
            raise ExportBlockedError(
                "candidate QA inputs changed after the last successful check",
                details={"expected_digest": candidate.qa_input_sha256, "actual_digest": current_digest},
            )

    def _assert_exportable(self, job_id: str, job: JobRecord, candidate: CandidateRecord) -> None:
        if candidate.status != CandidateStatus.approved:
            raise ExportBlockedError("candidate is not approved", details={"status": candidate.status.value})
        self._assert_qa_current(job_id, job, candidate)
        if candidate.hard_failures or not candidate.frames:
            raise ExportBlockedError("candidate has hard failures or no frames")
        unapproved = [frame.index for frame in candidate.frames if frame.review_status != ReviewStatus.approved]
        if unapproved:
            raise ExportBlockedError("all frames must be approved", details={"unapproved_frames": unapproved})

    def _refresh_approval(self, job: JobRecord, candidate: CandidateRecord) -> None:
        if candidate.frames and not candidate.hard_failures and not candidate.warnings and all(
            frame.review_status == ReviewStatus.approved and not frame.hard_failures for frame in candidate.frames
        ):
            candidate.status = CandidateStatus.approved
            self._refresh_job_status(job)
        elif any(frame.review_status == ReviewStatus.rejected for frame in candidate.frames):
            candidate.status = CandidateStatus.rejected
            self._refresh_job_status(job)
        elif candidate.hard_failures:
            candidate.status = CandidateStatus.check_failed
            self._refresh_job_status(job)
        else:
            candidate.status = CandidateStatus.review_ready
            self._refresh_job_status(job)

    @staticmethod
    def _refresh_job_status(job: JobRecord) -> None:
        statuses = {candidate.status for candidate in job.candidates}
        if job.export is not None:
            job.status = JobStatus.exported
        elif CandidateStatus.approved in statuses:
            job.status = JobStatus.approved
        elif statuses & {CandidateStatus.submitting, CandidateStatus.provider_pending}:
            job.status = JobStatus.provider_pending
        elif all(candidate.status in (CandidateStatus.rejected, CandidateStatus.failed) for candidate in job.candidates):
            job.status = JobStatus.failed
        elif statuses & {
            CandidateStatus.received,
            CandidateStatus.check_failed,
            CandidateStatus.review_ready,
            CandidateStatus.rejected,
        }:
            job.status = JobStatus.review_required
        elif CandidateStatus.created in statuses:
            job.status = JobStatus.created
        else:
            job.status = JobStatus.review_required
