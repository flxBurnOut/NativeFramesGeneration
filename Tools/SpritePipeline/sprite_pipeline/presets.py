from __future__ import annotations

from pathlib import Path

from pydantic import ValidationError

from .errors import NotFoundError, ValidationHarnessError
from .jsonio import inside, read_json
from .models import ActionPreset, CharacterPreset
from .settings import HarnessSettings


class PresetRepository:
    def __init__(self, settings: HarnessSettings) -> None:
        self.settings = settings

    @staticmethod
    def _safe_id(value: str, field: str) -> str:
        if not value or not all(ch.islower() or ch.isdigit() or ch == "_" for ch in value):
            raise ValidationHarnessError(f"invalid {field}", details={field: value})
        return value

    def character_path(self, character_id: str) -> Path:
        safe = self._safe_id(character_id, "character_id")
        return inside(self.settings.presets_dir, self.settings.presets_dir / "characters" / safe / "character.json")

    def action_path(self, action_id: str) -> Path:
        safe = self._safe_id(action_id, "action_id")
        return inside(self.settings.presets_dir, self.settings.presets_dir / "actions" / f"{safe}.json")

    def load_character(self, character_id: str, *, verify_assets: bool = True) -> tuple[CharacterPreset, Path]:
        path = self.character_path(character_id)
        if not path.is_file():
            raise NotFoundError("character preset not found", details={"character_id": character_id})
        try:
            preset = CharacterPreset.model_validate(read_json(path))
        except (ValidationError, ValueError) as exc:
            raise ValidationHarnessError("invalid character preset", details={"path": str(path), "error": str(exc)}) from exc
        if preset.character_id != character_id:
            raise ValidationHarnessError("character directory and character_id differ", details={"path": str(path)})
        if verify_assets:
            for field, filename, required in (
                ("reference_frame", preset.reference_frame, True),
                ("master", preset.master, False),
                ("palette", preset.palette, False),
                ("silhouette", preset.silhouette, False),
            ):
                if filename is None:
                    continue
                asset = inside(path.parent, path.parent / filename)
                if not asset.is_file() and required:
                    raise ValidationHarnessError("required character asset is missing", details={"field": field, "path": str(asset)})
                if not asset.is_file() and not required:
                    raise ValidationHarnessError("configured character asset is missing", details={"field": field, "path": str(asset)})
        return preset, path

    def load_action(self, action_id: str) -> tuple[ActionPreset, Path]:
        path = self.action_path(action_id)
        if not path.is_file():
            raise NotFoundError("action preset not found", details={"action_id": action_id})
        try:
            preset = ActionPreset.model_validate(read_json(path))
        except (ValidationError, ValueError) as exc:
            raise ValidationHarnessError("invalid action preset", details={"path": str(path), "error": str(exc)}) from exc
        if preset.action_id != action_id:
            raise ValidationHarnessError("action filename and action_id differ", details={"path": str(path)})
        return preset, path

    def list_characters(self) -> list[dict[str, str | bool]]:
        rows: list[dict[str, str | bool]] = []
        base = self.settings.presets_dir / "characters"
        for path in sorted(base.glob("*/character.json")):
            try:
                preset, _preset_path = self.load_character(path.parent.name, verify_assets=True)
                rows.append({"id": preset.character_id, "name": preset.display_name, "path": str(path), "valid": True})
            except Exception as exc:
                rows.append(
                    {
                        "id": path.parent.name,
                        "name": "INVALID",
                        "path": str(path),
                        "valid": False,
                        "error": str(exc),
                    }
                )
        return rows

    def list_actions(self) -> list[dict[str, str]]:
        rows: list[dict[str, str]] = []
        base = self.settings.presets_dir / "actions"
        for path in sorted(base.glob("*.json")):
            try:
                preset = ActionPreset.model_validate(read_json(path))
                rows.append({"id": preset.action_id, "name": preset.display_name or preset.action_id, "path": str(path)})
            except Exception:
                rows.append({"id": path.stem, "name": "INVALID", "path": str(path)})
        return rows
