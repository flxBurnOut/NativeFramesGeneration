from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


APPLICATION_DIRECTORY_NAME = "SpritePipeline"


def _read_dotenv(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.is_file():
        return values
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key:
            values[key] = value
    return values


def _setting(env: dict[str, str], name: str, default: str) -> str:
    return os.environ.get(name, env.get(name, default))


def _default_data_root() -> Path:
    if os.name == "nt":
        local_app_data = os.environ.get("LOCALAPPDATA")
        if local_app_data:
            return Path(local_app_data) / APPLICATION_DIRECTORY_NAME
        return Path.home() / "AppData" / "Local" / APPLICATION_DIRECTORY_NAME
    xdg_data_home = os.environ.get("XDG_DATA_HOME")
    if xdg_data_home:
        return Path(xdg_data_home) / APPLICATION_DIRECTORY_NAME
    return Path.home() / ".local" / "share" / APPLICATION_DIRECTORY_NAME


def _default_exports_root() -> Path:
    configured = os.environ.get("SPRITE_PIPELINE_EXPORTS_DIR")
    if configured:
        return Path(configured)
    return Path.home() / "Documents" / APPLICATION_DIRECTORY_NAME / "Exports"


@dataclass(frozen=True)
class HarnessSettings:
    """Resolved application, user-data, secret, job, and export locations.

    A caller-supplied root is an explicit portable/test layout retained for CLI
    backwards compatibility. Normal application startup never writes user data
    beside the installed source tree.
    """

    install_root: Path
    data_root: Path
    root: Path
    bundled_presets_dir: Path
    user_characters_dir: Path
    presets_dir: Path
    jobs_dir: Path
    work_dir: Path
    exports_dir: Path
    config_dir: Path
    cache_dir: Path
    recovery_dir: Path
    legacy_root: Path | None
    portable_mode: bool
    pixellab_api_key: str | None
    pixellab_base_url: str
    poll_interval_seconds: float
    max_wait_seconds: float
    http_timeout_seconds: float
    max_download_bytes: int

    @classmethod
    def load(cls, root: str | Path | None = None) -> "HarnessSettings":
        package_install_root = Path(__file__).resolve().parent.parent
        install_root = Path(
            os.environ.get("SPRITE_PIPELINE_INSTALL_ROOT", package_install_root)
        ).resolve()

        # --root and the legacy SPRITE_PIPELINE_HOME variable remain an
        # explicit portable/testing opt-in. The default desktop application
        # uses a per-user OS data directory instead.
        legacy_explicit_root = os.environ.get("SPRITE_PIPELINE_HOME")
        requested_root = root or legacy_explicit_root
        portable_mode = requested_root is not None
        if portable_mode:
            data_root = Path(requested_root).resolve()
            bundled_presets_dir = data_root / "presets"
            user_characters_dir = bundled_presets_dir / "characters"
            jobs_dir = data_root / "work"
            exports_dir = data_root / "exports"
            config_dir = data_root
            legacy_root: Path | None = None
        else:
            configured_data_root = os.environ.get("SPRITE_PIPELINE_DATA_DIR")
            data_root = Path(configured_data_root or _default_data_root()).resolve()
            bundled_presets_dir = install_root / "presets"
            user_characters_dir = data_root / "characters"
            jobs_dir = data_root / "jobs"
            exports_dir = _default_exports_root().resolve()
            config_dir = data_root / "config"
            legacy_root = install_root if install_root != data_root else None

        # Non-secret tunables live in the user config directory. Reading the
        # old .env is compatibility-only so migration can occur without making
        # a previously configured API unusable during the transition.
        config_env = _read_dotenv(config_dir / "settings.env")
        portable_env = _read_dotenv(data_root / ".env") if portable_mode else {}
        legacy_env = _read_dotenv(legacy_root / ".env") if legacy_root else {}
        env = {**legacy_env, **portable_env, **config_env}

        saved_key: str | None = None
        try:
            from .credential_store import CredentialStore

            saved_key = CredentialStore(config_dir).get("pixellab_api_key")
        except Exception:
            # A damaged credential file must not make offline workflows fail to
            # start. The storage report exposes the problem in the UI.
            saved_key = None
        # Once a credential file exists (including an explicit cleared
        # tombstone), never resurrect a legacy plaintext key from .env.
        credential_file_exists = (config_dir / "credentials.json").is_file()
        legacy_key = "" if credential_file_exists else env.get("PIXELLAB_API_KEY", "").strip()
        key = (
            os.environ.get("PIXELLAB_API_KEY", "").strip()
            or (saved_key or "").strip()
            or legacy_key
            or None
        )
        return cls(
            install_root=install_root,
            data_root=data_root,
            root=data_root,
            bundled_presets_dir=bundled_presets_dir,
            user_characters_dir=user_characters_dir,
            presets_dir=bundled_presets_dir,
            jobs_dir=jobs_dir,
            work_dir=jobs_dir,
            exports_dir=exports_dir,
            config_dir=config_dir,
            cache_dir=data_root / "cache",
            recovery_dir=data_root / "recovery",
            legacy_root=legacy_root,
            portable_mode=portable_mode,
            pixellab_api_key=key,
            pixellab_base_url=_setting(env, "PIXELLAB_BASE_URL", "https://api.pixellab.ai").rstrip("/"),
            poll_interval_seconds=float(_setting(env, "SPRITE_PIPELINE_POLL_INTERVAL_SECONDS", "5")),
            max_wait_seconds=float(_setting(env, "SPRITE_PIPELINE_MAX_WAIT_SECONDS", "300")),
            http_timeout_seconds=float(_setting(env, "SPRITE_PIPELINE_HTTP_TIMEOUT_SECONDS", "60")),
            max_download_bytes=int(_setting(env, "SPRITE_PIPELINE_MAX_DOWNLOAD_BYTES", "20971520")),
        )

    def ensure_directories(self) -> None:
        if not self.bundled_presets_dir.is_dir():
            if self.portable_mode:
                (self.bundled_presets_dir / "characters").mkdir(parents=True, exist_ok=True)
                (self.bundled_presets_dir / "actions").mkdir(parents=True, exist_ok=True)
            else:
                raise FileNotFoundError(f"bundled preset directory is missing: {self.bundled_presets_dir}")
        self.data_root.mkdir(parents=True, exist_ok=True)
        self.user_characters_dir.mkdir(parents=True, exist_ok=True)
        self.jobs_dir.mkdir(parents=True, exist_ok=True)
        self.exports_dir.mkdir(parents=True, exist_ok=True)
        self.config_dir.mkdir(parents=True, exist_ok=True)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.recovery_dir.mkdir(parents=True, exist_ok=True)

    def public_paths(self) -> dict[str, str | bool | None]:
        return {
            "install_root": str(self.install_root),
            "data_root": str(self.data_root),
            "jobs_dir": str(self.jobs_dir),
            "user_characters_dir": str(self.user_characters_dir),
            "exports_dir": str(self.exports_dir),
            "cache_dir": str(self.cache_dir),
            "portable_mode": self.portable_mode,
            "legacy_root": str(self.legacy_root) if self.legacy_root else None,
        }

    def resolve_record_path(self, value: str) -> Path:
        path = Path(value)
        return path.resolve() if path.is_absolute() else (self.data_root / path).resolve()

    def record_path(self, path: Path) -> str:
        resolved = path.resolve()
        try:
            return resolved.relative_to(self.data_root).as_posix()
        except ValueError:
            return str(resolved)
