from __future__ import annotations

from .models import ActionPreset, CharacterPreset


def compose_generation_prompt(character: CharacterPreset, action: ActionPreset) -> str:
    """Build one auditable prompt without mixing reusable identity and action data."""

    identity = character.identity_description.strip()
    if not identity:
        identity = (
            f"Preserve the exact character identity, outfit, proportions, silhouette, and palette "
            f"from the supplied first frame. The character faces {character.facing}."
        )
    parts = [
        "Character identity:",
        identity,
        "",
        "Animation action:",
        action.action_description.strip(),
        "",
        f"Produce exactly {action.frame_count} ordered animation frames on the unchanged "
        f"{character.cell_width}x{character.cell_height} canvas.",
    ]
    constraints = list(action.locked_constraints)
    required = [
        f"fixed side-view; face {character.facing}",
        "exact canvas and identity",
        f"root locked at ({character.anchor.x},{character.anchor.ground_y}) every frame; no whole-sprite canvas shift",
    ]
    if character.transparent_background:
        required.append("keep a fully transparent background")
    if action.loop and action.loop_constraint:
        required.append(action.loop_constraint)
    seen = {item.casefold() for item in constraints}
    constraints.extend(item for item in required if item.casefold() not in seen)
    parts.extend(["", "Locked constraints:"])
    parts.extend(f"- {item.strip()}" for item in constraints if item.strip())
    return "\n".join(parts).strip()
