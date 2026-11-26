---
name: tunjing-baodian
description: "Use when creating, importing, formatting, or producing short dramas and manju (短剧/漫剧/正剧/剧本导入/分镜/提示词/工作台/审片) with WhaleDigest."
version: 4.7.1
author: 吞鲸工作室 (Swallowing Whale Studio)
license: MIT
metadata:
  hermes:
    tags: [tunjing, baodian, drama, ref2v, gatekeeper]
---

# 🐳 WhaleDigest · 短剧工业化导演与门禁引擎 (v4.7.1)

> 对齐 `short-drama` 原版五文档工作流，在此基础上升级非破坏剧本导入、正剧确定性拆镜排时、94 套动作真源、H3 编译器与本地工作台。
> 工程细则与验收边界见 [engineering-contract.md](references/engineering-contract.md) 与 [engineering-rules-detail.md](references/engineering-rules-detail.md)。

---

## 一、立项确认（加载后必先弹窗）

加载宝典或接手既有项目时，**必须立即调用 `clarify` 工具**弹出可点击的选择表单，向监制一次性确认 4 项核心参数：
1. **资产处理**：复用现有资产包（推荐） / 重新生成
2. **项目模式**：`standard_drama` 纯净正剧（推荐） / `adult_drama` 成人剧（仅在明确成人剧本或点名时启用）
3. **画幅**：`16:9`（推荐） / `9:16` / `1:1`
4. **目标集数**：按目标集长切分（推荐，如 150 秒/集） / 按原稿集数

已有资产包（含 6 格 Model Sheet）直接盘点挂载为 `REF-...` 参考，**禁止擅自切图、重造人设或重写 `视觉设定.md` / `图片提示词.md`**。

---

## 二、五文档路由与阶段推进

所有项目统一维护唯一真相 `剧集/<EP>/` 下的五份 Markdown，**不建立并行的结构化创作真相、不为补齐名义流水线伪造上游、不将占位时长同步进正式 `分镜.md`**：

| 阶段 | 产物 | 唯一入口 / 规范 |
|---|---|---|
| 1. 剧本导入 | `剧集/<EP>/剧本.md` | `python scripts/whale_script_intake.py "<原稿>" --project "<项目目录>"`（先 `--dry-run` 再 `--apply`，按目标集长与剧情自然断点切分集数） |
| 2. 视觉设定 | `剧集/<EP>/视觉设定.md` | 复用已有资产包（`输入/参考图/`）或按 `references/sd_core/form-cards/*.md` 匹配制作形态 |
| 3. 图片提示词 | `剧集/<EP>/图片提示词.md` | 按参考图与冻结关键帧编写 |
| 4. 分镜与排时 | `剧集/<EP>/分镜.md` | **正剧**：`python scripts/whale_drama_storyboard.py --script "剧集/<EP>/剧本.md" --target-sec 150`<br>**成人剧**：`python scripts/whale_pipeline.py` / `whale_scene.py`（94 套动作真源 + `allowed_cameras` 过滤） |
| 5. 视频提示词 | `剧集/<EP>/视频提示词.md` | `whale_h3_prompt.py` / `whale_core.py`（MiniMax H3 原生音画同生，不先跑离线 TTS 倒推切镜） |
| 6. 门禁与停机 | 《监制五维核对签字单.md》 | `python scripts/whale_pipeline_check.py "<项目目录>"` & `whale_gatekeeper.py <项目目录> [1-6]`；**Gate 5 后停机呈报，未经明确指令不得提交 ComfyUI 渲染** |

---

## 三、本地工作台（唯一启动入口）

只要新写入/修改了 `剧本.md`（或 `剧集/*/剧本.md`），**当场立即拉起工作台并把可点击链接打印给用户**：

```bash
python scripts/whale_dashboard.py --workspace "<项目目录>" --port 0 --detach --open
```

- 仅在首次新启动时打开一次浏览器；工作台已在线时静默复用，依赖每 `2.5s` 的 `/api/live_signature` 热同步。
- 传入 `剧集/<EP>/` 子目录时自动向上锚定到项目根目录。

---

## 四、模式隔离与核心资产索引

| 模式 (`project_mode`) | 工作台与门禁表现 | 动作与模型参数控制 |
|---|---|---|
| **`standard_drama`**（默认正剧） | 隐藏专项动作规划页签，保持标准短剧工作台视图。 | `MysticXXX` 权重锁死 `0.0`，禁止 `*_nude.png` 与成人术语；通用场次调度正常放行。 |
| **`adult_drama`**（特殊定制题材） | 按需激活 `体位 · 94 真源` 规划与检视器。 | 全部 94 条真源（`references/whale_poses_matrix.json`）+ `whale_pose_guard.py` 跨维度守卫。 |

- **方言与真源**：`references/dialects/`（MiniMax H3 / Seedance / Wan 3.0）、`references/h3-official/`、`references/takeover-and-patching.md`（旧工程接盘）。
- **核心引擎**：`scripts/sd_core/`（对齐 `short-drama` 底座）、`whale_runner.py` / `whale_mastering.py`（渲染与后期）、`whale_advisor.py`（旧项目诊断）。
- **维护与自检**：维护变更后全量跑通 `python scripts/selftest.py`、`python -m unittest discover -s tests`、`node --check assets/dashboard/app.js`（见 `references/github-sync.md`）。
