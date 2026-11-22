"""Independent CLI tests on CPU colour clips. No fixtures or caches in the checkout."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / 'scripts' / 'tunjing_post.py'
SCHEMA = 'tunjing-post-v1'


def cue(text, start=400, end=1000, **extra):
    return dict(start_ms=start, end_ms=end, text=text, **extra)


class PostLayers(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        tmp = tempfile.TemporaryDirectory(prefix='post-layers-', dir=ROOT.parent)
        cls.addClassCleanup(tmp.cleanup)
        cls.scratch = Path(tmp.name)
        cls.env = dict(os.environ, PYTHONUTF8='1', PYTHONDONTWRITEBYTECODE='1',
                       TMPDIR=tmp.name, TEMP=tmp.name, TMP=tmp.name, XDG_CACHE_HOME=tmp.name)
        cls.wide = cls.clip('横屏 原片.mp4', '320x180', audio=True)
        cls.tall = cls.clip('竖屏原片.mp4', '180x320', audio=False)

    @classmethod
    def clip(cls, name, size, audio):
        path = cls.scratch / name
        args = ['ffmpeg', '-nostdin', '-v', 'error', '-f', 'lavfi', '-i', f'color=black:s={size}:r=25:d=2']
        if audio:
            args.extend(['-f', 'lavfi', '-i', 'sine=frequency=440:sample_rate=48000:duration=2', '-c:a', 'aac'])
        subprocess.run([*args, '-c:v', 'libx264', '-threads', '1', '-pix_fmt', 'yuv420p', str(path)],
                       cwd=cls.scratch, env=cls.env, check=True, capture_output=True)
        return path

    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix='工程 ', dir=self.scratch)
        self.addCleanup(tmp.cleanup)
        self.project = Path(tmp.name)
        self.plan = self.project / '后期单.json'
        self.script = self.project / '剧本.md'

    def order(self, **fields):
        self.plan.write_text(json.dumps({'schema': SCHEMA, **fields}, ensure_ascii=False), encoding='utf-8-sig')

    def cli(self, command='check', source=None, out=None):
        args = [sys.executable, '-B', str(CLI), command, str(self.project), '--input', str(source or self.wide)]
        if out is not None:
            args.extend(['--out', str(out)])
        return subprocess.run(args, cwd=self.scratch, env=self.env, capture_output=True, encoding='utf8')

    def snapshot(self):
        return {p.name: (p.read_bytes(), p.stat().st_mtime_ns) for p in self.project.iterdir()}

    def test_check_card_only_reports_real_input_without_writes(self):
        self.order(cards=[cue('次日', kind='plain')])
        original = self.snapshot()
        run = self.cli()
        self.assertEqual(run.returncode, 0, run.stderr)
        for fact in ['320×180', '2000 ms', '后期单.json', 'cards[0]']:
            self.assertIn(fact, run.stdout)
        self.assertEqual(self.snapshot(), original)

    def rejected(self, expected, **fields):
        self.order(**fields)
        run = self.cli()
        self.assertNotEqual(run.returncode, 0, fields)
        self.assertIn(expected, run.stderr)
        self.assertNotIn('Traceback', run.stderr)

    def test_only_declared_schema_fields_plain_text_and_real_intervals(self):
        for expected, fields in [
            ('schema', {'schema': 'v2'}), ('prompt', {'prompt': 'oops'}),
            ('cards', {'cards': {}}), ('music', {'music': None}),
            ('kind', {'cards': [cue('甲')]}), ('plain', {'cards': [cue('甲', kind='panel')]}),
            ('font', {'cards': [cue('甲', kind='plain', font='file')]}),
            ('start_ms', {'cards': [cue('甲', start=True, kind='plain')]}),
            ('end_ms', {'cards': [cue('甲', end=2001, kind='plain')]}),
            ('end_ms', {'cards': [cue('甲', end=400, kind='plain')]}),
            ('重叠', {'cards': [cue('甲', kind='plain'), cue('乙', start=800, kind='plain')]}),
            *[('纯文本', {'cards': [cue(s, kind='plain')]}) for s in
              ['', r'{\an1}挪位置', r'换\N行', '甲\n乙', '甲\x00乙', '<b>变粗</b>', '\u202e倒写']],
        ]:
            with self.subTest(fields=fields):
                self.rejected(expected, **fields)
        self.plan.write_text('{"schema":"old","schema":"tunjing-post-v1"}', encoding='utf8')
        run = self.cli()
        self.assertNotEqual(run.returncode, 0)
        self.assertIn('重复', run.stderr)

    def test_subtitles_name_the_script_line_cards_name_the_order(self):
        self.script.write_text('# 夜班\n## 第一幕\n- **S1（低声）：** `<d>[Chinese]先读 A|B，真的？</d>`\n'
                               '<d>[Chinese]好。</d>\n男子A：“再等等！”\n', encoding='utf-8-sig')
        self.order(subtitles=[cue('先读 A|B，真的？'), cue('好。', 0, 400), cue('再等等！', 1000, 2000)],
                   cards=[cue('夜班', 0, 1000, kind='plain')])
        original = self.snapshot()
        run = self.cli()
        self.assertEqual(run.returncode, 0, run.stderr)
        for i, n in enumerate([3, 4, 5]):
            self.assertRegex(run.stdout, rf'subtitles\[{i}\].*剧本\.md:{n}\b')
        self.assertRegex(run.stdout, r'cards\[0\].*后期单\.json')
        self.assertEqual(self.snapshot(), original)

    def test_subtitles_never_mine_prompt_transcript_direction_or_loose_words(self):
        self.script.write_text('## 第一幕\nS1（推开门）：<d>[Chinese]没事，走吧！</d>\n'
                               '动作：<d>[Chinese]转身。</d>\n他指着纸上的“关门”。\n'
                               'S2：好。（关灯）\n> S1：<d>[Chinese]引语。</d>\n'
                               '```\n<d>[Chinese]示例。</d>\n```\n'
                               '## 转写草稿\nS1：<d>[Chinese]听错。</d>\n', encoding='utf8')
        (self.project / '视频提示词.md').write_text('S1：<d>[Chinese]别动。</d>', encoding='utf8')
        (self.project / '转写.srt').write_text('只有转写。', encoding='utf8')
        for words in ['推开门', '没事,走吧!', '走吧！', '转身。', '关门', '好。（关灯）', '引语。',
                      '示例。', '听错。', '别动。', '只有转写。']:
            with self.subTest(words=words):
                self.rejected('剧本.md', subtitles=[cue(words)])

    def media_cmd(self, *args):
        run = subprocess.run(args, cwd=self.scratch, env=self.env, capture_output=True)
        self.assertEqual(run.returncode, 0, run.stderr.decode('utf8', 'replace'))
        return run.stdout

    def assert_picture(self, source, output, w, h, with_audio, sub=None, card=None, new_audio=False):
        meta = json.loads(self.media_cmd('ffprobe', '-v', 'error', '-of', 'json', '-show_streams',
                                         '-show_format', str(output)))
        v, = [s for s in meta['streams'] if s['codec_type'] == 'video']
        self.assertEqual((v['width'], v['height'], v['avg_frame_rate']), (w, h, '25/1'))
        self.assertEqual(float(v['duration']), 2)
        self.assertEqual(sum(s['codec_type'] == 'audio' for s in meta['streams']), int(with_audio or new_audio))
        if with_audio:
            def audio(path):
                return self.media_cmd('ffmpeg', '-v', 'error', '-i', str(path), '-map', '0:a:0',
                                      '-f', 's16le', '-c:a', 'pcm_s16le', 'pipe:1')
            self.assertEqual(audio(output), audio(source))
        def frames(path):
            return self.media_cmd('ffmpeg', '-v', 'error', '-i', str(path), '-map', '0:v:0',
                                  '-fps_mode', 'passthrough', '-f', 'rawvideo', '-pix_fmt', 'gray', 'pipe:1')
        original, result = frames(source), frames(output)
        self.assertEqual(len(result), 50 * w * h)
        self.assertEqual(len(result), len(original))
        for n in range(50):
            t = n * 40
            off = n * w * h
            changed = [divmod(i, w) for i, (x, y) in enumerate(zip(original[off:off+w*h], result[off:off+w*h]))
                       if abs(x-y) > 48]
            top = sum(y < h//2 for y, x in changed)
            bottom = len(changed) - top
            for count, interval in [(top, card), (bottom, sub)]:
                if interval is not None and interval[0] <= t < interval[1]:
                    self.assertGreater(count, 6, (n, t, count, interval))
                else:
                    self.assertEqual(count, 0, (n, t, count, interval))
            self.assertTrue(all(w*.05 < x < w*.95 and h*.05 < y < h*.95 for y, x in changed), (w, h, t))

    def test_render_simultaneous_independent_layers_and_preserve_audio(self):
        self.script.write_text('S1：<d>[Chinese]来了吗？</d>\n', encoding='utf8')
        self.order(subtitles=[cue('来了吗？', 799, 1201)], cards=[cue('片名 Title', 401, 1000, kind='plain')])
        out = self.project / "宽屏 '1', [交付].mp4"
        run = self.cli('render', self.wide, out)
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assert_picture(self.wide, out, 320, 180, True, (799, 1201), (401, 1000))

    def test_render_portrait_card_only_on_silent_input(self):
        self.order(cards=[cue('收工，18:00', 480, 1200, kind='plain')])
        out = self.project / '卡.mp4'
        run = self.cli('render', self.tall, out)
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assert_picture(self.tall, out, 180, 320, False, card=(480, 1200))

    def test_render_refuses_existing_or_input_target_and_invalid_order(self):
        self.order()
        output = self.project / '已存在.mp4'
        output.write_bytes(b'keep me')
        for target in [output, self.wide]:
            original = target.read_bytes()
            run = self.cli('render', self.wide, target)
            self.assertNotEqual(run.returncode, 0)
            self.assertIn('覆盖', run.stderr)
            self.assertEqual(target.read_bytes(), original)
        self.order(cards=[cue('标题', kind='panel')])
        new = self.project / '不应生成.mp4'
        before = self.snapshot()
        run = self.cli('render', self.wide, new)
        self.assertNotEqual(run.returncode, 0)
        self.assertIn('plain', run.stderr)
        self.assertEqual(self.snapshot(), before)

    def music_item(self):
        name = '配乐.wav'
        self.media_cmd('ffmpeg', '-v', 'error', '-f', 'lavfi', '-i',
                       'sine=frequency=880:sample_rate=48000:duration=1', str(self.project / name))
        return dict(id='MUSIC-01', file=name, start_ms=400, end_ms=1000, gain_db=-3)

    def test_unconfirmed_music_stops_check_and_render_before_delivery(self):
        self.order(music=[self.music_item()], cards=[cue('夜', kind='plain')])
        before = self.snapshot()
        for cmd, out in [('check', None), ('render', self.project / '未确认.mp4')]:
            with self.subTest(cmd=cmd):
                run = self.cli(cmd, self.tall, out)
                self.assertNotEqual(run.returncode, 0)
                self.assertIn('确认', run.stderr)
                self.assertIn('MUSIC-01', run.stderr)
                self.assertEqual(self.snapshot(), before)

    def test_confirmed_local_music_on_finished_card_layer(self):
        import array
        import re
        item = self.music_item()
        self.order(music=[item], cards=[cue('已到站', 1000, 1600, kind='plain')])
        mcli = CLI.with_name('tunjing_post_music.py')
        preview = self.media_cmd(sys.executable, '-B', str(mcli), 'preview', str(self.project)).decode('utf8')
        digest = re.search(r'SHA256=([0-9a-f]{64})', preview).group(1)
        # Only a synthetic fixture is confirmed; never adopt a user's music.
        self.media_cmd(sys.executable, '-B', str(mcli), 'confirm', str(self.project), '--id', item['id'], '--sha256', digest)
        out = self.project / '已混音.mp4'
        run = self.cli('render', self.tall, out)
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assert_picture(self.tall, out, 180, 320, False, card=(1000, 1600), new_audio=True)
        samples = array.array('h', self.media_cmd('ffmpeg', '-v', 'error', '-i', str(out), '-map', '0:a:0',
                                                   '-f', 's16le', '-ac', '1', '-ar', '16000', 'pipe:1'))
        for a, b, audible in [(0, 200, False), (500, 900, True), (1300, 1950, False)]:
            peak = max(abs(v) for v in samples[16*a:16*b])
            self.assertTrue(peak > 150 if audible else peak < 50, (a, b, peak))

    def test_check_rejects_a_truncated_file_with_a_valid_video_header(self):
        self.order()
        source = self.project / '截断.mp4'
        self.media_cmd('ffmpeg', '-v', 'error', '-f', 'lavfi', '-i', 'testsrc2=s=80x80:r=25:d=2',
                       '-c:v', 'libx264', '-threads', '1', '-movflags', '+faststart', str(source))
        blob = source.read_bytes()
        source.write_bytes(blob[:len(blob)//2])
        for command, out in [('check', None), ('render', self.project / '不能交付.mp4')]:
            with self.subTest(command=command):
                run = self.cli(command, source, out)
                self.assertNotEqual(run.returncode, 0)
                self.assertIn(source.name, run.stderr)
                self.assertFalse(out and out.exists())

    def test_check_ignores_ffreport_and_empty_order_adds_nothing(self):
        self.order()
        log = self.scratch / 'check-must-not-write.log'
        self.env = dict(self.env, FFREPORT=f'file={log.name}:level=32')
        run = self.cli()
        self.assertFalse(log.exists())
        self.assertEqual(run.returncode, 0, run.stderr)
        out = self.project / '副本.mp4'
        run = self.cli('render', self.wide, out)
        self.assertEqual(run.returncode, 0, run.stderr)
        self.env.pop('FFREPORT')
        self.assert_picture(self.wide, out, 320, 180, True)

    def test_repeated_or_annotated_dialogue_is_not_unique_plain_speech(self):
        self.script.write_text('S1：<d>[Chinese]来了。</d>\nS2：<d>[Chinese]来了。</d>\n'
                               'S1：<d>[Chinese]（挥手）这边。</d>\n'
                               '## 动作注记\n### 场景 A\nS1：<d>[Chinese]样稿。</d>\n', encoding='utf8')
        for s in ['来了。', '（挥手）这边。', '样稿。']:
            with self.subTest(text=s):
                self.rejected('剧本.md', subtitles=[cue(s)])

    def test_long_portrait_card_wraps_in_safe_area_or_explicitly_refuses(self):
        self.order(cards=[cue('W' * 20, 200, 800, kind='plain')])
        out = self.project / '长行.mp4'
        run = self.cli('render', self.tall, out)
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assert_picture(self.tall, out, 180, 320, False, card=(200, 800))
        self.rejected('安全区', cards=[cue('字' * 200, kind='plain')])

    def test_rotated_input_uses_display_geometry_not_coded_geometry(self):
        self.order(cards=[cue('片头', 200, 800, kind='plain')])
        rotated = self.project / '旋转标记.mp4'
        self.media_cmd('ffmpeg', '-v', 'error', '-display_rotation', '90', '-i', str(self.wide),
                       '-map', '0', '-c', 'copy', str(rotated))
        check = self.cli('check', rotated)
        self.assertEqual(check.returncode, 0, check.stderr)
        self.assertIn('180×320', check.stdout)
        out = self.project / '实竖屏.mp4'
        run = self.cli('render', rotated, out)
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assert_picture(rotated, out, 180, 320, True, card=(200, 800))

    def test_non_dialogue_blocks_cannot_supply_a_subtitle(self):
        self.script.write_text('## 正文\n    S1：<d>[Chinese]代码。</d>\n'
                               '动作注记：\n<d>[Chinese]推门。</d>\n'
                               '## 动作\nS2：<d>[Chinese]退后。</d>\n', encoding='utf8')
        for words in ['代码。', '推门。', '退后。']:
            with self.subTest(words=words):
                self.rejected('剧本.md', subtitles=[cue(words)])

    def test_ambiguous_media_is_rejected_rather_than_dropping_tracks_or_shifting_text(self):
        self.order(cards=[cue('清晨', kind='plain')])
        soft = self.project / '原字幕.srt'
        soft.write_text('1\n00:00:00,000 --> 00:00:01,000\nAlready here\n', encoding='utf8')
        cases = [(['-i', str(self.wide), '-i', str(soft), '-map', '0', '-map', '1', '-c', 'copy', '-c:s', 'mov_text'], '附加轨'),
                 (['-itsoffset', '0.2', '-i', str(self.wide), '-i', str(self.wide),
                   '-map', '0:v:0', '-map', '1:a:0', '-c', 'copy'], '起点')]
        for idx, (args, message) in enumerate(cases):
            path = self.project / f'另版{idx}.mp4'
            self.media_cmd('ffmpeg', '-v', 'error', *args, str(path))
            run = self.cli(source=path)
            with self.subTest(case=message):
                self.assertNotEqual(run.returncode, 0)
                self.assertIn(message, run.stderr)

    def test_failed_mix_or_invalid_final_media_is_never_published(self):
        # Fault injection only at the collaborator boundary. Real renderer and
        # real ffprobe/decoder still run; a failure may leave bytes in staging.
        import contextlib
        import io
        from unittest.mock import patch
        sys.path.insert(0, str(CLI.parent))
        self.addCleanup(sys.path.remove, str(CLI.parent))
        import tunjing_post as post
        import tunjing_post_music as music
        self.order(music=[self.music_item()], cards=[cue('夜', kind='plain')])
        target = self.project / '不得交付.mp4'
        before = self.snapshot()
        for stop in [True, False]:
            with self.subTest(stop=stop):
                def fail_after_writing(source, dest, cues, duration_ms):
                    self.assertTrue(source.is_file())
                    self.assertNotEqual(source, self.tall)
                    self.assertNotEqual(dest, target)
                    dest.write_bytes(b'incomplete mix')
                    if stop:
                        raise ValueError('模拟混音中断')
                with patch.object(music, 'prepare_music', return_value=[object()]), \
                     patch.object(music, 'mix_music', side_effect=fail_after_writing) as mixer, \
                     contextlib.redirect_stderr(io.StringIO()):
                    self.assertNotEqual(post.main(['render', str(self.project), '--input', str(self.tall), '--out', str(target)]), 0)
                    mixer.assert_called_once()
                self.assertEqual(self.snapshot(), before)


if __name__ == '__main__':
    unittest.main()
