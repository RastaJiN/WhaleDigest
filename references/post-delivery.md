# 后期交付：本地独立字幕与普通字卡

适用范围：已有现成成片（`.mp4` 等本地容器）时，使用本机 `ffmpeg` / `ffprobe` 在画布上叠加独立字幕与普通纯文本字卡，可选混入经逐条确认的本地配乐。**此入口不调用 H3、不触发 ComfyUI、不需要 Node 或 Remotion，也不修改原片或已有目标文件。**

## 清单格式（`项目目录/后期单.json`）

固定 `schema` 为 `"tunjing-post-v1"`，顶层只允许 `schema`、`subtitles`、`cards`、`music`（三个数组可省略或为空）：

```json
{
  "schema": "tunjing-post-v1",
  "subtitles": [
    {"start_ms": 400, "end_ms": 1800, "text": "单据呢？"}
  ],
  "cards": [
    {"start_ms": 100, "end_ms": 900, "text": "清晨·办公室", "kind": "plain"}
  ],
  "music": [
    {"id": "MUSIC-01", "file": "audio/score.wav", "start_ms": 0, "end_ms": 2000, "gain_db": -12}
  ]
}
```

- **`subtitles`**：每条须为 `{start_ms, end_ms, text}`（整数毫秒、同层不重叠、位于实际成片时长内）。`text` 必须逐字唯一核对到 `项目目录/剧本.md` 正文的完整对白原文（含标点），拒绝从动作注记、代码块、提示词或转写文本捞取，拒绝 ASS/HTML 控制符与换行。
- **`cards`**：每条须为 `{start_ms, end_ms, text, kind: "plain"}`。仅支持普通纯文本字卡（位于画面顶部安全区，字幕位于底部安全区，两者分轨独立）；遇到非 `plain`（如手机屏、系统面板、动态 HUD）明确报错拒绝，不静默降级。
- **`music`**：交由 `tunjing_post_music.py` 逐条预览并显式确认后才能在 `check` / `render` 放行；详情见[逐曲确认与混音](post-music.md)。

## 最小调用命令

```bash
# 只读校验（不写任何文件，不改原片）
python scripts/tunjing_post.py check <项目目录> --input <已有成片.mp4>

# 渲染新成片（绝不覆盖输入或已有目标；临时文件验收通过后才原子落盘）
python scripts/tunjing_post.py render <项目目录> --input <已有成片.mp4> --out <新成片.mp4>
```

## 边界与限制

- **不会擦除已有烫字**：如果上游视频本身已烫印字幕，本工具只在画面上另行叠加，不能消除原片瑕疵。
- **不静默丢弃附加轨或错位时间轴**：输入必须为单条可播放视频流（零或一条原声，且视频起点归零、无内封字幕/封面等附加轨），否则拒绝处理。
- **支持横屏与竖屏**：自动按实际显示宽高（含直角旋转元数据）计算字号与三行安全区；超出三行安全区时明确报错。
- **仅做后期包装**：`check` / `render` 通过只说明后期叠加和音画参数合规，不代表上游 H3 画面口型、人物一致或表演质量合格。
