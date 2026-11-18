"""Resolve one task source and bind audit results to its exact bytes.

The project manifest selects a relative task file. Legacy projects without a
manifest continue to use ``批量任务.json``. This module performs no rendering,
prompt rewriting, or network operations.
"""

import hashlib
import json
import re
import math
from pathlib import Path, PureWindowsPath


MANIFEST_NAME = ".tunjing_project.json"
LEGACY_BATCH_NAME = "批量任务.json"
MAX_PROMPT_BYTES = 8000


class TaskSourceError(ValueError):
    """The configured task or its recorded audit cannot be used."""


def _object_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise TaskSourceError("Duplicate JSON key: " + key)
        result[key] = value
    return result


def _read_json(path):
    try:
        raw = path.read_bytes()
        value = json.loads(raw.decode("utf-8-sig"), object_pairs_hook=_object_pairs)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise TaskSourceError("Cannot read JSON source " + str(path) + ": " + str(exc)) from exc
    return raw, value


def resolve_task_path(project_dir):
    """Return the selected task's absolute path, rejecting path escapes."""
    try:
        root = Path(project_dir).expanduser().resolve()
    except (OSError, ValueError, TypeError) as exc:
        raise TaskSourceError("Invalid project directory: " + str(exc)) from exc
    if not root.is_dir():
        raise TaskSourceError("Project directory is missing: " + str(root))
    manifest = root / MANIFEST_NAME
    if manifest.exists():
        _, config = _read_json(manifest)
        if not isinstance(config, dict):
            raise TaskSourceError("Project manifest must be a JSON object")
        relative = config.get("active_batch")
        if not isinstance(relative, str) or not relative.strip() or "\0" in relative:
            raise TaskSourceError("Project manifest requires a nonempty active_batch path")
        # Check Windows drive/UNC syntax too, keeping the rule portable.
        windows_path = PureWindowsPath(relative)
        candidate = Path(relative)
        if candidate.is_absolute() or windows_path.drive or windows_path.root:
            raise TaskSourceError("active_batch must be relative to the project directory")
        selected = (root / candidate).resolve()
        try:
            selected.relative_to(root)
        except ValueError as exc:
            raise TaskSourceError("active_batch escapes the project directory") from exc
    else:
        selected = (root / LEGACY_BATCH_NAME).resolve()
        try:
            selected.relative_to(root)
        except ValueError as exc:
            raise TaskSourceError("Task file escapes the project directory") from exc
    if not selected.is_file():
        raise TaskSourceError("Selected task file is missing: " + str(selected))
    return selected


def load_task_source(project_dir):
    """Return ``(absolute_path, batch, sha256)`` after per-shot validation."""
    path = resolve_task_path(project_dir)
    raw, batch = _read_json(path)
    if not isinstance(batch, dict):
        raise TaskSourceError("Task source must be a JSON object")
    if "schema" in batch and batch["schema"] != "h3-drama-task":
        raise TaskSourceError("Unsupported task schema: " + repr(batch["schema"]))
    shots = batch.get("batch_shots")
    if not isinstance(shots, list) or not shots:
        raise TaskSourceError("Task source requires a nonempty batch_shots list")
    seen = set()
    for index, shot in enumerate(shots, 1):
        if not isinstance(shot, dict):
            raise TaskSourceError("Shot " + str(index) + " must be a JSON object")
        identifier = shot.get("shot_id", shot.get("id"))
        if isinstance(identifier, bool) or not isinstance(identifier, (str, int)):
            raise TaskSourceError("Shot " + str(index) + " requires a shot_id or id")
        identifier = str(identifier).strip()
        if not identifier:
            raise TaskSourceError("Shot " + str(index) + " has an empty identifier")
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]*", identifier):
            raise TaskSourceError("Shot identifier contains unsupported path characters: " + identifier)
        if identifier in seen:
            raise TaskSourceError("Duplicate shot identifier: " + identifier)
        seen.add(identifier)
        prompt = shot.get("prompt")
        if not isinstance(prompt, str) or not prompt.strip():
            raise TaskSourceError("Shot " + identifier + " requires a nonempty prompt string")
        try:
            size = len(prompt.encode("utf-8"))
        except UnicodeError as exc:
            raise TaskSourceError("Shot " + identifier + " prompt is not valid UTF-8") from exc
        if size > MAX_PROMPT_BYTES:
            raise TaskSourceError("Shot " + identifier + " prompt exceeds 8000 UTF-8 bytes")
    return path, batch, hashlib.sha256(raw).hexdigest()


def source_record(project_dir):
    path, _, digest = load_task_source(project_dir)
    return {"task_path": str(path), "task_sha256": digest}


def refresh_status(project_dir, status):
    """Invalidate task-dependent gates in place when source evidence is stale.

    Source errors also revoke dependent gates and are recorded for the caller,
    allowing it to persist the revoked state before displaying the error.
    """
    if not isinstance(status, dict):
        raise TaskSourceError("Gate status must be a JSON object")
    try:
        current = source_record(project_dir)
        status.pop("source_error", None)
    except (TaskSourceError, OSError, ValueError) as exc:
        current = None
        status["source_error"] = str(exc)
    passed = status.get("passed_steps", [])
    if not isinstance(passed, list):
        passed = []
    gate_sources = status.get("gate_sources", {})
    if not isinstance(gate_sources, dict):
        gate_sources = {}
    stale = current is None or any(
        step in passed and gate_sources.get(str(step)) != current
        for step in (4, 5)
    )
    # A later gate cannot be current while its task audit records are absent.
    try:
        current_step = int(status.get("current_step", 1))
    except (TypeError, ValueError):
        current_step = 1
    required_prior_gates = tuple(step for step in (4, 5) if step < current_step)
    if required_prior_gates and not all(
        step in passed and gate_sources.get(str(step)) == current
        for step in required_prior_gates
    ):
        stale = True
    if stale:
        status["passed_steps"] = [step for step in passed if step not in (4, 5, 6)]
        status["current_step"] = min(current_step, 4)
        status["gate_sources"] = {
            key: value for key, value in gate_sources.items() if str(key) not in ("4", "5", "6")
        }
    return status


def require_source_audit(project_dir, status):
    """Reject missing/stale gate 4 and 5 evidence for the selected task."""
    if not isinstance(status, dict):
        raise TaskSourceError("Gate status must be a JSON object")
    current = source_record(project_dir)
    passed = status.get("passed_steps", [])
    sources = status.get("gate_sources", {})
    if not isinstance(passed, list) or not isinstance(sources, dict):
        raise TaskSourceError("Invalid task audit status")
    if not {1, 2, 3, 4, 5}.issubset(set(passed)):
        raise TaskSourceError("Project gates 1 through 5 must all have passed")
    for step in (4, 5):
        if step not in passed:
            raise TaskSourceError("Task audit gate " + str(step) + " has not passed")
        if sources.get(str(step)) != current:
            raise TaskSourceError("Task audit gate " + str(step) + " is stale or unbound")
    return current


def validate_batch_metadata(batch):
    """Validate dispatch metadata without changing prompts or caller objects."""
    if not isinstance(batch, dict) or not isinstance(batch.get("batch_shots"), list) or not batch["batch_shots"]:
        raise TaskSourceError("A nonempty batch_shots list is required")
    total = 0
    for index, shot in enumerate(batch["batch_shots"], 1):
        if not isinstance(shot, dict):
            raise TaskSourceError(f"Shot {index} must be an object")
        frames = shot.get("frames")
        if type(frames) is not int or not 39 <= frames <= 294 or (frames - 5) % 17:
            raise TaskSourceError(f"Shot {index}: frames must be an integer 5+17k, k=2..17")
        duration = shot.get("duration")
        if type(duration) not in (int, float) or not math.isfinite(duration) or abs(duration - frames / 24) > 0.021:
            raise TaskSourceError(f"Shot {index}: duration must agree with frames at 24 fps")
        validate_image_references(shot.get("ref_images"))
        total += frames
    if "total_frames" in batch and (type(batch["total_frames"]) is not int or batch["total_frames"] != total):
        raise TaskSourceError("Declared total_frames does not match the shot frames")


def validate_image_references(refs):
    if not isinstance(refs, list) or not 3 <= len(refs) <= 9:
        raise TaskSourceError("ref_images must contain 3 to 9 ordered image filenames")
    if any(not isinstance(ref, str) or not ref.strip() or not ref.isascii() for ref in refs):
        raise TaskSourceError("Image filenames must be nonempty ASCII strings")
