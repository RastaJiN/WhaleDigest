# 后期独立配乐：逐曲预览、显式确认与本地混音

适用范围：配合 `后期单.json` 中的 `music` 数组，对项目目录内**本机已有音频文件**做逐条审核确认，再由 `tunjing_post.py render` 调用 `prepare_music` / `mix_music` 混入成片。**与 H3 渲染签字完全隔离，不联网、不调用任何付费或音频生成服务。**

## 条目格式

`后期单.json`（`schema: "tunjing-post-v1"`）中每条 `music` 仅允许五个字段：

```json
{"id": "MUSIC-01", "file": "audio/score.wav", "start_ms": 200, "end_ms": 1800, "gain_db": -12}
```

- `id`：匹配 `MUSIC-01` 这类唯一标识，同单不重复。
- `file`：限定在项目目录内的普通相对路径（拒绝越界、链接逃逸或外部绝对路径），且实解音轨长度必须覆盖 `end_ms - start_ms`（不静默循环或补静音截断）。
- `start_ms` / `end_ms`：整数毫秒且位于视频时长内；混音时仅在该精确采样窗口叠加，窗口外不引入音乐，也不裁剪或移动视频帧。
- `gain_db`：`[-60, +6]` 范围内的有限数值；多条重叠时按各自增益线性叠加，不做隐式闪避（ducking）。

## 预览与逐条确认

```bash
# 1. 只读预览：列出每条规格、确认状态与完整 64 位 SHA256 指纹
python scripts/tunjing_post_music.py preview <项目目录>

# 2. 用户听取并明确选定后，逐条按完整指纹确认（写入 .tunjing_post_music.json）
python scripts/tunjing_post_music.py confirm <项目目录> --id MUSIC-01 --sha256 <64位完整SHA256>
```

## 隔离与失效规则

- **单曲指纹独立**：每条的 SHA256 只绑定该条的规格字段与实际音频文件字节，**不绑定视频画面、字幕、字卡或其他 `MUSIC-*` 条目**。修改无关镜头、字幕或其他配乐条目，不会让已确认的当前条目失效。
- **变更即过期**：一旦修改该条目的 `file`、`start_ms`、`end_ms`、`gain_db` 或替换磁盘音频字节，旧票据立即失效，`prepare_music(..., require_confirmed=True)` 和 `mix_music` 都会拒绝继续，必须重新 `preview` 并确认。
- **混音输出保护**：无原声视频自动补静音底轨，有单条原声时保留原声电平并重采样至 48 kHz 立体声无损混音（ALAC）；多原声轨或异常封装拒绝静默丢弃；绝不覆盖已有目标文件。
