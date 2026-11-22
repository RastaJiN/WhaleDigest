"""Validate audio metadata without editing prompts or building workflows.

Shot fields override batch fields individually.  The returned dictionary is new;
neither input is modified.  Reference audio metadata is representable, but actual
workflow reference routing is deliberately rejected until it is implemented.
"""

from collections.abc import Mapping


NATIVE_AUDIO = "H3_native_audio"
REFERENCE_AUDIO = "H3_reference_audio"
_FIELDS = ("audio_mode", "audio_reference_required", "ref_audios")


def _validate_fields(value, label):
    if not isinstance(value, Mapping):
        raise ValueError(f"{label} must be an object")
    if "audio_mode" in value:
        mode = value["audio_mode"]
        if not isinstance(mode, str) or mode not in (NATIVE_AUDIO, REFERENCE_AUDIO):
            raise ValueError(f"{label}.audio_mode must be {NATIVE_AUDIO!r} or {REFERENCE_AUDIO!r}")
    if "audio_reference_required" in value and type(value["audio_reference_required"]) is not bool:
        raise ValueError(f"{label}.audio_reference_required must be a boolean")
    if "ref_audios" in value:
        refs = value["ref_audios"]
        if not isinstance(refs, list):
            raise ValueError(f"{label}.ref_audios must be a list")
        if any(not isinstance(ref, str) or not ref.strip() or ref != ref.strip() for ref in refs):
            raise ValueError(f"{label}.ref_audios must contain nonempty, whitespace-trimmed strings")


def resolve_audio_contract(shot, batch=None):
    """Return validated ``audio_mode``, ``audio_reference_required``, ``ref_audios``.

    Missing metadata means native audio only when references are empty.  Legacy
    nonempty references without a mode require explicit migration.  A reference
    mode must explicitly resolve to ``audio_reference_required=True`` and a
    nonempty list; filenames are never invented or inferred.
    """
    _validate_fields(shot, "shot")
    if batch is None:
        batch = {}
    _validate_fields(batch, "batch")
    merged = {key: shot[key] if key in shot else batch[key]
              for key in _FIELDS if key in shot or key in batch}
    refs = merged.get("ref_audios", [])
    required = merged.get("audio_reference_required", False)
    if "audio_mode" not in merged and refs:
        raise ValueError("Legacy ref_audios without audio_mode require explicit migration; no mode was inferred")
    mode = merged.get("audio_mode", NATIVE_AUDIO)
    if mode == NATIVE_AUDIO:
        if required or refs:
            raise ValueError("H3_native_audio requires audio_reference_required=False and empty ref_audios")
    elif not required or not refs:
        raise ValueError("H3_reference_audio requires audio_reference_required=True and nonempty ref_audios")
    return {"audio_mode": mode, "audio_reference_required": required, "ref_audios": list(refs)}


def _bound_audio_inputs(inputs, path):
    for key, value in inputs.items():
        leaf = str(key).rsplit(".", 1)[-1]
        is_ref = leaf in ("ref_audio", "ref_audios") or leaf.startswith("ref_audio_")
        if is_ref and value is not None:
            yield f"{path}.{key}"
        elif isinstance(value, Mapping):
            yield from _bound_audio_inputs(value, f"{path}.{key}")


def validate_workflow_audio(workflow, contract):
    """Validate API workflow input bindings, returning ``None`` on success.

    Native audio allows omitted or null reference ports.  Any other value on a
    reference port is rejected, including empty containers.  Unconnected audio
    loader nodes and ordinary output audio links do not declare H3 references.
    This function never disconnects ports or otherwise changes the workflow.
    """
    resolved = resolve_audio_contract(contract)
    if resolved["audio_mode"] == REFERENCE_AUDIO:
        raise ValueError("Reference audio workflow routing is not supported; binding cannot be claimed")
    if not isinstance(workflow, Mapping) or not workflow:
        raise ValueError("workflow must be a nonempty API workflow object")
    for node_id, node in workflow.items():
        if not isinstance(node, Mapping):
            raise ValueError(f"workflow node {node_id!r} must be an object")
        inputs = node.get("inputs", {})
        if not isinstance(inputs, Mapping):
            raise ValueError(f"workflow node {node_id!r}.inputs must be an object")
        bound = list(_bound_audio_inputs(inputs, str(node_id)))
        if bound:
            raise ValueError("H3_native_audio has unexpected reference audio input bindings: " + ", ".join(bound))
