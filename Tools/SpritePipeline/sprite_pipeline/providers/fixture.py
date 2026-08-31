"""Deterministic offline fixture provider for harness diagnostics.

The fixture provider never calls a model or network service.  Because its
bundled action is idle, it keeps the validated reference at one canvas position
and varies only a few existing interior colour pixels to simulate a tiny
status-light pulse.  This is an idle-demo choice, not a universal fixed-centre
rule.  Its output is intentionally marked
``diagnostic_only`` everywhere: it verifies orchestration, storage, QA, review,
and export plumbing, but it is not a generated production animation.
"""

from __future__ import annotations

import hashlib
import io
import threading
from dataclasses import dataclass
from typing import Any, Callable

from PIL import Image

from sprite_pipeline.errors import ProviderPermanentError

from .base import (
    DEFAULT_MAX_IMAGE_BYTES,
    ImagePayloadError,
    PollResult,
    PollStatus,
    ProviderRequest,
    SpriteProvider,
    Submission,
    normalize_image_bytes,
)


@dataclass(frozen=True, slots=True)
class _FixtureJob:
    """Normalized immutable input retained until the diagnostic job is polled."""

    reference_png: bytes
    width: int
    height: int
    frame_count: int
    seed: int
    transparent_background: bool
    reference_sha256: str


class FixtureProvider(SpriteProvider):
    """Offline provider that returns deterministic stable-position idle frames.

    The provider is suitable for CI, demonstrations, and Codex-driven smoke
    tests without a PixelLab token.  It must never be represented as an AI
    generation result; both :class:`Submission` and :class:`PollResult` carry
    ``diagnostic_only=True``.
    """

    name = "fixture"
    diagnostic_only = True

    def __init__(
        self,
        *,
        poll_interval_seconds: float = 0.01,
        max_wait_seconds: float = 5.0,
        max_image_bytes: int = DEFAULT_MAX_IMAGE_BYTES,
        sleep_fn: Callable[[float], None] | None = None,
        monotonic_fn: Callable[[], float] | None = None,
    ) -> None:
        """Configure image bounds and initialize the in-memory diagnostic jobs."""

        super_kwargs: dict[str, Any] = {
            "poll_interval_seconds": poll_interval_seconds,
            "max_wait_seconds": max_wait_seconds,
        }
        if sleep_fn is not None:
            super_kwargs["sleep_fn"] = sleep_fn
        if monotonic_fn is not None:
            super_kwargs["monotonic_fn"] = monotonic_fn
        super().__init__(**super_kwargs)
        if max_image_bytes <= 0:
            raise ValueError("max_image_bytes must be positive")
        self.max_image_bytes = int(max_image_bytes)
        self._jobs: dict[str, _FixtureJob] = {}
        self._lock = threading.RLock()

    def submit(self, request: ProviderRequest) -> Submission:
        """Register a deterministic local job and return its redacted receipt."""

        try:
            reference = normalize_image_bytes(
                request.reference_image,
                max_bytes=self.max_image_bytes,
                max_width=256,
                max_height=256,
                max_pixels=256 * 256,
            )
        except ImagePayloadError as exc:
            raise ProviderPermanentError(
                "fixture reference image is not a valid PNG/JPEG",
                details={"reason": str(exc), "diagnostic_only": True},
            ) from exc

        effective_seed = request.seed if request.seed is not None else 0
        fingerprint = hashlib.sha256()
        fingerprint.update(reference.data)
        fingerprint.update(request.prompt.encode("utf-8"))
        fingerprint.update(str(request.frame_count).encode("ascii"))
        fingerprint.update(str(effective_seed).encode("ascii"))
        fingerprint.update(b"1" if request.transparent_background else b"0")
        job_id = f"fixture-{fingerprint.hexdigest()[:24]}"

        job = _FixtureJob(
            reference_png=reference.data,
            width=reference.width,
            height=reference.height,
            frame_count=request.frame_count,
            seed=effective_seed,
            transparent_background=request.transparent_background,
            reference_sha256=reference.sha256,
        )
        with self._lock:
            self._jobs[job_id] = job

        request_record = {
            "provider": self.name,
            "operation": "deterministic_idle_continuity_pulse",
            "diagnostic_only": True,
            "reference_frame": {
                "format": "png",
                "width": reference.width,
                "height": reference.height,
                "byte_length": len(reference.data),
                "sha256": reference.sha256,
            },
            "prompt": request.prompt,
            "frame_count": request.frame_count,
            "seed": effective_seed,
            "transparent_background": request.transparent_background,
        }
        raw_response = {
            "provider_job_id": job_id,
            "status": "completed",
            "diagnostic_only": True,
            "note": "idle fixture frames hold position and pulse interior pixels; other actions may move continuously",
        }
        return Submission(
            provider=self.name,
            provider_job_id=job_id,
            status="completed",
            expected_frame_count=request.frame_count,
            expected_size=(reference.width, reference.height),
            request_record=request_record,
            raw_response=raw_response,
            diagnostic_only=True,
        )

    def poll(self, provider_job_id: str) -> PollResult:
        """Render and return the registered diagnostic job immediately."""

        if not isinstance(provider_job_id, str) or not provider_job_id.strip():
            raise ProviderPermanentError(
                "fixture provider_job_id must be a non-empty string",
                details={"diagnostic_only": True},
            )
        job_id = provider_job_id.strip()
        with self._lock:
            job = self._jobs.get(job_id)
        if job is None:
            raise ProviderPermanentError(
                "fixture job was not found in this provider process",
                details={
                    "provider_job_id": job_id,
                    "diagnostic_only": True,
                    "hint": "fixture jobs are intentionally in-memory and must be polled by the submitting process",
                },
            )

        images, offsets = self._render_frames(job)
        raw_response = {
            "provider_job_id": job_id,
            "status": "completed",
            "frame_count": len(images),
            "frame_size": {"width": job.width, "height": job.height},
            "offsets": [{"x": x, "y": y} for x, y in offsets],
            "diagnostic_only": True,
            "reference_sha256": job.reference_sha256,
            "note": "idle fixture frames hold position and pulse interior pixels; other actions may move continuously",
        }
        return PollResult(
            provider=self.name,
            provider_job_id=job_id,
            status=PollStatus.completed,
            provider_status="completed",
            images=images,
            raw_response=raw_response,
            usage={"type": "diagnostic", "units": 0},
            diagnostic_only=True,
        )

    def _render_frames(self, job: _FixtureJob) -> tuple[list[bytes], list[tuple[int, int]]]:
        """Keep the source fixed and pulse interior pixels without moving alpha."""

        with Image.open(io.BytesIO(job.reference_png)) as opened:
            opened.load()
            reference = opened.convert("RGBA")

        alpha = reference.getchannel("A")
        bounds = alpha.getbbox()
        if bounds is None:
            raise ProviderPermanentError(
                "fixture reference image is completely transparent",
                details={"diagnostic_only": True},
            )
        center_x = (bounds[0] + bounds[2] - 1) / 2
        center_y = (bounds[1] + bounds[3] - 1) / 2
        visible = [
            (x, y)
            for y in range(bounds[1], bounds[3])
            for x in range(bounds[0], bounds[2])
            if alpha.getpixel((x, y)) > 0
        ]
        pulse_pixels = sorted(
            visible,
            key=lambda point: (
                (point[0] - center_x) ** 2 + (point[1] - center_y) ** 2,
                point[1],
                point[0],
            ),
        )[:6]
        offsets = [(0, 0) for _index in range(job.frame_count)]

        frames: list[bytes] = []
        for index, (_dx, _dy) in enumerate(offsets):
            canvas = reference.copy()
            pulse = 0 if index == 0 else ((index + job.seed) % 15) + 1
            if pulse:
                for x, y in pulse_pixels:
                    red, green, blue, alpha_value = canvas.getpixel((x, y))
                    canvas.putpixel((x, y), (red ^ pulse, green ^ pulse, blue ^ pulse, alpha_value))
            buffer = io.BytesIO()
            canvas.save(buffer, format="PNG", optimize=False, compress_level=9)
            normalized = normalize_image_bytes(
                buffer.getvalue(),
                max_bytes=self.max_image_bytes,
                max_width=256,
                max_height=256,
                max_pixels=256 * 256,
            )
            frames.append(normalized.data)
        return frames, offsets
