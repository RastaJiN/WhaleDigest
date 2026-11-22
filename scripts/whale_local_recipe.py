"""Explicit project-local staging recipes. No matrix mutation or fuzzy lookup."""
import json
import re
from pathlib import Path


def resolve(chain, poses, project):
    missing = set(chain) - poses.keys()
    if not missing:
        return {}
    path = Path(project) / 'pose_recipes.json'
    if not project or not path.is_file() or path.resolve().parent != Path(project).resolve():
        raise ValueError(f'Unknown pose(s) {sorted(missing)}; supply project-local pose_recipes.json')
    data = json.loads(path.read_text(encoding='utf-8-sig'))
    result = {}
    for pid in missing:
        recipe = data.get(pid) if isinstance(data, dict) else None
        if not re.fullmatch('[a-z][a-z0-9_]{0,63}', pid) or not isinstance(recipe, dict) or set(recipe) != {'orientation','support','beats','framing'}:
            raise ValueError(f'{pid}: expected orientation, support, beats and framing')
        beats, frame = recipe['beats'], recipe['framing']
        if not isinstance(beats,list) or not 2 <= len(beats) <= 4:
            raise ValueError(f'{pid}: expected 2-4 ordered visible beats')
        parts = [recipe['orientation'],recipe['support'],*beats]
        if not all(isinstance(x,str) and re.fullmatch(r"[A-Za-z0-9 ,.'()-]{1,240}",x) and re.search('[A-Za-z]',x) for x in parts):
            raise ValueError(f'{pid}: use short single-line English visual descriptions')
        if not isinstance(frame,dict) or set(frame) != {'size','cam'} or frame['size'] not in ('wide','mcu') or frame['cam'] not in ('static_side','static_front'):
            raise ValueError(f'{pid}: invalid two-subject framing')
        result[pid] = (' '.join(x.strip() for x in parts), frame['size'], frame['cam'])
    return result
