from __future__ import annotations

import re
import shutil
import threading
import os
import time
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Iterator

from pydantic import ValidationError

from .errors import ConflictError, NotFoundError, ValidationHarnessError
from .jsonio import atomic_write_json, inside, read_json, relative_posix
from .models import JobRecord
from .settings import HarnessSettings


_JOB_ID = re.compile(r"^[0-9]{8}_[a-z0-9_]+_[0-9]{3}$")


class JobStore:
    """Atomic JSON job store for the single-machine harness."""

    def __init__(self, settings: HarnessSettings) -> None:
        self.settings = settings
        self._lock = threading.RLock()

    @contextmanager
    def global_lock(self, name: str, *, timeout_seconds: float = 30.0) -> Iterator[None]:
        if not re.fullmatch(r"[a-z0-9_.-]+", name):
            raise ValidationHarnessError("invalid global lock name", details={"name": name})
        lock_path = self.settings.jobs_dir / ".locks" / f"{name}.lock"
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        with self._file_lock(lock_path, timeout_seconds=timeout_seconds, operation=name):
            yield

    @contextmanager
    def creation_lock(self, *, timeout_seconds: float = 30.0) -> Iterator[None]:
        with self.global_lock("job_creation", timeout_seconds=timeout_seconds):
            yield

    @contextmanager
    def submission_lock(self, *, timeout_seconds: float = 180.0) -> Iterator[None]:
        """Serialize every chargeable provider submission across processes."""

        with self.global_lock("chargeable_submission", timeout_seconds=timeout_seconds):
            yield

    @contextmanager
    def _process_lock(self, job_id: str, *, timeout_seconds: float = 30.0) -> Iterator[None]:
        """Use a crash-safe OS byte-range lock to serialize job mutations."""

        lock_path = self.job_dir(job_id) / ".job.lock"
        with self._file_lock(lock_path, timeout_seconds=timeout_seconds, operation="job mutation"):
            yield

    @contextmanager
    def operation_lock(
        self,
        job_id: str,
        operation: str,
        *,
        timeout_seconds: float = 30.0,
    ) -> Iterator[None]:
        """Serialize a named network operation without holding the JSON mutation lock."""

        if not re.fullmatch(r"[a-z0-9_.-]+", operation):
            raise ValidationHarnessError("invalid operation lock name", details={"operation": operation})
        lock_path = self.job_dir(job_id) / f".{operation}.lock"
        with self._file_lock(lock_path, timeout_seconds=timeout_seconds, operation=operation):
            yield

    @contextmanager
    def _file_lock(self, lock_path: Path, *, timeout_seconds: float, operation: str) -> Iterator[None]:
        """Lock one persistent byte; the OS releases it automatically after a crash."""

        descriptor = os.open(str(lock_path), os.O_CREAT | os.O_RDWR)
        handle = os.fdopen(descriptor, "r+b", buffering=0)
        acquired = False
        try:
            if os.fstat(descriptor).st_size == 0:
                os.write(descriptor, b"\0")
            deadline = time.monotonic() + timeout_seconds
            while not acquired:
                try:
                    handle.seek(0)
                    if os.name == "nt":
                        import msvcrt

                        msvcrt.locking(descriptor, msvcrt.LK_NBLCK, 1)
                    else:
                        import fcntl

                        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    acquired = True
                except (OSError, BlockingIOError):
                    if time.monotonic() >= deadline:
                        raise ConflictError(
                            "job is busy in another process",
                            details={"job_id": lock_path.parent.name, "operation": operation},
                        )
                    time.sleep(0.05)
            yield
        finally:
            if acquired:
                try:
                    handle.seek(0)
                    if os.name == "nt":
                        import msvcrt

                        msvcrt.locking(descriptor, msvcrt.LK_UNLCK, 1)
                    else:
                        import fcntl

                        fcntl.flock(descriptor, fcntl.LOCK_UN)
                except OSError:
                    pass
            handle.close()

    def _validate_job_id(self, job_id: str) -> str:
        if not _JOB_ID.fullmatch(job_id):
            raise ValidationHarnessError("invalid job_id", details={"job_id": job_id})
        return job_id

    def job_dir(self, job_id: str) -> Path:
        return inside(self.settings.work_dir, self.settings.work_dir / self._validate_job_id(job_id))

    def create_layout(self, character_id: str, action_id: str) -> tuple[str, Path]:
        base = f"{datetime.now().strftime('%Y%m%d')}_{character_id}_{action_id}"
        with self._lock:
            for number in range(1, 1000):
                job_id = f"{base}_{number:03d}"
                directory = self.settings.work_dir / job_id
                try:
                    directory.mkdir(parents=True, exist_ok=False)
                except FileExistsError:
                    continue
                for name in ("input", "raw", "repaired", "previews", "export", "provider"):
                    (directory / name).mkdir()
                return job_id, directory
        raise ValidationHarnessError("daily job id space exhausted")

    def save(self, job: JobRecord) -> Path:
        with self._lock:
            path = self.job_dir(job.job_id) / "job.json"
            # Each revision is written to an append-only recovery journal before
            # the current pointer. If job.json is ever damaged, the latest valid
            # journal record still contains the complete durable task.
            history = self.job_dir(job.job_id) / "history" / f"job_{job.revision:08d}.json"
            atomic_write_json(history, job.model_dump(mode="json"))
            atomic_write_json(path, job.model_dump(mode="json"))
            return path

    def load(self, job_id: str) -> JobRecord:
        path = self.job_dir(job_id) / "job.json"
        primary_error: Exception | None = None
        primary: JobRecord | None = None
        if path.is_file():
            try:
                primary = JobRecord.model_validate(read_json(path))
                if primary.job_id != job_id:
                    raise ValueError("current job record belongs to a different job")
            except (ValidationError, ValueError, OSError) as exc:
                primary_error = exc
        history_dir = self.job_dir(job_id) / "history"
        latest_history: JobRecord | None = None
        for recovery_path in sorted(history_dir.glob("job_*.json"), reverse=True):
            try:
                recovered = JobRecord.model_validate(read_json(recovery_path))
                filename_revision = int(recovery_path.stem.rsplit("_", 1)[1])
                if recovered.job_id != job_id or recovered.revision != filename_revision:
                    continue
                latest_history = recovered
                break
            except (ValidationError, ValueError, OSError, IndexError):
                continue
        if primary is not None and latest_history is not None:
            # save() publishes the journal before job.json. A crash between
            # those writes leaves a valid but stale current pointer. Selecting
            # the highest durable revision preserves a just-returned provider
            # job ID and prevents an unsafe second POST.
            return latest_history if latest_history.revision > primary.revision else primary
        if primary is not None:
            return primary
        if latest_history is not None:
            return latest_history
        if not path.is_file() and not history_dir.is_dir():
            raise NotFoundError("job not found", details={"job_id": job_id})
        raise ValidationHarnessError(
            "job record and its recovery journal are invalid",
            details={"job_id": job_id, "error": str(primary_error) if primary_error else "no valid revision"},
        )

    def find_by_request_key(self, request_key: str) -> JobRecord | None:
        if not request_key:
            return None
        directories = [
            path
            for path in self.settings.jobs_dir.iterdir()
            if path.is_dir() and _JOB_ID.fullmatch(path.name)
        ]
        for directory in sorted(directories, key=lambda item: item.name, reverse=True):
            try:
                job = self.load(directory.name)
            except Exception:
                continue
            if job.request.request_key == request_key:
                return job
        return None

    def snapshot_file(self, job_id: str, source: Path, filename: str) -> str:
        if not filename or Path(filename).name != filename or filename in {".", ".."}:
            raise ValidationHarnessError("snapshot filename must be a plain filename")
        destination = inside(self.job_dir(job_id) / "input", self.job_dir(job_id) / "input" / filename)
        source_resolved = source.resolve()
        if not source_resolved.is_file():
            raise NotFoundError("snapshot source not found", details={"path": str(source)})
        shutil.copy2(source_resolved, destination)
        return relative_posix(destination, self.job_dir(job_id))

    def resolve_job_path(self, job_id: str, relative: str) -> Path:
        return inside(self.job_dir(job_id), self.job_dir(job_id) / Path(relative))

    def list_jobs(self) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        if not self.settings.work_dir.exists():
            return result
        directories = [
            path
            for path in self.settings.work_dir.iterdir()
            if path.is_dir() and _JOB_ID.fullmatch(path.name)
        ]
        for directory in sorted(directories, key=lambda item: item.name, reverse=True):
            try:
                job = self.load(directory.name)
                result.append(
                    {
                        "job_id": job.job_id,
                        "status": job.status.value,
                        "updated_at": job.updated_at.isoformat(),
                        "created_at": job.created_at.isoformat(),
                        "provider": job.request.provider,
                        "character_id": job.character.character_id,
                        "character_name": job.character.display_name,
                        "action_id": job.action.action_id,
                        "action_name": job.action.display_name or job.action.action_id,
                        "generation_requested": job.generation_requested_at is not None,
                    }
                )
            except Exception:
                result.append({"job_id": directory.name, "status": "invalid", "updated_at": ""})
        return result

    @contextmanager
    def locked_job(self, job_id: str) -> Iterator[JobRecord]:
        """Serialize mutations in this process and persist on successful exit."""

        with self._lock:
            with self._process_lock(job_id):
                job = self.load(job_id)
                yield job
                job.revision += 1
                self.save(job)
