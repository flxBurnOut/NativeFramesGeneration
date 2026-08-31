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
        f"Produce exactly {action.generation_frame_count} ordered animation frames on the unchanged "
        f"{character.cell_width}x{character.cell_height} canvas.",
    ]
    if action.generation_frame_count != action.frame_count:
        retained = ", ".join(str(index + 1) for index in action.generation_frame_selection)
        parts.extend(
            [
                "",
                f"Keep all source frames continuous. The harness retains frames {retained} "
                f"as the project's {action.frame_count}-frame sequence.",
            ]
        )
    constraints = list(action.locked_constraints)
    required = [
        f"fixed side-view; face {character.facing}",
        "exact canvas and identity",
        (
            f"start near root reference ({character.anchor.x},{character.anchor.ground_y}); "
            "smooth frame-to-frame root path; no sudden whole-sprite jump"
        ),
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
