from __future__ import annotations

import re
import shutil
import threading
import os
import time
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Iterator

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
            atomic_write_json(path, job.model_dump(mode="json"))
            return path

    def load(self, job_id: str) -> JobRecord:
        path = self.job_dir(job_id) / "job.json"
        if not path.is_file():
            raise NotFoundError("job not found", details={"job_id": job_id})
        try:
            return JobRecord.model_validate(read_json(path))
        except (ValidationError, ValueError) as exc:
            raise ValidationHarnessError("job record is invalid", details={"job_id": job_id, "error": str(exc)}) from exc

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

    def list_jobs(self) -> list[dict[str, str]]:
        result: list[dict[str, str]] = []
        if not self.settings.work_dir.exists():
            return result
        for path in sorted(self.settings.work_dir.glob("*/job.json"), reverse=True):
            try:
                job = JobRecord.model_validate(read_json(path))
                result.append({"job_id": job.job_id, "status": job.status.value, "updated_at": job.updated_at.isoformat()})
            except Exception:
                result.append({"job_id": path.parent.name, "status": "invalid", "updated_at": ""})
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
