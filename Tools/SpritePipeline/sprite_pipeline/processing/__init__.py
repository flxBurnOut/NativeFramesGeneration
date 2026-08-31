"""Pure-Pillow import, QA, preview, and export utilities.

All public functions accept :class:`pathlib.Path` or Unicode path strings and
return JSON-serializable dictionaries where applicable. They do not depend on a
web UI, model provider, database, or process-global state, making the same core
safe to drive through API endpoints, a CLI, or Codex.
"""

from .frame_alignment import clean_png_transparency, clean_rgba_file, clean_transparent_rgb
from .frame_checks import DEFAULT_QA_THRESHOLDS, run_frame_checks, run_frame_qa, run_qa
from .frame_import import (
    import_frames,
    import_gif,
    import_png_sequence,
    import_sprite_sheet,
    ingest_frames,
)
from .preview import (
    build_baseline_grid,
    build_first_frame_overlay,
    build_frame_grid,
    build_gif,
    build_overlay,
    build_previews,
    build_review_grid,
)
from .sheet_export import build_sprite_sheet, export_sprite_sheet

__all__ = [
    "DEFAULT_QA_THRESHOLDS",
    "build_first_frame_overlay",
    "build_frame_grid",
    "build_gif",
    "build_baseline_grid",
    "build_overlay",
    "build_previews",
    "build_review_grid",
    "build_sprite_sheet",
    "clean_png_transparency",
    "clean_rgba_file",
    "clean_transparent_rgb",
    "export_sprite_sheet",
    "import_frames",
    "import_gif",
    "import_png_sequence",
    "import_sprite_sheet",
    "ingest_frames",
    "run_frame_checks",
    "run_frame_qa",
    "run_qa",
]
