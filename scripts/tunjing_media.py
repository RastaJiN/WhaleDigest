"""Local media identity and probing shared by postproduction tools."""
import json
import os
import re
import subprocess

def shot_key(value):
    match = re.fullmatch(r"(\d+)([a-z]*)", str(value), re.I)
    if match is None:
        match = re.search(r"shot[-_ ]*(\d+)([a-z]*)(?![a-z0-9])", str(value), re.I)
    return (int(match.group(1)), match.group(2).upper()) if match else None

def find_clip(directories, identity):
    key = shot_key(identity)
    episode = re.search(r"(?:^|[_-])ep(\d+)(?:[_-]|$)", str(identity), re.I)
    def stem(name):
        return os.path.splitext(name)[0].lower().removeprefix("norm_").removesuffix("-audio")
    def same_episode(name):
        if episode is None:
            return True
        other = re.search(r"(?:^|[_-])ep(\d+)(?:[_-]|$)", name, re.I)
        return other is not None and int(other.group(1)) == int(episode.group(1))
    def choose(names, directory):
        groups = {}
        for name in names:
            groups.setdefault(stem(name), []).append(name)
        if len(groups) > 1:
            raise ValueError(f"Multiple output candidates for {identity}: {sorted(names)}")
        if not groups:
            return None
        pair = next(iter(groups.values()))
        audio = [name for name in pair if os.path.splitext(name)[0].lower().endswith("-audio")]
        preferred = audio or pair
        if len(preferred) != 1:
            raise ValueError(f"Multiple output candidates for {identity}: {sorted(names)}")
        return os.path.join(directory, preferred[0])
    for directory in directories:
        if not directory or not os.path.isdir(directory):
            continue
        names = [name for name in os.listdir(directory)
                 if name.lower().endswith((".mp4", ".mov", ".webm"))]
        exact = [name for name in names if stem(name) == str(identity).lower()]
        if exact:
            return choose(exact, directory)
        candidates = [name for name in names
                      if key is not None and shot_key(name) == key
                      and same_episode(name)
                      and not re.search(r"_v\d+$", stem(name), re.I)]
        if candidates:
            return choose(candidates, directory)
    return None


def probe_media(path):
    result = subprocess.run(["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", str(path)], capture_output=True, text=True, encoding="utf-8", errors="replace")
    if result.returncode:
        raise ValueError("Invalid or missing media: " + str(path))
    data = json.loads(result.stdout)
    if not any(s.get("codec_type") == "video" for s in data.get("streams", [])):
        raise ValueError("No video stream: " + str(path))
    return data
