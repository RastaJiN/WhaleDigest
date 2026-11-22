"""Offline, synthetic tests for local score adoption and mixing (stdlib only)."""
import array
from concurrent.futures import ThreadPoolExecutor
import json
import math
import os
import re
import struct
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import wave
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
CLI = SCRIPTS / "whale_post_music.py"
import whale_post_music as music


def tone(path, hz, ms=1200, rate=16000):
    with wave.open(str(path), "wb") as out:
        out.setparams((1, 2, rate, 0, "NONE", ""))
        out.writeframes(b"".join(struct.pack("<h", round(6000 * math.sin(2 * math.pi * hz * i / rate)))
                                 for i in range(rate * ms // 1000)))


def media(tool, *args):
    p = subprocess.run([tool, "-v", "error", *map(str, args)], capture_output=True, timeout=45,
                       stdin=subprocess.DEVNULL, env={k: v for k, v in os.environ.items() if k != "FFREPORT"})
    if p.returncode:
        raise AssertionError(p.stderr.decode(errors="replace"))
    return p.stdout


def samples(path):
    data = array.array("h", media("ffmpeg", "-nostdin", "-i", path, "-map", "0:a:0", "-ac", 1,
                                 "-ar", 48000, "-f", "s16le", "pipe:1"))
    if sys.byteorder != "little":
        data.byteswap()
    return data


def amplitude(data, hz, start_ms, end_ms):
    """Amplitude at one frequency, measured on decoded PCM (no numpy)."""
    window = data[start_ms * 48:end_ms * 48]
    step = math.tau * hz / 48000
    a = sum(s * math.cos(i * step) for i, s in enumerate(window))
    b = sum(s * math.sin(i * step) for i, s in enumerate(window))
    return 2 * math.hypot(a, b) / len(window)


def picture_packets(path):
    return json.loads(media("ffprobe", "-select_streams", "v:0", "-show_packets", "-show_data_hash", "sha256",
                            "-show_entries", "packet=pts_time,dts_time,duration_time,data_hash", "-of", "json", path))


class LocalMusic(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix="post-music-test-", dir=SCRIPTS.parent.parent)
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name) / "项目 A"
        self.audio = self.root / "audio"
        self.audio.mkdir(parents=True)
        self.plan = self.root / "后期单.json"
        self.items = [dict(id="MUSIC-01", file="audio/score.wav", start_ms=300, end_ms=850, gain_db=-6)]
        tone(self.audio / "score.wav", 880)
        self.write_plan()

    def write_plan(self, **changes):
        plan = dict(schema="tunjing-post-v1", music=self.items)
        plan.update(changes)
        self.plan.write_text(json.dumps(plan, ensure_ascii=False), encoding="utf-8-sig")

    def cli(self, command, *args):
        return subprocess.run([sys.executable, "-B", str(CLI), command, str(self.root), *args],
                              capture_output=True, text=True, encoding="utf-8", timeout=45,
                              env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1", "PYTHONUTF8": "1"})

    def preview(self):
        p = self.cli("preview")
        self.assertEqual(p.returncode, 0, p.stderr)
        return p.stdout

    def fingerprints(self):
        return dict(re.findall(r"^(MUSIC-[A-Z0-9_-]+)\s+[^\n]*SHA256=([0-9a-f]{64})\b", self.preview(), re.M))

    def confirm(self, ident, sha):
        p = self.cli("confirm", "--id", ident, "--sha256", sha)
        self.assertEqual(p.returncode, 0, p.stderr)

    def add_second(self):
        self.items.append(dict(self.items[0], id="MUSIC-02", file="audio/second.wav", start_ms=900, end_ms=1100))
        tone(self.audio / "second.wav", 660)
        self.write_plan()

    def clip(self, sound=False, offset=0):
        path = self.root / "原片.mp4"
        args = ["-f", "lavfi", "-i", "color=c=teal:s=96x64:r=25:d=1.2"]
        if sound:
            args += ["-itsoffset", str(offset), "-f", "lavfi", "-i", "sine=f=440:r=44100:d=1", "-c:a", "aac"]
        media("ffmpeg", "-nostdin", *args, "-c:v", "libx264", "-threads", "1", "-pix_fmt", "yuv420p", path)
        return path

    def approved(self):
        for ident, sha in self.fingerprints().items():
            self.confirm(ident, sha)
        return music.prepare_music(self.root, self.items, 1200)

    def test_silent_picture_gets_music_only_within_exact_sample_window_and_no_video_shift(self):
        source, out = self.clip(), self.root / "混音.mp4"
        music.mix_music(source, out, self.approved(), 1200)
        data = samples(out)
        self.assertEqual(len(data), 1200 * 48)
        self.assertEqual(max(map(abs, data[:300 * 48])), 0)
        self.assertGreater(amplitude(data, 880, 350, 750), 1500)
        self.assertEqual(max(map(abs, data[850 * 48:])), 0)
        self.assertEqual(picture_packets(out), picture_packets(source))
        streams = json.loads(media("ffprobe", "-show_streams", "-of", "json", out))["streams"]
        audio, = [s for s in streams if s["codec_type"] == "audio"]
        self.assertEqual((audio["channels"], audio["sample_rate"]), (2, "48000"))

    def test_original_tone_keeps_level_and_timing_gain_is_applied_only_to_music(self):
        source, out = self.clip(sound=True), self.root / "含原声.mp4"
        music.mix_music(source, out, self.approved(), 1200)
        orig, mixed = samples(source), samples(out)
        for a, b in [(50, 250), (400, 700), (875, 975)]:
            self.assertAlmostEqual(amplitude(mixed, 440, a, b) / amplitude(orig, 440, a, b), 1, delta=.02)
        gain = amplitude(mixed, 880, 400, 700) / amplitude(samples(self.audio / "score.wav"), 880, 100, 400)
        self.assertAlmostEqual(gain, 10 ** (-6 / 20), delta=.02)
        self.assertEqual(len(mixed), 1200 * 48)  # short original padded, picture unchanged
        self.assertEqual(max(map(abs, mixed[1100 * 48:])), 0)
        self.assertEqual(picture_packets(out), picture_packets(source))

    def test_overlaps_add_at_requested_levels_without_ducking(self):
        self.add_second()
        self.items[1].update(start_ms=600, end_ms=1050, gain_db=-12)
        self.write_plan()
        source, out = self.clip(), self.root / "两条.mp4"
        music.mix_music(source, out, self.approved(), 1200)
        mixed = samples(out)
        for hz, single in [(880, (400, 550)), (660, (875, 1025))]:
            level = amplitude(mixed, hz, *single)
            self.assertGreater(level, 800)
            self.assertAlmostEqual(amplitude(mixed, hz, 650, 800) / level, 1, delta=.015)

    def test_mix_refetches_receipt_spec_and_audio_after_prepare_and_never_uses_preview_as_ticket(self):
        src, out = self.clip(), self.root / "不应存在.mp4"
        cues = music.prepare_music(self.root, self.items, 1200, require_confirmed=False)
        cues[0]["confirmed"] = True  # UI state is not authority
        with self.assertRaisesRegex(ValueError, "MUSIC-01"):
            music.mix_music(src, out, cues, 1200)
        approved = self.approved()
        self.items[0]["end_ms"] -= 1
        self.write_plan()
        with self.assertRaisesRegex(ValueError, "MUSIC-01"):
            music.mix_music(src, out, approved, 1200)
        self.items[0]["end_ms"] += 1
        self.write_plan()
        tone(self.audio / "score.wav", 990)
        with self.assertRaisesRegex(ValueError, "MUSIC-01"):
            music.mix_music(src, out, approved, 1200)
        self.assertFalse(out.exists())

    def test_confirm_only_named_item_preserve_other_valid_tickets_prune_stale_ones(self):
        self.add_second()
        h3 = self.root / ".whale_status.json"
        before = self.fingerprints()
        h3.write_text(json.dumps(before), encoding="utf-8")  # not a music authority
        self.confirm("MUSIC-01", before["MUSIC-01"])
        with self.assertRaisesRegex(ValueError, "MUSIC-02"):
            music.prepare_music(self.root, self.items, 1200)
        self.confirm("MUSIC-02", before["MUSIC-02"])
        orig = music.prepare_music(self.root, self.items, 1200)
        self.assertEqual([x["sha256"] for x in orig], list(before.values()))
        (self.root / "无关镜头.mp4").write_bytes(b"other video bytes")
        self.write_plan(music=list(reversed(self.items)), subtitles=[{"text": "改无关字幕"}])
        self.assertEqual(before, self.fingerprints())
        self.assertEqual(orig, music.prepare_music(self.root, self.items, 1400))

        self.items[0]["gain_db"] = -9
        self.write_plan()
        after = self.fingerprints()
        self.assertNotEqual(before["MUSIC-01"], after["MUSIC-01"])
        self.assertEqual(before["MUSIC-02"], after["MUSIC-02"])
        self.confirm("MUSIC-02", after["MUSIC-02"])  # reconcile stale 01, must not adopt it
        self.items[0]["gain_db"] = -6
        self.write_plan()
        with self.assertRaisesRegex(ValueError, "MUSIC-01"):
            music.prepare_music(self.root, self.items, 1200)
        self.assertEqual(json.loads(h3.read_text(encoding="utf-8")), before)

    def test_confirm_refuses_wrong_id_short_or_stale_sha_without_writing(self):
        self.add_second()
        shas = self.fingerprints()
        self.confirm("MUSIC-02", shas["MUSIC-02"])
        path = self.audio / "score.wav"
        orig_stat = path.stat()
        tone(path, 990)  # different bytes, same file name, length and timestamp
        os.utime(path, ns=(orig_stat.st_atime_ns, orig_stat.st_mtime_ns))
        changed = self.fingerprints()
        self.assertNotEqual(changed["MUSIC-01"], shas["MUSIC-01"])
        self.assertEqual(changed["MUSIC-02"], shas["MUSIC-02"])
        before = {p: p.read_bytes() for p in self.root.iterdir() if p.is_file()}
        for ident, sha in [("MUSIC-01", shas["MUSIC-01"]), ("MUSIC-02", changed["MUSIC-01"]),
                           ("MUSIC-01", changed["MUSIC-01"][:16]), ("MUSIC-03", changed["MUSIC-01"])]:
            p = self.cli("confirm", "--id", ident, "--sha256", sha)
            self.assertNotEqual(p.returncode, 0, p.stdout)
            self.assertNotIn("Traceback", p.stderr)
            self.assertEqual(before, {f: f.read_bytes() for f in self.root.iterdir() if f.is_file()})

    def test_prepare_validates_actual_video_duration_even_for_review(self):
        for ms in (849, True, 1200.5):
            with self.assertRaises(ValueError):
                music.prepare_music(self.root, self.items, ms, require_confirmed=False)
        self.assertEqual(music.prepare_music(self.root, [], 1200), [])
        cue, = music.prepare_music(self.root, self.items, 850, require_confirmed=False)
        self.assertFalse(cue["confirmed"])
        self.assertEqual(cue["sha256"], self.fingerprints()["MUSIC-01"])

    def test_preview_shows_full_gain_not_a_rounded_different_spec(self):
        self.items[0]["gain_db"] = -6.12345678
        self.write_plan()
        self.assertIn("-6.12345678 dB", self.preview())

    def test_only_project_files_not_traversal_devices_links_or_playlists(self):
        outside = self.root.parent / "outside.wav"
        outside.write_bytes((self.audio / "score.wav").read_bytes())
        alias = self.root / "alias.wav"
        os.link(outside, alias)
        external_dir = self.root.parent / "elsewhere"
        external_dir.mkdir()
        (external_dir / "ok.wav").write_bytes(outside.read_bytes())
        link = self.audio / "redirect"
        if os.name == "nt":
            subprocess.run(["cmd", "/d", "/c", "mklink", "/J", str(link), str(external_dir)],
                           check=True, capture_output=True)
        else:
            link.symlink_to(external_dir, target_is_directory=True)
        for file in ("../outside.wav", outside.as_posix(), "audio/redirect/ok.wav", "alias.wav", "audio",
                     "file:audio/score.wav", "audio/score.wav:alt", "//server/share/a.wav", r"C:\a.wav", "NUL.wav",
                     "audio/score.wav.", "audio/fake.m3u8", r"audio\..\outside.wav"):
            with self.subTest(file=file), self.assertRaises(ValueError):
                music.prepare_music(self.root, [dict(self.items[0], file=file)], 1200, require_confirmed=False)

    def test_concurrent_confirmations_do_not_lose_each_other(self):
        self.add_second()
        entries = self.fingerprints().items()
        with ThreadPoolExecutor(max_workers=2) as pool:
            list(pool.map(lambda kv: self.confirm(*kv), entries))
        self.assertEqual(len(music.prepare_music(self.root, self.items, 1200)), 2)

    def test_invalid_or_linked_ledger_does_not_get_replaced(self):
        ident, sha = next(iter(self.fingerprints().items()))
        self.confirm(ident, sha)
        ledger = self.root / ".tunjing-post-music.json"
        linked = self.root.parent / "outside-ledger"
        os.link(ledger, linked)
        before = ledger.read_bytes()
        self.assertNotEqual(self.cli("confirm", "--id", ident, "--sha256", sha).returncode, 0)
        self.assertTrue(linked.samefile(ledger))
        self.assertEqual(before, ledger.read_bytes())
        linked.unlink()
        ledger.write_bytes(b"{broken ledger")
        self.assertNotEqual(self.cli("confirm", "--id", ident, "--sha256", sha).returncode, 0)
        self.assertEqual(b"{broken ledger", ledger.read_bytes())

    def test_unsafe_other_path_aborts_entire_confirm_without_losing_good_receipt(self):
        self.add_second()
        shas = self.fingerprints()
        self.confirm("MUSIC-02", shas["MUSIC-02"])
        ledger = self.root / ".tunjing-post-music.json"
        before = ledger.read_bytes()
        self.items[1]["file"] = "../missing.wav"
        self.write_plan()
        run = self.cli("confirm", "--id", "MUSIC-01", "--sha256", shas["MUSIC-01"])
        self.assertNotEqual(run.returncode, 0)
        self.assertIn("MUSIC-02", run.stderr)
        self.assertEqual(before, ledger.read_bytes())

    def test_failed_or_colliding_mix_leaves_source_target_and_directory_intact(self):
        src, out = self.clip(), self.root / "已有.mp4"
        out.write_bytes(b"keep old")
        cues = self.approved()
        before = {p: p.read_bytes() for p in self.root.rglob("*") if p.is_file()}
        for target, ms in ((src, 1200), (out, 1200), (self.root / "bad.mp4", 1199)):
            with self.assertRaises(ValueError):
                music.mix_music(src, target, cues, ms)
        def interrupted(source, output, *args):
            output.write_bytes(b"partially written")
            raise ValueError("simulated encoder failure")
        with patch.object(music, "_mix", interrupted), self.assertRaisesRegex(ValueError, "encoder failure"):
            music.mix_music(src, self.root / "失败.mp4", cues, 1200)
        self.assertFalse(list(self.root.glob(".tunjing-mix-*")))
        self.assertEqual(before, {p: p.read_bytes() for p in self.root.rglob("*") if p.is_file()})

    def test_delayed_original_not_shifted_back_to_zero(self):
        src, out = self.clip(sound=True, offset=.2), self.root / "晚入原声.mp4"
        music.mix_music(src, out, self.approved(), 1200)
        data = samples(out)
        self.assertEqual(max(map(abs, data[:150 * 48])), 0)
        self.assertGreater(amplitude(data, 440, 220, 295), 3000)
        self.assertEqual(picture_packets(src), picture_packets(out))

    def test_preview_is_read_only_and_shows_reviewed_spec_and_full_fingerprint(self):
        h3 = self.root / ".whale_status.json"
        h3.write_bytes(b"H3 unrelated bytes")
        before = {p: p.read_bytes() for p in self.root.rglob("*") if p.is_file()}
        text = self.preview()
        self.assertRegex(text, r"MUSIC-01[^\n]*[0-9a-f]{64}\b")
        for field in ("audio/score.wav", "300", "850", "-6", "confirm", "--id", "--sha256", "H3", "外部"):
            self.assertIn(field, text)
        self.assertEqual(before, {p: p.read_bytes() for p in self.root.rglob("*") if p.is_file()})

    def test_cli_validates_every_cue_before_showing_any_fingerprint(self):
        cue = self.items[0]
        for invalid in ([cue, cue], [dict(cue, end_ms=86_400_001)], [dict(cue, start_ms=-1)],
                        [dict(cue, start_ms=850)], [dict(cue, start_ms=True)], [dict(cue, end_ms=600.5)],
                        [dict(cue, gain_db=-90)], [dict(cue, gain_db=7)], [dict(cue, gain_db=True)],
                        [dict(cue, id="../MUSIC-01")], [dict(cue, loop=True)], [dict(cue, gain_db="-6")],
                        [dict(cue, gain_db=float("inf"))], [dict(cue, gain_db=float("nan"))], None, {}):
            with self.subTest(invalid=invalid):
                self.write_plan(music=invalid)
                p = self.cli("preview")
                self.assertNotEqual(p.returncode, 0, p.stdout)
                self.assertNotIn("Traceback", p.stderr)
                self.assertNotIn("SHA256=", p.stdout)

    def test_only_self_contained_decodable_audio_long_enough_for_window(self):
        # First 200 ms are genuine, the WAV header still advertises 1200 ms.
        path = self.audio / "score.wav"
        blob = path.read_bytes()
        for bad in (b"not media", blob[:44 + 6400], b"ffconcat version 1.0\nfile score.wav\n"):
            with self.subTest(size=len(bad)):
                path.write_bytes(bad)
                p = self.cli("preview")
                self.assertNotEqual(p.returncode, 0, p.stdout)
                self.assertIn("MUSIC-01", p.stderr)
                self.assertNotIn("Traceback", p.stderr)

    def test_empty_or_missing_music_needs_no_media(self):
        self.plan.write_text('{"schema":"tunjing-post-v1"}', encoding="utf-8")
        self.assertIn("无配乐", self.preview())
        self.write_plan(music=[])
        self.assertIn("无配乐", self.preview())
        self.write_plan(schema="unexpected")
        self.assertNotEqual(self.cli("preview").returncode, 0)


if __name__ == "__main__":
    unittest.main()
