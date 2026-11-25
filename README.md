# 🐳 吞鲸宝典 (WhaleDigest) · v4.7.0

> 吞鲸工作室 · 短剧工业化导演与门禁生产引擎
> 阶段解耦 · 闭环门禁 · 多模型方言 · 本地工作台一体交付

工程接口与验收边界见 [工程契约](references/engineering-contract.md)。

---

## 安装

```bash
git clone https://github.com/RastaJiN/WhaleDigest.git ~/.hermes/skills/tunjing-baodian
```

---

## 一、本地创作台唯一入口

```bash
python scripts/whale_dashboard.py "<项目目录>" --port 0 --detach --open
```

- 默认仅读写标准 Markdown 与项目状态索引；
- 按 `project_mode` 自动隔离模式：`standard_drama`（普通正剧/动画）隐藏专项动作选单并将专项权重归零；`adult_drama`（专项题材）于 `视觉设定 ➔ 分镜` 之间开放 94 条动作真源规划与检视器选择。

---

## 二、核心工具与门禁

| 脚本 / 文件 | 核心职责 |
|---|---|
| `scripts/whale_script_intake.py` | 非破坏性多集/散装剧本导入与格式统一（`规范化不改台词`） |
| `scripts/whale_dashboard.py` | 唯一本地工作台启动入口（自动建档并拉起多视图交互工作台） |
| `scripts/whale_pipeline_check.py` | Markdown 闭环校验（来源、4 字以上台词逐字核对、连续性锁）+ 动作真源联合核验 |
| `scripts/whale_gatekeeper.py` | 六大刚性步进门禁状态机（Gate 1–6） |
| `scripts/whale_pose_guard.py` | 动作真源校验与高危动作安全降级转换 |
| `scripts/whale_h3_prompt.py` | MiniMax H3 六段式提示词编译器 + 全集音色账本 (`voice_bible.json`) |
| `scripts/whale_scene.py` / `whale_dialogue.py` / `whale_storyboard.py` | 自动拆镜、文戏调度与单镜精修 |
| `scripts/whale_diff_audit.py` | 生成前盲检审计与五维签字单 |
| `scripts/whale_runner.py` / `whale_mastering.py` / `export_jianying_draft.py` | ComfyUI 原地工作流回填点火、母带音画精修与剪映草稿导出 |
| `references/dialects/` | MiniMax H3 / Seedance 2.0 / Seedance 2.5 / Wan 3.0 提示词方言规范 |
| `references/whale_poses_matrix.json` | 94 条动作与机位真源矩阵 |

---

## 三、自检与测试

```bash
python -m unittest discover -s tests -p "test_*.py"
python scripts/dryrun_test.py
```
