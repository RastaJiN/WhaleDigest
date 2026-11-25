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

if __package__:
    from .whale_blocking import project_file, verify_inputs
    from . import whale_shot_facts
else:
    from whale_blocking import project_file, verify_inputs
    import whale_shot_facts


MANIFEST_NAME = ".whale_project.json"
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
    _verify_export(project_dir, batch)
    return path, batch, hashlib.sha256(raw).hexdigest()



def execution_board_path(project_dir, batch=None):
    """Use the board selected by the batch, never an unbound sibling file."""
    root = Path(project_dir).expanduser().resolve()
    if batch is None:
        if not ((root / MANIFEST_NAME).exists() or (root / LEGACY_BATCH_NAME).exists()):
            return project_file(root, '分镜.md')  # Gate 3 is also usable before compilation.
        _, batch = _read_json(resolve_task_path(root))
    if not isinstance(batch, dict):
        raise TaskSourceError('任务源必须是 JSON 对象')
    _verify_export(root, batch)
    return project_file(root, batch.get('execution_board', '分镜.md'))


def _verify_export(root, batch):
    try:
        verify_inputs(root, batch)
        verify_pose_export(root, batch)
        whale_shot_facts.verify(root, batch)
    except (ValueError, OSError) as exc:
        raise TaskSourceError(str(exc)) from exc


def verify_sourced_dialogue(sequence, rows):
    """Verify ordered turn identity AND words in the actual prompt. A long
    utterance may span requests; reassembly must yield the exact source turn."""
    expected = [(item.get('source_scene'), item['dialogue']) for item in sequence if 'dialogue' in item]
    if not expected: return  # legacy, manually allocated --lines
    n = 0
    parts = []
    for row in rows:
        turn = row.get('dialogue')
        words = re.findall(r'<d>\[Chinese\](.*?)</d>', row['prompt'], re.S)
        if turn is None and not words: continue
        if not isinstance(turn,dict) or n>=len(expected): raise TaskSourceError('Unbound or extra speech')
        scene, original = expected[n]
        source_turn = {k:v for k,v in turn.items() if k not in ('part','part_text')}
        if scene != row.get('source_scene') or original != source_turn:
            raise TaskSourceError('Speech order, scene or named speaker differs from source')
        words_for_part = turn.get('part_text',turn['text'])
        speech = re.findall(r'^SPEECH: ([^\n]*?)<d>\[Chinese\]', row['prompt'], re.M)
        actor = turn['actor']; digit = actor[1:]
        anchor = rf'(?:<Subject {digit}> \({actor}\)|the narrator \(voice {actor}\))(?:, speaking in [^:\n]+)? says(?: in an off-screen voiceover)?: $'
        if len(speech)!=1 or not re.search(anchor,speech[0]) or words != [words_for_part]:
            raise TaskSourceError('Exported SPEECH does not match source actor and verbatim utterance')
        if turn.get('part',0) != len(parts): raise TaskSourceError('Reordered speech continuation')
        parts.append(words_for_part)
        joined = ''.join(parts)
        if not original['text'].startswith(joined): raise TaskSourceError('Rewritten speech')
        if joined == original['text']:
            parts.clear(); n+=1
    if parts or n!=len(expected): raise TaskSourceError('Missing source speech')


def verify_pose_export(project_dir, batch):
    """Legacy batches need no review files. A reviewed project cannot fall back to one."""
    if __package__:
        from .whale_pose_choice import CARD, PLAN, BOARD, prompt_hash
    else:
        from whale_pose_choice import CARD, PLAN, BOARD, prompt_hash
    root = Path(project_dir)
    binding = batch.get('pose_input_hashes')
    if binding is None:
        if ('storyboard_cards' in batch or any((root/k).exists() for k in (CARD,PLAN)) or
                any('action_decision' in shot for shot in batch.get('batch_shots', []))):
            raise TaskSourceError('Unbound pose review; recompile from the confirmed card')
        return
    required = {CARD, PLAN, BOARD, '视频提示词.md'}
    if not isinstance(binding, dict) or not required <= binding.keys() <= required | {'pose_recipes.json'}:
        raise TaskSourceError('Incomplete pose review binding')
    for name, digest in binding.items():
        if (digest is None and name != CARD) or _file_digest(root/name) != digest:
            raise TaskSourceError(f'分镜来源已变更：{name}；请重新编译并验收')
    _, board = _read_json(root/BOARD)
    if (not isinstance(board,dict) or board.get('cards') != batch.get('storyboard_cards') or
            board.get('review_inputs') != {k:v for k,v in binding.items() if k not in (BOARD,'视频提示词.md')}):
        raise TaskSourceError('Exported pose cards differ from the resolved storyboard')
    _, receipt = _read_json(root/PLAN)
    if receipt.get('cast_sha256') != _file_digest(root/'角色映射.json'):
        raise TaskSourceError('源角色映射已更改；请重新编译')
    rows = batch['batch_shots']
    verify_sourced_dialogue(receipt['sequence'], rows)
    if board.get('prompt_sha256') != [prompt_hash(row['prompt']) for row in rows]:
        raise TaskSourceError('Prompt differs from the confirmed storyboard export')
    shots = board.get('shots')
    if not isinstance(shots, list) or len(shots) != len(rows):
        raise TaskSourceError('Storyboard shot count changed')
    for number, (shot, row) in enumerate(zip(shots, rows), 1):
        if not isinstance(shot, dict):
            raise TaskSourceError(f'SHOT-{number:02d}：已决分镜记录无效')
        _check_shot_ids(row, number)
        for field in ('pose', 'action_decision', 'action_steps', 'custom_recipe', 'blocking_state',
                      'source_scene', 'source_line', 'cast', 'dialogue', 'staging_note'):
            if field in shot or field in row:
                if field not in shot:
                    raise TaskSourceError(f'SHOT-{number:02d}：已决分镜没有 {field}')
                _check_fact(row, field, shot[field], number)
        for source, field in (('cam', 'camera_motion'), ('size', 'shot_size'),
                              ('dur', 'duration'), ('frames', 'frames')):
            if source in shot:
                _check_fact(row, field, shot[source], number)


def _check_fact(row, field, expected, number):
    # Compare JSON values, including nested types (True is not source shot 1).
    if field not in row or json.dumps(row[field], sort_keys=True) != json.dumps(expected, sort_keys=True):
        raise TaskSourceError(f'SHOT-{number:02d}：批量任务 {field} 与分镜事实不符；请重新编译')


def _check_shot_ids(row, number):
    _check_fact(row, 'id', f'shot_{number}', number)
    _check_fact(row, 'shot_id', f'shot_{number:02d}', number)


def source_record(project_dir):
    """Bind exact task bytes, upstream inputs, manifest selection and validators."""
    path, _, digest = load_task_source(project_dir)
    root = Path(project_dir).resolve()
    return {"task_path": str(path), "task_sha256": digest,
            "project_inputs": _input_fingerprints(root, include_manifest=True),
            "validation_sources": _validation_fingerprints()}



def refresh_status(project_dir, status):
    """Revoke the earliest stage whose inputs or validation rules have changed."""
    if not isinstance(status, dict):
        raise TaskSourceError("Gate status must be a JSON object")
    passed = status.get("passed_steps", [])
    if not isinstance(passed, list):
        passed = []
    passed = sorted({step for step in passed if type(step) is int and 1 <= step <= 6})
    status["passed_steps"] = passed
    sources = status.get("gate_sources", {})
    if not isinstance(sources, dict):
        sources = {}
    sources = {str(key): value for key, value in sources.items() if str(key).isdigit() and 1 <= int(key) <= 6}
    status["gate_sources"] = sources
    try:
        current_step = int(status.get("current_step", 1))
    except (TypeError, ValueError):
        current_step = 1
    current_step = max(1, min(current_step, 6))
    status["current_step"] = current_step
    earliest = None
    for step in (1, 2, 3, 4, 5):
        if step not in passed:
            if step < current_step:
                earliest = step
                break
            continue
        try:
            current = gate_evidence(project_dir, step)
            if sources.get(str(step)) != current:
                earliest = step
                break
        except (TaskSourceError, OSError, ValueError) as exc:
            status["source_error"] = str(exc)
            earliest = step
            break
    if earliest is not None:
        status["passed_steps"] = [step for step in passed if step < earliest]
        status["current_step"] = min(current_step, earliest)
        status["gate_sources"] = {key: value for key, value in sources.items() if int(key) < earliest}
    else:
        status.pop("source_error", None)
    return status



def require_source_audit(project_dir, status):
    """Require current, bound evidence for all five prerequisite gates."""
    if not isinstance(status, dict):
        raise TaskSourceError("Gate status must be a JSON object")
    passed, sources = status.get("passed_steps", []), status.get("gate_sources", {})
    if not isinstance(passed, list) or not isinstance(sources, dict):
        raise TaskSourceError("Invalid task audit status")
    if not all(step in passed for step in (1, 2, 3, 4, 5)):
        raise TaskSourceError("Project gates 1 through 5 must all have passed")
    for step in (1, 2, 3, 4, 5):
        if sources.get(str(step)) != gate_evidence(project_dir, step):
            raise TaskSourceError(f"Task audit gate {step} is stale or unbound; rerun that gate")
    return source_record(project_dir)



def validate_batch_metadata(batch):
    """Validate the same frame, duration, aspect and image contract at every gate."""
    if not isinstance(batch, dict) or not isinstance(batch.get("batch_shots"), list) or not batch["batch_shots"]:
        raise TaskSourceError("A nonempty batch_shots list is required")
    if "fps" in batch and (type(batch["fps"]) not in (int, float) or batch["fps"] != 24):
        raise TaskSourceError("H3 task fps must be 24")
    # 画幅硬契约：禁止接手旧任务时连画幅都未确认就悄悄按默认 9:16 渲染
    raw_aspect = batch.get("aspect")
    valid_aspects = {"9:16", "16:9", "1:1", "9:16 (portrait widescreen)", "16:9 (widescreen)", "1:1 (square)"}
    if not isinstance(raw_aspect, str) or not raw_aspect.strip():
        shot_aspects = [s.get("aspect") for s in batch["batch_shots"] if isinstance(s, dict)]
        if not all(isinstance(a, str) and a.strip().lower() in valid_aspects for a in shot_aspects):
            raise TaskSourceError(
                "未明确锁定画幅（aspect 缺失）！必须在批量任务顶层显式声明 aspect（'16:9' / '9:16' / '1:1'），"
                "严禁未确认画幅直接套用默认竖屏渲染。"
            )
    elif raw_aspect.strip().lower() not in valid_aspects:
        raise TaskSourceError(f"Unsupported batch aspect: {raw_aspect!r}; must be '16:9', '9:16', or '1:1'")
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
        refs = shot.get("ref_images")
        validate_image_references(refs)
        declared = shot.get("references")
        if declared is not None and (not isinstance(declared, list) or len(declared) != len(refs) or any(not isinstance(item, str) or not item.strip() for item in declared)):
            raise TaskSourceError(f"Shot {index}: references must correspond to the ordered ref_images slots")
        prompt = shot.get("prompt", "")
        if not isinstance(prompt, str):
            raise TaskSourceError(f"Shot {index}: prompt must be a string")
        # Quoted speech cannot invent image bindings.
        positive = re.sub(r"<d>.*?</d>", "", prompt, flags=re.DOTALL | re.IGNORECASE)
        pictures = [int(value) for value in re.findall(r"<Picture\s+(\d+)>", positive)]
        if any(not 1 <= value <= len(refs) for value in pictures):
            raise TaskSourceError(f"Shot {index}: prompt Picture reference has no corresponding ref_images slot")
        total += frames
    if "total_frames" in batch and (type(batch["total_frames"]) is not int or batch["total_frames"] != total):
        raise TaskSourceError("Declared total_frames does not match the shot frames")
    if "total_duration" in batch:
        duration = batch["total_duration"]
        if type(duration) not in (int, float) or not math.isfinite(duration) or abs(duration - total / 24) > 0.021:
            raise TaskSourceError("Declared total_duration does not match total_frames at 24 fps")



def resolve_workflow_path(project_dir, explicit_workflow=None):
    """Resolve the user-specified ComfyUI workflow JSON.

    Priority: explicit --workflow > .whale_project.json['workflow'] > batch['workflow_template']
    (only if it points to an existing custom file) > None (caller decides fallback or error).
    Never silently invent a brand-new workflow graph.
    """
    if explicit_workflow:
        p = Path(explicit_workflow).expanduser().resolve()
        if not p.is_file():
            raise TaskSourceError(f"指定的 ComfyUI 工作流文件不存在: {p}")
        return p
    root = Path(project_dir).expanduser().resolve()
    manifest = root / MANIFEST_NAME
    if manifest.is_file():
        _, cfg = _read_json(manifest)
        if isinstance(cfg, dict) and cfg.get("workflow"):
            wf_raw = str(cfg["workflow"]).strip()
            wf_p = Path(wf_raw)
            if not wf_p.is_absolute():
                wf_p = (root / wf_p).resolve()
            if not wf_p.is_file():
                raise TaskSourceError(f".whale_project.json 中指定的工作流文件不存在: {wf_p}")
            return wf_p
    return None


def validate_project_assets(project_dir, batch):
    """Verify every shot's ref_images physically exist and are decodable inside 00_资产/.

    Prevents gatekeeper from passing phantom placeholder names like female_nude.png / scene_main.png
    when the actual asset directory holds differently named files or is empty.
    """
    assets = (Path(project_dir).resolve() / "00_资产").resolve()
    if not assets.is_dir():
        raise TaskSourceError("缺少 '00_资产/' 资产目录，无法验证参考图绑定")
    referenced = []
    seen = set()
    for idx, shot in enumerate(batch.get("batch_shots", []), 1):
        for name in shot.get("ref_images") or []:
            if name not in seen:
                seen.add(name)
                referenced.append((idx, name))
    missing = []
    for idx, name in referenced:
        p = (assets / name).resolve()
        try:
            p.relative_to(assets)
        except ValueError as exc:
            raise TaskSourceError(f"镜头 {idx} 参考图 '{name}' 越界，不在 00_资产/ 目录内") from exc
        if not p.is_file():
            missing.append(f"镜头{idx}:{name}")
        else:
            validate_asset_image(p)
    if missing:
        actual_files = sorted(f.name for f in assets.iterdir() if f.is_file())
        raise TaskSourceError(
            f"参考图物理缺失（未与 00_资产/ 真实绑定）: {missing[:6]}；"
            f"当前 00_资产/ 实有文件: {actual_files[:12]}"
        )


def validate_image_references(refs):
    if not isinstance(refs, list) or not 1 <= len(refs) <= 9:
        raise TaskSourceError("ref_images must contain 1 to 9 ordered image filenames")
    for ref in refs:
        if not isinstance(ref, str) or not ref.strip() or ref != ref.strip() or not ref.isascii():
            raise TaskSourceError("Image filenames must be nonempty, trimmed ASCII strings")
        win = PureWindowsPath(ref)
        normalized = ref.replace("\\", "/")
        if win.drive or win.root or normalized.startswith("/") or any(part in ("", ".", "..") for part in normalized.split("/")):
            raise TaskSourceError("Image references must be relative filenames without path traversal")


_VALIDATOR_NAMES = ("whale_task_source.py", "whale_compiler.py", "whale_gatekeeper.py",
                    "whale_diff_audit.py", "whale_audio_contract.py", "whale_core.py", "whale_blocking.py",
                    "whale_pose_choice.py", "whale_prose.py", "whale_scene.py", "whale_shot_facts.py",
                    "whale_h3_prompt.py")


def _file_digest(path):
    if not path.is_file():
        return None
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _validation_fingerprints():
    base = Path(__file__).resolve().parent
    return {name: _file_digest(base / name) for name in _VALIDATOR_NAMES}


def _input_fingerprints(root, include_manifest=False):
    records = {"剧本.md": _file_digest(root / "剧本.md"), "分镜.md": _file_digest(root / "分镜.md")}
    assets = root / "00_资产"
    records["00_资产/"] = "directory" if assets.is_dir() else None
    if assets.is_dir():
        for path in sorted(assets.rglob("*")):
            if path.is_file():
                records[path.relative_to(root).as_posix()] = _file_digest(path)
    if include_manifest:
        records[MANIFEST_NAME] = _file_digest(root / MANIFEST_NAME)
    return records


def stage_record(project_dir, step):
    root = Path(project_dir).resolve()
    inputs = _input_fingerprints(root)
    if step == 1:
        inputs = {key: value for key, value in inputs.items() if key.startswith("00_资产/")}
    elif step == 2:
        inputs = {"剧本.md": inputs["剧本.md"]}
    elif step == 3:
        board = execution_board_path(root)
        inputs = {"分镜.md": inputs["分镜.md"], board.name: _file_digest(board)}
    else:
        raise TaskSourceError("stage_record expects a gate from 1 to 3")
    return {"stage": step, "project_inputs": inputs, "validation_sources": _validation_fingerprints()}


def gate_evidence(project_dir, step):
    if step in (1, 2, 3):
        return stage_record(project_dir, step)
    current = source_record(project_dir)
    if step == 5:
        report = Path(project_dir).resolve() / "审查" / "生成前终审报告.md"
        digest = _file_digest(report)
        if digest is None:
            raise TaskSourceError("Gate 5 audit report is missing; run gate 5 again")
        current = dict(current, audit_report_path=str(report), audit_report_sha256=digest)
    return current


def validate_asset_image(path):
    """Decode PNG scanlines using stdlib; use Pillow for other supported images."""
    import struct
    import zlib
    path = Path(path)
    if not path.is_file() or path.stat().st_size == 0:
        raise TaskSourceError(f"Asset image is missing or empty: {path.name}")
    raw = path.read_bytes()
    if not raw.startswith(b"\x89PNG\r\n\x1a\n"):
        try:
            from PIL import Image
        except ImportError as exc:
            raise TaskSourceError(f"Cannot decode asset {path.name}; use a valid PNG or install Pillow for this image format") from exc
        try:
            with Image.open(path) as image:
                image.load()
                if image.width <= 0 or image.height <= 0:
                    raise ValueError("invalid image size")
        except Exception as exc:
            raise TaskSourceError(f"Asset is not a decodable image: {path.name}: {exc}") from exc
        return
    offset, header, data, ended, palette = 8, None, bytearray(), False, False
    while offset < len(raw):
        if offset + 12 > len(raw):
            raise TaskSourceError(f"Truncated PNG chunk: {path.name}")
        size = struct.unpack(">I", raw[offset:offset + 4])[0]
        kind = raw[offset + 4:offset + 8]
        payload = raw[offset + 8:offset + 8 + size]
        end = offset + 12 + size
        if end > len(raw) or len(payload) != size:
            raise TaskSourceError(f"Truncated PNG payload: {path.name}")
        expected_crc = struct.unpack(">I", raw[offset + 8 + size:end])[0]
        if zlib.crc32(kind + payload) & 0xffffffff != expected_crc:
            raise TaskSourceError(f"Invalid PNG checksum: {path.name}")
        if header is None and kind != b"IHDR":
            raise TaskSourceError(f"PNG does not start with IHDR: {path.name}")
        if kind == b"IHDR":
            if header is not None or size != 13:
                raise TaskSourceError(f"Invalid PNG IHDR: {path.name}")
            header = struct.unpack(">IIBBBBB", payload)
        elif kind == b"IDAT":
            data.extend(payload)
        elif kind == b"PLTE":
            palette = size > 0 and size % 3 == 0 and size <= 768
        elif kind == b"IEND":
            if size or end != len(raw):
                raise TaskSourceError(f"Invalid PNG end marker: {path.name}")
            ended = True
            break
        offset = end
    if not ended or header is None or not data:
        raise TaskSourceError(f"Incomplete PNG image: {path.name}")
    width, height, depth, color, compression, filtering, interlace = header
    depths = {0: (1, 2, 4, 8, 16), 2: (8, 16), 3: (1, 2, 4, 8), 4: (8, 16), 6: (8, 16)}
    if width <= 0 or height <= 0 or color not in depths or depth not in depths[color] or compression or filtering or interlace not in (0, 1) or (color == 3 and not palette):
        raise TaskSourceError(f"Unsupported or invalid PNG header: {path.name}")
    channels = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}[color]
    passes = [(0, 0, 1, 1)] if not interlace else [(0, 0, 8, 8), (4, 0, 8, 8), (0, 4, 4, 8), (2, 0, 4, 4), (0, 2, 2, 4), (1, 0, 2, 2), (0, 1, 1, 2)]
    layouts = []
    for x, y, dx, dy in passes:
        pw = max(0, (width - x + dx - 1) // dx)
        ph = max(0, (height - y + dy - 1) // dy)
        if pw and ph:
            layouts.append(((pw * channels * depth + 7) // 8 + 1, ph))
    expected = sum(stride * count for stride, count in layouts)
    if expected > 268435456:
        raise TaskSourceError(f"PNG decoded size exceeds validation limit: {path.name}")
    try:
        decoder = zlib.decompressobj()
        decoded = decoder.decompress(bytes(data), expected + 1)
    except zlib.error as exc:
        raise TaskSourceError(f"Invalid PNG pixel stream: {path.name}") from exc
    if len(decoded) != expected or not decoder.eof or decoder.unconsumed_tail or decoder.unused_data:
        raise TaskSourceError(f"PNG pixel data length is invalid: {path.name}")
    offset = 0
    for stride, count in layouts:
        for _ in range(count):
            if decoded[offset] > 4:
                raise TaskSourceError(f"Invalid PNG row filter: {path.name}")
            offset += stride
