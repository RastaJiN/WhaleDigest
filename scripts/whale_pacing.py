"""Validated per-shot actor and ordered pace directives for prompt export."""
from __future__ import annotations
import json

PACE = {"slow": "slower controlled timing", "steady": "steady timing", "fast": "faster controlled timing"}
ACTORS = {"S1", "S2"}
INCOMPATIBLE = {"env_establish", "empty_cut", "corridor_cut", "prop_insert", "cut_insert", "blocking_2s", "srs_male", "srs_female", "outro_solo"}

def _actor(value):
    if not isinstance(value, str) or value.upper() not in ACTORS:
        raise ValueError("actor must be exactly S1 or S2")
    return value.upper()

def _pace(value):
    if not isinstance(value, str) or value.lower() not in PACE:
        raise ValueError("pace must be slow, steady, or fast")
    return value.lower()

def parse_overrides(raw):
    """Parse [{"shot": 1, "actor": "S1", "pace": ["slow", "fast"]}]."""
    if raw is None:
        return {}
    try:
        rows = json.loads(raw) if isinstance(raw, str) else raw
    except (TypeError, json.JSONDecodeError) as exc:
        raise ValueError("pace overrides must be a JSON list") from exc
    if not isinstance(rows, list):
        raise ValueError("pace overrides must be a JSON list")
    out = {}
    for row in rows:
        if not isinstance(row, dict) or isinstance(row.get("shot"), bool):
            raise ValueError("each override needs integer shot, actor, and pace list")
        shot = row.get("shot")
        if not isinstance(shot, int) or shot < 1 or shot in out:
            raise ValueError("shot must be a unique positive integer")
        if set(row) == {"shot", "driver"}:
            out[shot] = _pace(row["driver"])
            continue
        if set(row) != {"shot", "actor", "pace"}:
            raise ValueError("expected shot, actor and pace")
        actor = _actor(row.get("actor"))
        pace = row.get("pace")
        if not isinstance(pace, list) or not pace:
            raise ValueError("pace must be a non-empty ordered list")
        out[shot] = {"actor": actor, "pace": [_pace(x) for x in pace]}
    return out

# Both partners can shift weight independently without changing these supports.
SUPPORTED = {"missionary": "<Subject 1> remains supine beneath <Subject 2>",
             "cowgirl": "<Subject 1> remains seated above <Subject 2>",
             "doggy": "<Subject 2> remains behind <Subject 1>"}


def apply(shots, driver=None, overrides=None, *, actor=None, pace=None):
    overrides = overrides or {}
    if any(type(i) is not int or not 1 <= i <= len(shots) for i in overrides):
        raise ValueError("override shot outside storyboard")
    if pace is not None and not actor:
        raise ValueError("--pace requires --motion-actor")
    default = {"actor": _actor(actor), "pace": pace or ["steady"]} if actor else None
    result = []
    matched = False
    for i, shot in enumerate(shots, 1):
        spec = overrides.get(i, default or driver)
        pose = shot.get("pose")
        if pose not in SUPPORTED or shot.get("blocking_state", {}).get("action"):
            if i in overrides:
                raise ValueError(f"shot {i}: incompatible pose or adopted action")
            spec = None
        item = dict(shot)
        if isinstance(spec, str):  # Legacy tempo-only option; initiator unchanged.
            item["pace_instruction"] = "Pace driver: " + PACE[_pace(spec)] + "."
        elif spec is not None:
            who = _actor(spec['actor'])
            stages = spec['pace']
            if not isinstance(stages, list) or not stages:
                raise ValueError("pace must be a nonempty list")
            leader = int(who[1])
            beats = [f"Phase {n}: <Subject {leader}> leads the weight shift at a {_pace(speed)} tempo"
                     for n, speed in enumerate(stages, 1)]
            action = (SUPPORTED[pose] + f". <Subject {3-leader}> follows each shift while maintaining support. "
                      + "; then ".join(beats) + ".")
            item.update(text=action, text_en=action, motion_override=True)
        matched |= spec is not None
        result.append(item)
    if (default or driver) and not matched:
        raise ValueError("no compatible shots")
    return result


def prompt_clause(shot):
    return shot.get("pace_instruction", "")
