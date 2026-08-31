"""Automatic hard checks and configurable warnings for sprite sequences."""

from __future__ import annotations

import hashlib
import json
import math
import os
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any

from PIL import Image

from ._common import PathLike, image_source_has_alpha, resolve_frame_paths, sha256_file
from .frame_alignment import clean_transparent_rgb


DEFAULT_QA_THRESHOLDS: dict[str, int | float | None] = {
    "alpha_threshold": 0,
    "safe_margin": 4,
    "area_change_ratio": 0.35,
    "centroid_jump_ratio": 0.15,
    "centroid_jump_pixels": None,
    "palette_color_distance": 48.0,
    "palette_deviation_ratio": 0.25,
    "palette_max_colors": 64,
    "loop_difference_ratio": 0.25,
    "ground_y": None,
    "ground_baseline_tolerance": 4,
    "rigid_translation_tolerance_px": 0,
    "duplicate_min_run": 2,
}


def run_frame_qa(
    frames: PathLike | Iterable[PathLike],
    *,
    expected_count: int | None = None,
    expected_size: tuple[int, int] | None = None,
    thresholds: Mapping[str, int | float | None] | None = None,
    reference_frame: PathLike | Image.Image | None = None,
    palette: PathLike | Image.Image | Sequence[Sequence[int]] | None = None,
    loop: bool = False,
    grounded: bool = False,
    source_metadata: Mapping[str, Any] | Sequence[Mapping[str, Any]] | None = None,
) -> dict[str, object]:
    """Run deterministic hard checks and warning heuristics on PNG frames.

    Hard failures block export: missing/wrong count, corrupt files, unexpected
    dimensions, blank frames, missing source alpha, exact consecutive duplicate
    runs, and whole-sprite canvas translations. Warnings cover canvas-edge
    contact, safe-margin violations, area change from a reference, adjacent
    centroid jumps, palette deviation, loop end/start difference, and grounded
    baseline drift.

    ``thresholds`` accepts the keys in :data:`DEFAULT_QA_THRESHOLDS`:

    - ``alpha_threshold``: pixels with alpha above this are content.
    - ``safe_margin``: required transparent pixels on every canvas side.
    - ``area_change_ratio``: absolute area delta from reference / reference.
    - ``centroid_jump_ratio``: adjacent centroid distance / canvas diagonal.
    - ``centroid_jump_pixels``: optional absolute override for centroid jumps.
    - ``palette_color_distance`` and ``palette_deviation_ratio``: Euclidean RGB
      tolerance and maximum out-of-palette content fraction.
    - ``palette_max_colors``: maximum most-frequent reference colours retained.
    - ``loop_difference_ratio``: maximum exact RGBA pixel mismatch fraction.
    - ``ground_y`` and ``ground_baseline_tolerance``: expected inclusive bottom
      row and allowed pixel delta. ``ground_y`` defaults to the reference.
    - ``rigid_translation_tolerance_px``: allowed exact whole-sprite translation
      between adjacent frames before export is blocked.
    - ``duplicate_min_run``: minimum identical consecutive run length (>=2).

    Imported frame directories automatically consume ``frames_manifest.json``
    to retain pre-RGBA source-alpha information. ``source_metadata`` can instead
    be an import manifest, its ``frames`` list, or an index/path mapping.

    Returns:
        A fully JSON-serializable report. ``exportable`` is false exactly when
        ``hard_failures`` is non-empty. Decode errors are reported rather than
        raised, allowing callers to display all failures in one pass.

    Raises:
        ValueError: For invalid expected values, thresholds, or palette input.
    """

    effective = _validate_thresholds(thresholds)
    if expected_count is not None and expected_count < 0:
        raise ValueError("expected_count cannot be negative.")
    if expected_size is not None:
        if len(expected_size) != 2 or expected_size[0] <= 0 or expected_size[1] <= 0:
            raise ValueError("expected_size must contain two positive integers.")
        expected_size = int(expected_size[0]), int(expected_size[1])

    paths = resolve_frame_paths(frames, allow_empty=True)
    metadata = _source_alpha_metadata(paths, source_metadata)
    hard_failures: list[dict[str, object]] = []
    warnings: list[dict[str, object]] = []
    frame_reports: list[dict[str, Any]] = []

    if not paths:
        hard_failures.append(
            {"code": "no_frames", "message": "No PNG frames were found."}
        )
    if expected_count is not None and len(paths) != expected_count:
        hard_failures.append(
            {
                "code": "frame_count_mismatch",
                "message": f"Expected {expected_count} frames, found {len(paths)}.",
                "expected": expected_count,
                "actual": len(paths),
            }
        )

    inferred_size = expected_size
    valid_images: dict[int, Image.Image] = {}
    for index, path in enumerate(paths):
        report: dict[str, Any] = {
            "index": index,
            "path": str(path.resolve()),
            "readable": False,
            "hard_failures": [],
            "warnings": [],
            "metrics": {},
        }
        try:
            with Image.open(path) as opened:
                raw_has_alpha = image_source_has_alpha(opened)
                original_mode = opened.mode
                opened.load()
                rgba = clean_transparent_rgb(opened)
            report["readable"] = True
            report["source_mode"] = original_mode
            report["width"], report["height"] = rgba.size
            report["file_sha256"] = sha256_file(path)
            report["pixel_sha256"] = _pixel_digest(rgba)
            source_has_alpha = metadata.get(index, raw_has_alpha)
            report["source_has_alpha"] = bool(source_has_alpha)
            if inferred_size is None:
                inferred_size = rgba.size
            if rgba.size != inferred_size:
                _add_hard_failure(
                    hard_failures,
                    report,
                    "frame_size_mismatch",
                    f"Frame {index} is {rgba.width}x{rgba.height}; expected "
                    f"{inferred_size[0]}x{inferred_size[1]}.",
                    expected=list(inferred_size),
                    actual=[rgba.width, rgba.height],
                )
            if not source_has_alpha:
                _add_hard_failure(
                    hard_failures,
                    report,
                    "missing_alpha",
                    f"Frame {index} source has no alpha/transparency channel.",
                )

            metrics = _content_metrics(rgba, int(effective["alpha_threshold"] or 0))
            report["metrics"].update(metrics)
            if metrics["area"] == 0:
                _add_hard_failure(
                    hard_failures,
                    report,
                    "blank_frame",
                    f"Frame {index} has no non-transparent content.",
                )
            else:
                bbox = metrics["bbox"]
                assert isinstance(bbox, list)
                if bbox[0] == 0 or bbox[1] == 0 or bbox[2] == rgba.width or bbox[3] == rgba.height:
                    _add_warning(
                        warnings,
                        report,
                        "touches_canvas_edge",
                        f"Frame {index} content touches the canvas edge.",
                    )
                margin = int(effective["safe_margin"] or 0)
                actual_margins = [bbox[0], bbox[1], rgba.width - bbox[2], rgba.height - bbox[3]]
                report["metrics"]["margins"] = actual_margins
                if margin > 0 and min(actual_margins) < margin:
                    _add_warning(
                        warnings,
                        report,
                        "safe_margin_violation",
                        f"Frame {index} violates the {margin}px safe margin.",
                        required=margin,
                        actual=actual_margins,
                    )
            valid_images[index] = rgba
        except (OSError, ValueError, SyntaxError) as exc:
            _add_hard_failure(
                hard_failures,
                report,
                "corrupt_frame",
                f"Frame {index} cannot be decoded: {exc}",
                error_type=type(exc).__name__,
            )
        frame_reports.append(report)

    duplicate_runs = _find_duplicate_runs(frame_reports, int(effective["duplicate_min_run"] or 2))
    for run in duplicate_runs:
        failure = {
            "code": "consecutive_duplicate_frames",
            "message": (
                f"Frames {run[0]}-{run[-1]} are consecutive exact duplicates."
            ),
            "frame_indices": run,
            "run_length": len(run),
        }
        hard_failures.append(failure)
        for index in run:
            frame_reports[index]["hard_failures"].append("consecutive_duplicate_frames")

    rigid_translations: list[dict[str, int]] = []
    translation_tolerance = int(effective["rigid_translation_tolerance_px"] or 0)
    for previous_index, current_index in zip(
        range(len(frame_reports) - 1), range(1, len(frame_reports))
    ):
        previous_image = valid_images.get(previous_index)
        current_image = valid_images.get(current_index)
        if previous_image is None or current_image is None or previous_image.size != current_image.size:
            continue
        previous_bbox = frame_reports[previous_index]["metrics"].get("bbox")
        current_bbox = frame_reports[current_index]["metrics"].get("bbox")
        if not isinstance(previous_bbox, list) or not isinstance(current_bbox, list):
            continue
        dx = int(current_bbox[0]) - int(previous_bbox[0])
        dy = int(current_bbox[1]) - int(previous_bbox[1])
        if dx == 0 and dy == 0:
            continue
        if (
            int(current_bbox[2]) - int(previous_bbox[2]) != dx
            or int(current_bbox[3]) - int(previous_bbox[3]) != dy
            or max(abs(dx), abs(dy)) <= translation_tolerance
        ):
            continue
        translated = Image.new("RGBA", previous_image.size, (0, 0, 0, 0))
        translated.paste(previous_image, (dx, dy))
        if translated.tobytes() != current_image.tobytes():
            continue
        translation = {
            "from": previous_index,
            "to": current_index,
            "dx": dx,
            "dy": dy,
        }
        rigid_translations.append(translation)
        _add_hard_failure(
            hard_failures,
            frame_reports[current_index],
            "frame_anchor_translation",
            (
                f"Frame {current_index} is frame {previous_index} translated by "
                f"({dx},{dy})px inside the canvas."
            ),
            previous_frame=previous_index,
            dx=dx,
            dy=dy,
            threshold=translation_tolerance,
        )

    reference_metrics, reference_error = _load_reference_metrics(
        reference_frame,
        valid_images,
        int(effective["alpha_threshold"] or 0),
    )
    if reference_error:
        warnings.append(
            {"code": "reference_unavailable", "message": reference_error}
        )
    if reference_metrics and int(reference_metrics["area"]) > 0:
        reference_area = int(reference_metrics["area"])
        area_limit = float(effective["area_change_ratio"] or 0.0)
        for index, report in enumerate(frame_reports):
            area = report["metrics"].get("area")
            if not area:
                continue
            ratio = abs(int(area) - reference_area) / reference_area
            report["metrics"]["area_change_ratio"] = round(ratio, 6)
            if ratio > area_limit:
                _add_warning(
                    warnings,
                    report,
                    "area_change",
                    f"Frame {index} area differs from reference by {ratio:.1%}.",
                    actual=round(ratio, 6),
                    threshold=area_limit,
                )

    centroid_pairs: list[dict[str, object]] = []
    pixel_limit = effective["centroid_jump_pixels"]
    ratio_limit = float(effective["centroid_jump_ratio"] or 0.0)
    for previous_index, current_index in zip(
        range(len(frame_reports) - 1), range(1, len(frame_reports))
    ):
        previous = frame_reports[previous_index]
        current = frame_reports[current_index]
        previous_centroid = previous["metrics"].get("centroid")
        current_centroid = current["metrics"].get("centroid")
        if previous_centroid is None or current_centroid is None:
            continue
        distance = math.dist(previous_centroid, current_centroid)
        width = max(int(previous.get("width", 0)), int(current.get("width", 0)))
        height = max(int(previous.get("height", 0)), int(current.get("height", 0)))
        diagonal = math.hypot(width, height) or 1.0
        ratio = distance / diagonal
        pair_metric = {
            "from": previous_index,
            "to": current_index,
            "distance_pixels": round(distance, 6),
            "distance_ratio": round(ratio, 6),
        }
        centroid_pairs.append(pair_metric)
        exceeded = distance > float(pixel_limit) if pixel_limit is not None else ratio > ratio_limit
        if exceeded:
            threshold_value = float(pixel_limit) if pixel_limit is not None else ratio_limit
            threshold_kind = "pixels" if pixel_limit is not None else "ratio"
            _add_warning(
                warnings,
                current,
                "centroid_jump",
                f"Centroid jumps from frame {previous_index} to {current_index}.",
                previous_frame=previous_index,
                distance_pixels=round(distance, 6),
                distance_ratio=round(ratio, 6),
                threshold=threshold_value,
                threshold_kind=threshold_kind,
            )

    try:
        palette_colors = _load_palette_colors(
            palette,
            int(effective["palette_max_colors"] or 64),
            int(effective["alpha_threshold"] or 0),
        )
    except (OSError, SyntaxError, ValueError) as exc:
        if not isinstance(palette, (str, os.PathLike, Image.Image)):
            raise
        palette_colors = []
        warnings.append(
            {
                "code": "palette_unavailable",
                "message": f"Palette cannot be decoded; palette check was skipped: {exc}",
                "error_type": type(exc).__name__,
            }
        )
    if palette_colors:
        distance_limit = float(effective["palette_color_distance"] or 0.0)
        deviation_limit = float(effective["palette_deviation_ratio"] or 0.0)
        for index, image in valid_images.items():
            ratio = _palette_deviation_ratio(
                image,
                palette_colors,
                distance_limit,
                int(effective["alpha_threshold"] or 0),
            )
            frame_reports[index]["metrics"]["palette_deviation_ratio"] = round(ratio, 6)
            if ratio > deviation_limit:
                _add_warning(
                    warnings,
                    frame_reports[index],
                    "palette_deviation",
                    f"Frame {index} has {ratio:.1%} out-of-palette content.",
                    actual=round(ratio, 6),
                    threshold=deviation_limit,
                )

    loop_metric: dict[str, object] | None = None
    if loop and frame_reports:
        first = valid_images.get(0)
        last_index = len(frame_reports) - 1
        last = valid_images.get(last_index)
        if first is not None and last is not None and first.size == last.size:
            different = sum(
                left != right
                for left, right in zip(
                    _rgba_pixels(first),
                    _rgba_pixels(last),
                )
            )
            ratio = different / (first.width * first.height)
            loop_metric = {
                "different_pixels": different,
                "difference_ratio": round(ratio, 6),
            }
            limit = float(effective["loop_difference_ratio"] or 0.0)
            if ratio > limit:
                _add_warning(
                    warnings,
                    frame_reports[last_index],
                    "loop_endpoint_difference",
                    f"Last frame differs from first by {ratio:.1%} of pixels.",
                    actual=round(ratio, 6),
                    threshold=limit,
                )

    ground_reference: int | None = None
    if grounded:
        configured_ground = effective["ground_y"]
        if configured_ground is not None:
            ground_reference = int(configured_ground)
        elif reference_metrics and reference_metrics.get("ground_y") is not None:
            ground_reference = int(reference_metrics["ground_y"])
        tolerance = int(effective["ground_baseline_tolerance"] or 0)
        if ground_reference is not None:
            for index, report in enumerate(frame_reports):
                ground_y = report["metrics"].get("ground_y")
                if ground_y is None:
                    continue
                delta = int(ground_y) - ground_reference
                report["metrics"]["ground_delta"] = delta
                if abs(delta) > tolerance:
                    _add_warning(
                        warnings,
                        report,
                        "ground_baseline_drift",
                        f"Frame {index} ground baseline drifts by {delta}px.",
                        expected=ground_reference,
                        actual=int(ground_y),
                        delta=delta,
                        threshold=tolerance,
                    )

    exportable = not hard_failures
    status = "failed" if not exportable else ("warning" if warnings else "passed")
    report: dict[str, object] = {
        "schema_version": 1,
        "status": status,
        "exportable": exportable,
        "expected": {
            "frame_count": expected_count,
            "frame_size": list(expected_size) if expected_size else None,
        },
        "actual": {
            "frame_count": len(paths),
            "inferred_frame_size": list(inferred_size) if inferred_size else None,
        },
        "thresholds": effective,
        "hard_failures": hard_failures,
        "warnings": warnings,
        "summary": {
            "hard_failure_count": len(hard_failures),
            "warning_count": len(warnings),
            "readable_frame_count": len(valid_images),
        },
        "sequence_metrics": {
            "duplicate_runs": duplicate_runs,
            "rigid_translations": rigid_translations,
            "centroid_pairs": centroid_pairs,
            "palette_color_count": len(palette_colors),
            "loop": loop_metric,
            "ground_y": ground_reference,
        },
        "frames": frame_reports,
    }
    # Assert the public contract during development without changing its value.
    json.dumps(report, ensure_ascii=False, allow_nan=False)
    return report


def run_frame_checks(*args: Any, **kwargs: Any) -> dict[str, object]:
    """Compatibility name for :func:`run_frame_qa`."""

    return run_frame_qa(*args, **kwargs)


def run_qa(
    frame_paths: PathLike | Iterable[PathLike],
    expected_count: int,
    cell_width: int,
    cell_height: int,
    reference_path: PathLike | None = None,
    palette_path: PathLike | None = None,
    safe_margin: int = 4,
    grounded: bool = False,
    anchor_ground_y: int | None = None,
    loop: bool = False,
    thresholds: Mapping[str, int | float | None] | None = None,
) -> dict[str, object]:
    """Stable harness wrapper around :func:`run_frame_qa`.

    Explicit wrapper arguments map character/action preset fields into the flat
    QA-threshold dictionary. Values already present in ``thresholds`` win, so a
    per-action override can intentionally replace the character defaults. The
    returned dictionary is JSON serializable and its ``exportable`` field is
    false whenever at least one hard failure is present.
    """

    merged: dict[str, int | float | None] = dict(thresholds or {})
    merged.setdefault("safe_margin", safe_margin)
    if anchor_ground_y is not None:
        merged.setdefault("ground_y", anchor_ground_y)
    return run_frame_qa(
        frame_paths,
        expected_count=expected_count,
        expected_size=(cell_width, cell_height),
        thresholds=merged,
        reference_frame=reference_path,
        palette=palette_path,
        loop=loop,
        grounded=grounded,
    )


def _validate_thresholds(
    supplied: Mapping[str, int | float | None] | None,
) -> dict[str, int | float | None]:
    effective = dict(DEFAULT_QA_THRESHOLDS)
    if supplied:
        unknown = sorted(set(supplied) - set(effective))
        if unknown:
            raise ValueError(f"Unknown QA threshold(s): {', '.join(unknown)}")
        effective.update(supplied)

    alpha = int(effective["alpha_threshold"] or 0)
    if not 0 <= alpha <= 254:
        raise ValueError("alpha_threshold must be between 0 and 254.")
    effective["alpha_threshold"] = alpha
    for name in (
        "safe_margin",
        "ground_baseline_tolerance",
        "rigid_translation_tolerance_px",
    ):
        value = int(effective[name] or 0)
        if value < 0:
            raise ValueError(f"{name} cannot be negative.")
        effective[name] = value
    duplicate_min_run = int(effective["duplicate_min_run"] or 2)
    if duplicate_min_run < 2:
        raise ValueError("duplicate_min_run must be at least 2.")
    effective["duplicate_min_run"] = duplicate_min_run
    palette_max = int(effective["palette_max_colors"] or 64)
    if palette_max < 1:
        raise ValueError("palette_max_colors must be positive.")
    effective["palette_max_colors"] = palette_max
    if effective["ground_y"] is not None:
        effective["ground_y"] = int(effective["ground_y"])
    for name in (
        "area_change_ratio",
        "centroid_jump_ratio",
        "palette_color_distance",
        "palette_deviation_ratio",
        "loop_difference_ratio",
    ):
        value = float(effective[name] or 0.0)
        if value < 0:
            raise ValueError(f"{name} cannot be negative.")
        effective[name] = value
    if effective["centroid_jump_pixels"] is not None:
        value = float(effective["centroid_jump_pixels"])
        if value < 0:
            raise ValueError("centroid_jump_pixels cannot be negative.")
        effective["centroid_jump_pixels"] = value
    return effective


def _source_alpha_metadata(
    paths: list[Path],
    supplied: Mapping[str, Any] | Sequence[Mapping[str, Any]] | None,
) -> dict[int, bool]:
    result: dict[int, bool] = {}
    value: Any = supplied
    if value is None:
        manifest_cache: dict[Path, list[Mapping[str, Any]]] = {}
        for index, path in enumerate(paths):
            parent = path.parent.resolve()
            if parent not in manifest_cache:
                manifest_cache[parent] = []
                manifest_path = parent / "frames_manifest.json"
                if manifest_path.is_file():
                    try:
                        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
                        records = payload.get("frames", []) if isinstance(payload, Mapping) else []
                        if isinstance(records, list):
                            manifest_cache[parent] = [
                                item for item in records if isinstance(item, Mapping)
                            ]
                    except (OSError, ValueError, TypeError):
                        pass
            for item in manifest_cache[parent]:
                if "source_has_alpha" not in item:
                    continue
                output_path = item.get("output_path")
                output_name = item.get("output_name")
                matches_path = output_path is not None and os.path.normcase(
                    str(Path(str(output_path)).expanduser().resolve())
                ) == os.path.normcase(str(path.resolve()))
                if matches_path or output_name == path.name:
                    result[index] = bool(item["source_has_alpha"])
                    break
        return result

    if isinstance(value, Mapping) and isinstance(value.get("frames"), Sequence):
        value = value["frames"]

    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        for fallback_index, item in enumerate(value):
            if not isinstance(item, Mapping) or "source_has_alpha" not in item:
                continue
            index = int(item.get("index", fallback_index))
            result[index] = bool(item["source_has_alpha"])
    elif isinstance(value, Mapping):
        for index, path in enumerate(paths):
            candidates = (index, str(index), path.name, str(path), str(path.resolve()))
            for key in candidates:
                if key in value:
                    item = value[key]
                    if isinstance(item, Mapping):
                        item = item.get("source_has_alpha")
                    result[index] = bool(item)
                    break
    return result


def _content_metrics(image: Image.Image, alpha_threshold: int) -> dict[str, object]:
    width, height = image.size
    alpha = image.getchannel("A").tobytes()
    area = 0
    sum_x = 0
    sum_y = 0
    left = width
    top = height
    right = -1
    bottom = -1
    for offset, value in enumerate(alpha):
        if value <= alpha_threshold:
            continue
        x = offset % width
        y = offset // width
        area += 1
        sum_x += x
        sum_y += y
        left = min(left, x)
        top = min(top, y)
        right = max(right, x)
        bottom = max(bottom, y)
    if area == 0:
        return {"area": 0, "area_ratio": 0.0, "bbox": None, "centroid": None, "ground_y": None}
    return {
        "area": area,
        "area_ratio": round(area / (width * height), 6),
        "bbox": [left, top, right + 1, bottom + 1],
        "centroid": [round(sum_x / area, 6), round(sum_y / area, 6)],
        "ground_y": bottom,
    }


def _pixel_digest(image: Image.Image) -> str:
    digest = hashlib.sha256()
    digest.update(f"RGBA:{image.width}x{image.height}:".encode("ascii"))
    digest.update(image.tobytes())
    return digest.hexdigest()


def _find_duplicate_runs(reports: list[dict[str, Any]], minimum: int) -> list[list[int]]:
    runs: list[list[int]] = []
    current: list[int] = []
    previous_digest: str | None = None
    for index, report in enumerate(reports):
        digest = report.get("pixel_sha256") if report.get("readable") else None
        if digest is not None and digest == previous_digest:
            if not current:
                current = [index - 1]
            current.append(index)
        else:
            if len(current) >= minimum:
                runs.append(current)
            current = []
        previous_digest = digest
    if len(current) >= minimum:
        runs.append(current)
    return runs


def _load_reference_metrics(
    reference: PathLike | Image.Image | None,
    valid_images: dict[int, Image.Image],
    alpha_threshold: int,
) -> tuple[dict[str, object] | None, str | None]:
    if reference is None:
        first = valid_images.get(0)
        if first is None:
            return None, None
        return _content_metrics(first, alpha_threshold), None
    try:
        if isinstance(reference, Image.Image):
            image = clean_transparent_rgb(reference)
        else:
            with Image.open(Path(reference).expanduser()) as opened:
                opened.load()
                image = clean_transparent_rgb(opened)
        return _content_metrics(image, alpha_threshold), None
    except (OSError, ValueError, SyntaxError) as exc:
        return None, f"Reference frame cannot be decoded: {exc}"


def _load_palette_colors(
    palette: PathLike | Image.Image | Sequence[Sequence[int]] | None,
    maximum: int,
    alpha_threshold: int,
) -> list[tuple[int, int, int]]:
    if palette is None:
        return []
    if isinstance(palette, Image.Image):
        return _most_frequent_colors(clean_transparent_rgb(palette), maximum, alpha_threshold)
    if isinstance(palette, (str, os.PathLike)):
        with Image.open(Path(palette).expanduser()) as opened:
            opened.load()
            image = clean_transparent_rgb(opened)
        return _most_frequent_colors(image, maximum, alpha_threshold)
    colors: set[tuple[int, int, int]] = set()
    for item in palette:
        if len(item) < 3:
            raise ValueError("Every palette colour must have at least RGB values.")
        color = tuple(int(channel) for channel in item[:3])
        if any(channel < 0 or channel > 255 for channel in color):
            raise ValueError("Palette RGB values must be between 0 and 255.")
        colors.add(color)
    return sorted(colors)[:maximum]


def _most_frequent_colors(
    image: Image.Image, maximum: int, alpha_threshold: int
) -> list[tuple[int, int, int]]:
    counts: Counter[tuple[int, int, int]] = Counter()
    for red, green, blue, alpha in image.getdata():
        if alpha > alpha_threshold:
            counts[(red, green, blue)] += 1
    ordered = sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    return [color for color, _count in ordered[:maximum]]


def _palette_deviation_ratio(
    image: Image.Image,
    palette: list[tuple[int, int, int]],
    maximum_distance: float,
    alpha_threshold: int,
) -> float:
    counts: Counter[tuple[int, int, int]] = Counter()
    for red, green, blue, alpha in image.getdata():
        if alpha > alpha_threshold:
            counts[(red, green, blue)] += 1
    total = sum(counts.values())
    if total == 0:
        return 0.0
    limit_squared = maximum_distance * maximum_distance
    cache: dict[tuple[int, int, int], bool] = {}
    outside = 0
    for color, count in counts.items():
        if color not in cache:
            cache[color] = min(
                (color[0] - target[0]) ** 2
                + (color[1] - target[1]) ** 2
                + (color[2] - target[2]) ** 2
                for target in palette
            ) > limit_squared
        if cache[color]:
            outside += count
    return outside / total


def _rgba_pixels(image: Image.Image) -> list[bytes]:
    raw = image.tobytes()
    return [raw[offset : offset + 4] for offset in range(0, len(raw), 4)]


def _add_hard_failure(
    failures: list[dict[str, object]],
    frame_report: dict[str, Any],
    code: str,
    message: str,
    **details: object,
) -> None:
    failures.append(
        {
            "code": code,
            "message": message,
            "frame_index": frame_report["index"],
            **details,
        }
    )
    frame_report["hard_failures"].append(code)


def _add_warning(
    warnings: list[dict[str, object]],
    frame_report: dict[str, Any],
    code: str,
    message: str,
    **details: object,
) -> None:
    warnings.append(
        {
            "code": code,
            "message": message,
            "frame_index": frame_report["index"],
            **details,
        }
    )
    frame_report["warnings"].append(code)
