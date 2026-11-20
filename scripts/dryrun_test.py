"""Offline neutral pipeline regression; no dispatch or render requests."""
from pathlib import Path
import json
import struct
import sys
import tempfile
import zlib
import tunjing_scene as scene
import tunjing_gatekeeper as gate
from tunjing_compiler import lint_tunjing_document


def png_bytes():
    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xffffffff)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 2, 2, 8, 2, 0, 0, 0)) + chunk(b"IDAT", zlib.compress((b"\x00" + b"\x80\x80\x80" * 2) * 2)) + chunk(b"IEND", b"")


def run_dryrun(target_dir):
    root = Path(target_dir)
    root.mkdir(parents=True, exist_ok=True)
    for aspect in ("9:16", "16:9"):
        project = root / aspect.replace(":", "x")
        project.mkdir(exist_ok=True)
        assets = project / "00_资产"
        assets.mkdir(exist_ok=True)
        for name in ("female_ref.png", "male_ref.png", "scene_main.png"):
            (assets / name).write_bytes(png_bytes())
        (project / "剧本.md").write_text("# Neutral regression\n## 第一幕\nenv_establish establishes the office.\n## 第二幕\nblocking_2s walks to a desk; prop_insert shows a document.\n男主：<d>[Chinese]会议开始了。</d>\n## 第三幕\noutro_solo closes the meeting.\n", encoding="utf-8")
        shots, actual = scene.build_scene(["env_establish", "blocking_2s", "prop_insert", "outro_solo"], 24.0, scene.load_poses())
        _, prompt_path, _ = scene.save_project_artifacts(str(project), shots, actual, 24.0, lines="2:男子A:会议开始了。", idea="office meeting", scene="office", pose_names="env_establish,blocking_2s,prop_insert,outro_solo", aspect=aspect)
        assert any(shot["size"] == "wide" for shot in shots), "wide regression fixture missing"
        prompt_text = Path(prompt_path).read_text(encoding="utf-8")
        assert "SPEECH:" in prompt_text and "会议开始了。" in prompt_text
        errors, _ = lint_tunjing_document(prompt_text)
        assert not errors, errors
        for step in range(1, 7):
            assert gate.check_gate(str(project), step), f"{aspect} gate {step} failed"
        print(f"PASS aspect={aspect} shots={len(shots)} wide=True gates=1..6 offline=True")
    return str(root.resolve())


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    run_dryrun(sys.argv[1] if len(sys.argv) > 1 else tempfile.mkdtemp(prefix="tunjing_neutral_"))
