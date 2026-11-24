---
name: tunjing-baodian
description: "Use when producing or auditing short dramas with WhaleDigest."
version: 4.6.3
author: 吞鲸工作室 (Swallowing Whale Studio)
license: MIT
metadata:
  hermes:
    tags: [tunjing, baodian, drama, ref2v, gatekeeper]
---

# 🐳 WhaleDigest · 短剧工业化导演与门禁引擎 (v4.6.3)

> 阶段解耦 · 闭环门禁 · 多模型方言 · 本地工作台一体交付。
> 工程验收边界与测试说明见 [engineering-contract.md](references/engineering-contract.md)。

---

## 一、工作流与职责边界

1. **创作台与阶段解耦（先写后编、一次一环）**
   - 严格按阶段推进，仅读取上游定稿产物并写回当前阶段标准 Markdown：
     `剧本.md` ➔ `视觉设定.md`（特殊模式加挂动作序列规划）➔ `图片提示词.md` ➔ `分镜.md` ➔ `视频提示词.md` ➔ 门禁核验 ➔ 生产/后期。
   - **剧本就绪自动加载工作台（强制，不等用户催促）**：
     只要项目中已存在或刚写入 `剧本.md`（或 `剧集/*/剧本.md`），系统通过 `whale_pipeline.py` / `whale_gatekeeper.py` (Gate 2) / `whale_pipeline_check.py` 会**自动后台拉起本地创作台**并输出 URL（手动拉起唯一入口：`python scripts/whale_dashboard.py "<项目目录>" --port 0 --detach --open`）。
     创作台默认只读写标准 Markdown 与项目状态索引；`批量任务.json` 为下游渲染编译产物，不作为前置手写文件。
2. **决策与执行分工**
   - **需监制确认的决策**：题材方向、冲突原型、画幅比例（`16:9` / `9:16` / `1:1`）、角色参考资产、指定工作流路径及特殊动作序列确认。
   - **引擎自动执行项**：单镜拆镜、景别与机位梯度、时长帧数对齐（H3 须满足 `length = 5 + 17 * N`）、参考图 `1–9` 槽位动态装配、音色账本校验与多模态提示词编译。
3. **四条工程硬约束**
   - **严禁绕过真源与门禁**：不得在项目内临时编写一次性脚本或私建未指定的 ComfyUI 工作流；外部指定工作流须通过 `--workflow <路径>` 或 `.whale_project.json["workflow"]` 原地回填。
   - **点火签字隔离**：通过 Gate 5 生成《监制五维核对签字单.md》并停机呈报，未经明确渲染指令不得提交 ComfyUI 渲染；`跳过测试` 仅跳过样镜，不跳过资产与门禁校验。
   - **三大物理前置闸门**：① 显式锁定 `aspect`；② `00_资产/` 非空且逐镜 `ref_images` 100% 物理存在可读；③ ≥5 镜严禁单一机位、单一景别或静态机位占比 >60%。
   - **提交规范**：仓库维护提交前清理 `__pycache__/` 与临时测试目录；不泄露本地绝对路径与测试剧名。

---

## 二、模式隔离与专项动作控制

| 模式 (`project_mode`) | 工作台与门禁表现 | 动作与模型参数控制 |
|---|---|---|
| **`standard_drama`**（默认正剧/动画） | 隐藏专项动作规划页签与相关选择器，保持标准短剧工作台视图。 | `MysticXXX` 等专项权重默认归零（`0.0`），严禁出现非正剧术语；按纯正剧口径执行。 |
| **`adult_drama`**（特殊定制题材） | 在 `视觉设定 ➔ 分镜` 之间按需激活专项动作序列规划，并在分镜检视器开放对应选择器。 | 所有亲密/高难度动作须从 `references/whale_poses_matrix.json`（94 条动作真源）选取并锁定 `framingZh`；禁止自造易穿模动作，旧稿异常动作须经 `scripts/whale_pose_guard.py` 转换为安全可落地动作后再进分镜。 |

---

## 三、多目标视频模型方言 (`references/dialects/`)

剧本与分镜保持模型无关，至 `视频提示词.md` 编译阶段按项目锁定的目标模型切换方言：
- **MiniMax H3**：走 `scripts/whale_h3_prompt.py` Ref2VA 六段式 + `voice_bible.json`（参见 `references/dialects/minimax-h3.md` 与 `references/h3-prompt-master-guide.md`）。
- **Seedance 2.0 / 2.5**：参见 `references/dialects/seedance-2.0.md`、`references/dialects/seedance-2.5.md`。
- **Wan 3.0**：参见 `references/dialects/wan-3.0.md`；能力边界参考 `references/dialects/target-model-profile.md`。

---

## 四、刚性门禁体系 (Gates & Pipeline Check)

1. **Markdown 闭环与动作总检（每步完稿执行）**：
   ```bash
   python scripts/whale_pipeline_check.py "<项目目录>" --mode <standard_drama|adult_drama>
   ```
   串联 `sd_core/creator_markdown_check.py`（场景来源解析、4 字以上台词逐字核对、连续性锁原样透传、跨镜边界校验）与 `whale_pose_guard.py`。
2. **六步生产门禁 (`python scripts/whale_gatekeeper.py <项目目录> [1-6]`)**：
   - **Gate 1**：`00_资产/` 物理图片存在性与可读性校验
   - **Gate 2**：`剧本.md` 结构、对白格式与动作推进校验
   - **Gate 3**：`分镜.md` 景别/机位活性、帧长与语速预算校验
   - **Gate 4**：显式画幅、`1–9` 槽位实图存在性与提示词编译校验
   - **Gate 5**：`whale_diff_audit.py` 盲检一致性、模式纯净度并签发 SHA-256 核对单
   - **Gate 6**：闭合打包与指定工作流原地节点回填

---

## 五、核心目录与脚本索引

| 路径 | 核心职责 |
|---|---|
| `scripts/whale_dashboard.py` | 唯一本地创作台统一启动入口（自动建档并拉起 `sd_core/dashboard_server.py`） |
| `scripts/whale_pipeline_check.py` | Markdown 闭环 + 动作真源联合核验入口 |
| `scripts/whale_gatekeeper.py` | 六大刚性步进门禁状态机 |
| `scripts/whale_pose_guard.py` | 动作真源校验与高危动作安全降级转换器 |
| `scripts/whale_h3_prompt.py` | H3 六段全场景提示词编译器 + `VoiceRegistry` 音色账本 |
| `scripts/whale_scene.py` / `whale_dialogue.py` / `whale_storyboard.py` | 自动拆镜、文戏调度与单镜多节拍精修引擎 |
| `scripts/whale_compiler.py` / `whale_diff_audit.py` | 提示词体检与生成前盲检审计 |
| `scripts/whale_runner.py` / `whale_mastering.py` | ComfyUI 后台批跑点火与后期母带音画缝合 |
| `scripts/whale_advisor.py` | 旧项目/废稿接盘诊断顾问 |
| `references/whale_poses_matrix.json` | 94 条动作与机位真源矩阵 |
| `references/transition_recipes.json` / `oneshot_transitions.json` | 40 条物理衔接配方与 9 套一键转换模板 |
| `references/h3-official/` | MiniMax-AI 官方 `h3-prompt-writing` 原件真源 |
