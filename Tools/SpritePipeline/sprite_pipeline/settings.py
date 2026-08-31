from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


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


@dataclass(frozen=True)
class HarnessSettings:
    root: Path
    presets_dir: Path
    work_dir: Path
    exports_dir: Path
    pixellab_api_key: str | None
    pixellab_base_url: str
    poll_interval_seconds: float
    max_wait_seconds: float
    http_timeout_seconds: float
    max_download_bytes: int

    @classmethod
    def load(cls, root: str | Path | None = None) -> "HarnessSettings":
        default_root = Path(__file__).resolve().parent.parent
        root_path = Path(root or os.environ.get("SPRITE_PIPELINE_HOME", default_root)).resolve()
        env = _read_dotenv(root_path / ".env")
        key = _setting(env, "PIXELLAB_API_KEY", "").strip() or None
        return cls(
            root=root_path,
            presets_dir=root_path / "presets",
            work_dir=root_path / "work",
            exports_dir=root_path / "exports",
            pixellab_api_key=key,
            pixellab_base_url=_setting(env, "PIXELLAB_BASE_URL", "https://api.pixellab.ai").rstrip("/"),
            poll_interval_seconds=float(_setting(env, "SPRITE_PIPELINE_POLL_INTERVAL_SECONDS", "5")),
            max_wait_seconds=float(_setting(env, "SPRITE_PIPELINE_MAX_WAIT_SECONDS", "300")),
            http_timeout_seconds=float(_setting(env, "SPRITE_PIPELINE_HTTP_TIMEOUT_SECONDS", "60")),
            max_download_bytes=int(_setting(env, "SPRITE_PIPELINE_MAX_DOWNLOAD_BYTES", "20971520")),
        )

    def ensure_directories(self) -> None:
        self.presets_dir.mkdir(parents=True, exist_ok=True)
        (self.presets_dir / "characters").mkdir(parents=True, exist_ok=True)
        (self.presets_dir / "actions").mkdir(parents=True, exist_ok=True)
        self.work_dir.mkdir(parents=True, exist_ok=True)
        self.exports_dir.mkdir(parents=True, exist_ok=True)

