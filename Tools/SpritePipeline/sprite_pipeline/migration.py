from __future__ import annotations

import hashlib
import os
import re
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .credential_store import CredentialStore
from .jsonio import atomic_write_json, read_json, sha256_file
from .settings import HarnessSettings, _read_dotenv


def _utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _tree_fingerprints(root: Path) -> list[tuple[str, str]]:
    if not root.is_dir():
        return []
    return [
        (path.relative_to(root).as_posix(), sha256_file(path))
        for path in sorted(root.rglob("*"), key=lambda item: item.as_posix())
        if path.is_file() and not path.name.endswith(".lock")
    ]


def _job_tree_fingerprints(root: Path) -> list[tuple[str, str]]:
    """Fingerprint canonical job data while ignoring rebuildable catalog data."""
    return [
        (relative, digest)
        for relative, digest in _tree_fingerprints(root)
        if relative != "summary.json"
    ]


def _atomic_copy(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temp_name = tempfile.mkstemp(
        prefix=f".{destination.name}.",
        suffix=".migration.tmp",
        dir=destination.parent,
    )
    os.close(descriptor)
    try:
        shutil.copy2(source, temp_name)
        if sha256_file(source) != sha256_file(Path(temp_name)):
            raise OSError("migration copy checksum mismatch")
        os.replace(temp_name, destination)
    except Exception:
        try:
            os.unlink(temp_name)
        except FileNotFoundError:
            pass
        raise


class LegacyLayoutMigrator:
    """Copy legacy code-adjacent user data into the separated user layout.

    Source jobs, exports, and character packages are never moved, renamed,
    truncated, or deleted. Every copied file is checksum-verified before it
    becomes visible at its destination. Conflicting destinations are preserved
    under recovery/migration_conflicts. The sole source-side change is removal
    of a legacy plaintext API key after its protected copy is decrypted and
    verified byte-for-byte.
    """

    def __init__(self, settings: HarnessSettings) -> None:
        self.settings = settings
        self.report_path = settings.config_dir / "migration_report.json"

    def run(self) -> dict[str, Any]:
        report: dict[str, Any] = {
            "schema_version": 1,
            "checked_at": datetime.now(timezone.utc).isoformat(),
            "status": "not_required",
            "source_root": str(self.settings.legacy_root) if self.settings.legacy_root else None,
            "destination_root": str(self.settings.data_root),
            "source_left_intact": True,
            "copied_jobs": 0,
            "copied_exports": 0,
            "copied_characters": 0,
            "skipped_recreatable_diagnostic_jobs": [],
            "skipped_identical": 0,
            "skipped_destination_newer": 0,
            "conflicts": [],
            "errors": [],
            "legacy_secret_still_present": False,
            "legacy_plaintext_secret_removed": False,
            "credential_migrated": False,
        }
        if self.settings.portable_mode or self.settings.legacy_root is None:
            report["status"] = "portable_mode" if self.settings.portable_mode else "not_required"
            atomic_write_json(self.report_path, report)
            return report

        legacy = self.settings.legacy_root
        assert legacy is not None
        report["status"] = "complete"
        try:
            self._migrate_jobs(legacy / "work", report)
        except Exception as exc:
            report["errors"].append({"area": "jobs", "message": str(exc), "type": type(exc).__name__})
        try:
            self._migrate_exports(legacy / "exports", report)
        except Exception as exc:
            report["errors"].append({"area": "exports", "message": str(exc), "type": type(exc).__name__})
        try:
            self._migrate_characters(legacy / "presets" / "characters", report)
        except Exception as exc:
            report["errors"].append({"area": "characters", "message": str(exc), "type": type(exc).__name__})
        try:
            self._migrate_environment(legacy / ".env", report)
        except Exception as exc:
            report["errors"].append({"area": "credentials", "message": str(exc), "type": type(exc).__name__})
        if report["errors"]:
            report["status"] = "incomplete"
        elif report["conflicts"]:
            report["status"] = "complete_with_conflicts"
        atomic_write_json(self.report_path, report)
        return report

    def _migrate_jobs(self, source_root: Path, report: dict[str, Any]) -> None:
        if not source_root.is_dir():
            return
        for source in sorted(source_root.iterdir(), key=lambda item: item.name):
            if not source.is_dir() or (
                not (source / "job.json").is_file()
                and not (source / "history").is_dir()
            ):
                continue
            try:
                outcome = self._copy_directory(source, self.settings.jobs_dir / source.name, "jobs", report)
                if outcome == "copied":
                    report["copied_jobs"] += 1
            except Exception as exc:
                if self._is_recreatable_diagnostic_job(source):
                    report["skipped_recreatable_diagnostic_jobs"].append(
                        {
                            "source": str(source),
                            "reason": (
                                "bundled offline diagnostic output was inaccessible; "
                                "it is not user game art and can be recreated without API usage"
                            ),
                            "source_left_intact": True,
                        }
                    )
                    continue
                report["errors"].append(
                    {
                        "area": "job",
                        "source": str(source),
                        "message": str(exc),
                        "type": type(exc).__name__,
                    }
                )

    @staticmethod
    def _is_recreatable_diagnostic_job(source: Path) -> bool:
        """Return true only for explicitly marked, free offline fixture jobs."""

        job_path = source / "job.json"
        if not job_path.is_file():
            return False
        try:
            payload = read_json(job_path)
            request = payload.get("request") if isinstance(payload, dict) else None
            candidates = payload.get("candidates") if isinstance(payload, dict) else None
            return (
                isinstance(request, dict)
                and request.get("provider") == "fixture"
                and isinstance(candidates, list)
                and bool(candidates)
                and all(
                    isinstance(candidate, dict)
                    and candidate.get("diagnostic_only") is True
                    for candidate in candidates
                )
            )
        except Exception:
            return False

    def _migrate_exports(self, source_root: Path, report: dict[str, Any]) -> None:
        if not source_root.is_dir():
            return
        for source in sorted(source_root.rglob("*"), key=lambda item: item.as_posix()):
            if not source.is_file():
                continue
            try:
                relative = source.relative_to(source_root)
                destination = self.settings.exports_dir / relative
                if destination.is_file():
                    if sha256_file(source) == sha256_file(destination):
                        report["skipped_identical"] += 1
                        continue
                    self._preserve_conflict(source, "exports", relative, report)
                    continue
                _atomic_copy(source, destination)
                report["copied_exports"] += 1
            except Exception as exc:
                report["errors"].append(
                    {
                        "area": "export",
                        "source": str(source),
                        "message": str(exc),
                        "type": type(exc).__name__,
                    }
                )

    def _migrate_characters(self, source_root: Path, report: dict[str, Any]) -> None:
        if not source_root.is_dir():
            return
        bundled_ids = self._bundled_character_ids()
        for source in sorted(source_root.iterdir(), key=lambda item: item.name):
            if (
                not source.is_dir()
                or source.name.startswith("_")
                or source.name in bundled_ids
                or not (source / "character.json").is_file()
            ):
                continue
            try:
                outcome = self._copy_directory(
                    source,
                    self.settings.user_characters_dir / source.name,
                    "characters",
                    report,
                )
                if outcome == "copied":
                    report["copied_characters"] += 1
            except Exception as exc:
                report["errors"].append(
                    {
                        "area": "character",
                        "source": str(source),
                        "message": str(exc),
                        "type": type(exc).__name__,
                    }
                )

    def _migrate_environment(self, source: Path, report: dict[str, Any]) -> None:
        if not source.is_file():
            return
        values = _read_dotenv(source)
        key = values.pop("PIXELLAB_API_KEY", "").strip()
        if key:
            store = CredentialStore(self.settings.config_dir)
            existing = store.get("pixellab_api_key")
            if existing is None:
                store.set("pixellab_api_key", key)
                if store.get("pixellab_api_key") != key:
                    raise OSError("protected credential verification failed")
                report["credential_migrated"] = True
            elif existing != key:
                report["conflicts"].append(
                    {
                        "area": "credentials",
                        "source": str(source),
                        "destination": str(store.path),
                        "reason": "a different protected credential already exists; it was preserved",
                    }
                )
            if store.get("pixellab_api_key") == key:
                self._remove_legacy_plaintext_key(source)
                report["legacy_plaintext_secret_removed"] = True

        report["legacy_secret_still_present"] = bool(
            _read_dotenv(source).get("PIXELLAB_API_KEY", "").strip()
        )

        allowed = {
            name: value
            for name, value in values.items()
            if name.startswith("SPRITE_PIPELINE_") or name == "PIXELLAB_BASE_URL"
        }
        if not allowed:
            return
        settings_path = self.settings.config_dir / "settings.env"
        current = _read_dotenv(settings_path)
        merged = {**allowed, **current}
        payload = "".join(f"{name}={value}\n" for name, value in sorted(merged.items()))
        self._atomic_write_text(settings_path, payload)

    def _remove_legacy_plaintext_key(self, source: Path) -> None:
        original = source.read_text(encoding="utf-8-sig")
        kept = [
            line
            for line in original.splitlines(keepends=True)
            if not re.match(
                r"^\s*(?:export\s+)?PIXELLAB_API_KEY\s*=",
                line,
                flags=re.IGNORECASE,
            )
        ]
        updated = "".join(kept)
        if updated != original:
            self._atomic_write_text(source, updated)

    def _bundled_character_ids(self) -> set[str]:
        manifest_path = self.settings.bundled_presets_dir / "bundled_manifest.json"
        if manifest_path.is_file():
            payload = read_json(manifest_path)
            values = payload.get("characters", []) if isinstance(payload, dict) else []
            return {str(value) for value in values}
        # Compatibility fallback for a package created before the manifest.
        return {"diagnostic_dummy", "player_cyber"}

    def _copy_directory(
        self,
        source: Path,
        destination: Path,
        area: str,
        report: dict[str, Any],
    ) -> str:
        fingerprints = _job_tree_fingerprints if area == "jobs" else _tree_fingerprints
        source_fingerprints = fingerprints(source)
        if destination.exists():
            if destination.is_dir() and source_fingerprints == fingerprints(destination):
                report["skipped_identical"] += 1
                return "identical"
            if (
                area == "jobs"
                and destination.is_dir()
                and self._job_destination_is_compatible_newer(source, destination)
            ):
                # The active copy may have gained result commit markers, a
                # journal, or normalized safety timestamps after migration.
                # The original source is still present, so this is an expected
                # upgrade rather than a data conflict.
                report["skipped_destination_newer"] += 1
                return "destination_newer"
            self._preserve_conflict(source, area, Path(source.name), report)
            return "conflict"

        destination.parent.mkdir(parents=True, exist_ok=True)
        staging = Path(tempfile.mkdtemp(prefix=f".{destination.name}.", dir=destination.parent))
        try:
            shutil.rmtree(staging)
            shutil.copytree(source, staging, ignore=shutil.ignore_patterns("*.lock"))
            if area == "jobs":
                # summary.json is a disposable, lightweight catalog projection.
                # The destination store rebuilds it from the canonical job record.
                (staging / "summary.json").unlink(missing_ok=True)
            if source_fingerprints != fingerprints(staging):
                raise OSError("migration directory checksum mismatch")
            os.replace(staging, destination)
        finally:
            if staging.exists():
                shutil.rmtree(staging, ignore_errors=True)
        return "copied"

    @staticmethod
    def _job_destination_is_compatible_newer(
        source: Path,
        destination: Path,
    ) -> bool:
        def identity_and_revision(root: Path) -> tuple[str, int] | None:
            records = [root / "job.json"]
            records.extend(
                sorted((root / "history").glob("job_*.json"), reverse=True)
            )
            best: tuple[str, int] | None = None
            for record in records:
                if not record.is_file():
                    continue
                try:
                    payload = read_json(record)
                    job_id = payload.get("job_id")
                    revision = payload.get("revision", 0)
                    if (
                        isinstance(job_id, str)
                        and isinstance(revision, int)
                        and not isinstance(revision, bool)
                        and (best is None or revision > best[1])
                    ):
                        best = (job_id, revision)
                except Exception:
                    continue
            return best

        source_record = identity_and_revision(source)
        destination_record = identity_and_revision(destination)
        if (
            source_record is None
            or destination_record is None
            or source_record[0] != destination_record[0]
            or destination_record[1] < source_record[1]
        ):
            return False

        destination_files = dict(_job_tree_fingerprints(destination))
        for relative, digest in _job_tree_fingerprints(source):
            if relative == "job.json" or relative.startswith("history/"):
                continue
            if destination_files.get(relative) != digest:
                return False
        return True

    def _preserve_conflict(
        self,
        source: Path,
        area: str,
        relative: Path,
        report: dict[str, Any],
    ) -> None:
        digest = (
            hashlib.sha256(str(source.resolve()).encode("utf-8")).hexdigest()[:8]
        )
        conflict_root = (
            self.settings.recovery_dir
            / "migration_conflicts"
            / f"{_utc_stamp()}_{digest}"
            / area
        )
        destination = conflict_root / relative
        if source.is_dir():
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(source, destination, ignore=shutil.ignore_patterns("*.lock"))
            if _tree_fingerprints(source) != _tree_fingerprints(destination):
                raise OSError("conflict preservation checksum mismatch")
        else:
            _atomic_copy(source, destination)
        report["conflicts"].append(
            {
                "area": area,
                "source": str(source),
                "destination": str(destination),
                "reason": "destination contained different data; both copies were preserved",
            }
        )

    @staticmethod
    def _atomic_write_text(path: Path, payload: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
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
