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

> 阶段解耦 · 非破坏剧本导入 · 统一 H3 编译器 · 闭环门禁 · 本地工作台一体交付。
> 工程验收边界与测试说明见 [engineering-contract.md](references/engineering-contract.md)。

---

## 一、工作流与职责边界

1. **端到端自主推进（禁止每步停下问“是否继续/确认”）**
   - 除 **初次立项缺少题材/画幅** 与 **Gate 5 签发《监制五维核对签字单.md》后准备提交 ComfyUI 渲染前** 必须停机呈报外，其余从剧本导入、规范化、视觉设定、拆镜、提示词编译到 `whale_pipeline_check.py` / Gate 1–5 闭环修复，**全部在单轮内自主连贯跑通并自愈报错**，严禁每改完一个小环节就停下来等用户说“继续 / 确认”。
   - **非破坏性剧本导入与格式统一（`scripts/whale_script_intake.py`）**：
     按序执行：① `python scripts/whale_script_intake.py "<原稿>" --project "<项目目录>"` 先做 `--dry-run` 预览，核对分集数、剥离的 `人物小传-前言.md` 及每集 `duration_estimate` 的 `incomplete` 为 `null`（`review_status=clean`）；② 加 `--apply` 将原稿原字节备存至 `输入/original-*` 并写入 `剧集/<EP>/剧本.md`（存量非规范库用 `--standardize-workspace --apply`）；③ 接手旧/残缺工程的完整流程见 [takeover-and-patching.md](references/takeover-and-patching.md)。
     - *规范与提取硬约束*：遵循 [screenplay-format.md](references/sd_core/screenplay-format.md)「规范化不改台词」，仅对齐结构外壳（`# EP001`、`## EP001-SC001 内/外 · 地点 · 时间`、`角色（表演）：台词`、`[VO]`/`[OS]`/`[SFX]`/`[画面文字]`/`[连续性]`）。分集切分与解析必须兼容 `# EP001《标题》`（集号紧邻书名号无空格）、`**角色：**`/`**角色 OS：**`（冒号在加粗内）、`` `<d>[Chinese]...</d>` `` 包裹对白及 `### 阶段`/`### 节拍` 连续性子标题；纯叙事动作句的修饰冒号（如 `面部近景：...`）与集前 `>` 摘要分别转为破折号或注释（动作描述长句绝不当说话人），以免触发 `screenplay_index.py` 的 `source_issue` 或让工作台侧栏显示 `**` 与假说话人。提取 `--speaker` 前须先剥除 `[VO] ` / `[OS] ` 前缀（否则 `[OS]` 说话人会触发 `screenplay_index.py` 的 `source_issue`），读 `duration_estimate.py` JSON 时须读嵌套 `counts.*` 字段，修改解析器后须用真实 `.docx`/紧凑场标（`1-1日内`、`7-1 夜外`、`【字幕：...】`、`△动作。角色：台词`）与多集加粗合并稿实测而非只跑合成样本。
     `whale_script_intake.py`、`whale_pipeline.py`、`whale_gatekeeper.py` (`audit_step_2`) 与 `sd_core/creator_views.py` (`parse_screenplay`) 统一经 `detect_document_role()` 校验文档身份；一旦命中 `SHOT-xx`+`景别`/`机位`/`f` 或 `subject_definitions:`+`detailed_description:` 立即拒绝导入或放行，严禁工作台用兜底逻辑把错误分镜吞成假场次。
     - *跨脚本/视图修改避坑*：改写 `whale_gatekeeper.py` 等多步骤脚本时，校验补丁必须锚定该步独有文件变量（如 Gate 2 的 `script_file`），禁止匹配 `with open(path)` 这类与 Gate 3（`分镜.md`）共用的模板行；扩展 `creator_views.py` 时须保留中文参考图文件名（禁止用 `[A-Za-z0-9_./-]+` 截断中文资产名），并区分项目根目录与分集目录——工作台进度与 `设定`/`分镜`/`提示词` 页签只认 `剧集/<EP>/` 下的对应文件，未制作下游阶段时如实保持 `0/N` 未写，不从下游反推伪造上游 `剧本.md`。
   - **五文档阶段推进**（契约见 [creator-documents.md](references/sd_core/creator-documents.md) 与 [creator-workflow.md](references/sd_core/creator-workflow.md)）：
     `剧集/<EP>/剧本.md` ➔ `剧集/<EP>/视觉设定.md`（特殊模式按需加挂动作序列规划）➔ `剧集/<EP>/图片提示词.md` ➔ `剧集/<EP>/分镜.md` ➔ `剧集/<EP>/视频提示词.md` ➔ 门禁核验 ➔ 生产/后期。
   - **剧本就绪自动加载与全页实时热同步（强制，不等用户催促）**：
     只要通过 `whale_script_intake.py --apply`、对话手写或任何脚本新写入/修改了 `剧本.md`（或 `剧集/*/剧本.md`），**当场立即调用 `auto_start_dashboard(project_dir, open_browser=True)`（或 `python scripts/whale_dashboard.py --workspace "<项目目录>" --port 0 --detach --open`）并把可点击链接直接给用户，绝不等用户再下指令**；`whale_pipeline.py` / `whale_gatekeeper.py` (Gate 2) / `whale_pipeline_check.py` 同样自动拉起工作台。已运行的工作台会每 `2.5s` 自动比对 `/api/live_signature` 热同步磁盘改动（无需手工 F5 或下指令），且每次 `whale_dashboard.py` 检测到 `brand` 或 `code_fingerprint` 陈旧时会自动淘汰重启旧进程，确保永远加载最新版工作台（手动唯一入口：`python scripts/whale_dashboard.py --workspace "<项目目录>" --port 0 --detach --open`，内部 `--status`/`--detach` 调用须带有限超时如 15s 防僵尸端口阻塞）。
     若 `.short-drama/dashboard.json` 已有存活进程但 `brand != "tunjing-baodian"`，严禁静默复用，必须 `--restart` 终止旧进程后重拉。引导查看分镜示意图与检视器须指向顶部 `分镜` 阶段页签；`批量任务.json` 为下游编译产物，不作前置手写文件；Markdown 结构门禁与 ComfyUI 批任务门禁须各自独立核验；临时 E2E 验证完成后须停掉临时后台进程并清理临时目录。
2. **制作形态与决策分工**
   - **六大制作形态卡（`references/sd_core/form-cards/*.md`）**：按 `short-drama.json` 的 `production_form` 自动匹配「实拍 / 二维动态漫 / 风格化三维 / 国漫二次元 / 水墨笔触 / Q版表达」；实拍默认启用 `DE_OIL` 去油光质感锁，动画/三维/水墨自动屏蔽 `35mm` 皮肤摄影前缀并切换对应风格描述。
   - **需监制确认的决策**：题材方向、冲突原型、画幅比例（`16:9` / `9:16` / `1:1`）、角色参考资产、指定工作流路径及特殊动作序列确认。
   - **引擎自动执行项**：非破坏分集切片、景别与机位梯度、时长帧数对齐（H3 须满足 `length = 5 + 17 * N`）、参考图 `1–9` 槽位装配、音色账本 (`VoiceRegistry`) 注入与多模态提示词编译。
3. **工程维护与质量铁律**
   - **严禁绕过真源与门禁**：不得私建临时脚本或未指定工作流；通过 Gate 5 签发《监制五维核对签字单.md》后停机呈报，未经明确指令不得向 ComfyUI 提交渲染；三大前置闸门：① 显式锁定 `aspect`；② `00_资产/` 非空且逐镜 `ref_images` 物理存在；③ ≥5 镜严禁单一机位、单一景别或静态占比 >60%。
   - **脚本联动、正则兼容与全局验收铁律**：修改跨脚本契约（`SPEECH:` 行格式、体位校验、`creator_views` 解析）时，先全局检索并对齐全部下游校验器与回归测试（`whale_task_source.py`、`whale_shot_facts.py`、`whale_pose_guard.py`、`tests/`），避免主链加新片段（如音色描述）却被既有精确正则误杀或正剧通用调度原语被体位守卫误拦。扩展 `creator_views.py` 标题匹配时须同时兼容无 `##` 标记的场景 ID 与 `## 第X幕`、`画面`/`OS`/`结束状态` 及 `/` 分隔机位；全仓 CLI 脚本统一使用 `argparse` 并对内部 `subprocess.run()` 设置有限 `timeout`（禁止位置参数把 `--help` 当目录建库并拉起后台进程）；修改或验收完成后须清理 `--help/`、`__pycache__/` 与临时测试进程，再执行 `py_compile`、`node --check`、`selftest.py`、`unittest`、真实浏览器 E2E 与脱敏扫描。
   - **前端与安全铁律**：禁止内联 `style` / `cssText`（遵守 `style-src 'self'` CSP）；扩展 DOM 须在 `host.innerHTML = ...` 之后挂载；参考图复选框必须按完整文件名精确比对（禁用 `.endsWith(name)` 防 `female_*` 误匹配 `male_*`）；`/api/whale/shot` `GET`/`POST` 均带集号 `ep` 参数并统一扫描 `03_生成任务/<ep>/批量任务.json` 与 `剧集/<ep>/批量任务.json`；正剧 (`standard_drama`) 全链路锁死 `is_nude_state=False`、支持中文资产名并严禁生成或放行 `*_nude.png` / 非零 `MysticXXX` 权重。
   - **提交与维护**：禁止向 `SKILL.md` 尾部追加补丁；维护变更须同步更新 `scripts/selftest.py` 并全量跑通 `selftest.py` + `unittest` + `node --check` + 脱敏扫描（见 [github-sync.md](references/github-sync.md)），提交前清理 `__pycache__/` 与临时目录。

---

## 二、模式隔离与净化动作真源

| 模式 (`project_mode`) | 工作台与门禁表现 | 动作与模型参数控制 |
|---|---|---|
| **`standard_drama`**（默认正剧/动画） | 隐藏专项动作规划页签与相关选择器，保持标准短剧工作台视图。 | `MysticXXX` 权重锁死 `0.0`，禁止出现 `*_nude.png` 与成人术语；通用场次调度原语（`category="staging"`）正常放行，其余非正剧动作一律拦截。 |
| **`adult_drama`**（特殊定制题材） | 在 `视觉设定 ➔ 分镜` 之间按需激活 `体位 · 94 真源` 规划与检视器选择。 | 全部 94 条真源（`references/whale_poses_matrix.json`）已完成全肯定物理去毒与全分类标注（0 `Woman A/Man A`、0 负向词、0 空分类）；异常动作须经 `scripts/whale_pose_guard.py` 跨维度守卫与转换后方可通过 Gate 4。 |

---

## 三、多目标视频模型方言与统一 H3 编译器 (`references/dialects/`)

剧本与分镜保持模型无关，至 `视频提示词.md` 编译阶段按项目锁定的目标模型切换方言：
- **MiniMax H3（统一编译内核：`whale_core.py` + `whale_h3_prompt.py`）**：
  - **Ref2VA 六段式** (`compile_h3_ref2va_prompt` / `single_shot_prompt`)：单 `Camera:` 行 + 姿态分流情绪动作表（禁止站姿脚部重心词渗入坐/跨/跪/仰卧体位）+ 全集 `VoiceRegistry` 音色指纹直入 `SPEECH:` + 非说话人闭嘴锁；
  - **Base / 首帧 / 首尾帧三段式** (`compile_h3_base_prompt`)：`integrated_multimodal_description` + `overall_soundscape` + `non_diegetic_music`；
  - **多镜容器** (`compile_h3_container_prompt`)：4–15s 内打包 2–4 个带独立起始帧的关键帧切镜；
  - 方言细节见 `references/dialects/minimax-h3.md` 与 `references/h3-prompt-master-guide.md`。
- **Seedance 2.0 / 2.5**：参见 `references/dialects/seedance-2.0.md`、`references/dialects/seedance-2.5.md`。
- **Wan 3.0**：参见 `references/dialects/wan-3.0.md`；能力边界参考 `references/dialects/target-model-profile.md`。

---

## 四、刚性门禁体系 (Gates & Pipeline Check)

1. **联合闭环核验（每步完稿执行）**：
   ```bash
   python scripts/whale_pipeline_check.py "<项目目录>" [--mode standard_drama|adult_drama]
   ```
   串联 `sd_core/creator_markdown_check.py`、`sd_core/screenplay_index.py` + `duration_estimate.py`、`whale_pose_guard.py`、`whale_compiler.lint_task_prompt()` 与 `validate_batch_voice_consistency()`（同时扫描 `批量任务.json` 与 `03_生成任务/*/批量任务.json`）。
2. **六步生产门禁 (`python scripts/whale_gatekeeper.py <项目目录> [1-6]`)**：
   - **Gate 1**：`00_资产/` 物理图片存在性与可读性校验
   - **Gate 2**：`剧本.md` 结构、对白格式与动作推进校验
   - **Gate 3**：`分镜.md` 景别/机位活性、帧长与语速预算校验
   - **Gate 4**：显式画幅、`1–9` 槽位实图存在性、体位跨维度防呆与提示词编译校验
   - **Gate 5**：`whale_diff_audit.py` 盲检一致性、模式纯净度并签发 SHA-256 核对单
   - **Gate 6**：闭合打包与指定工作流原地节点回填

---

## 五、核心目录与脚本索引

| 路径 | 核心职责 |
|---|---|
| `scripts/whale_script_intake.py` | 非破坏性剧本导入与格式统一（`--dry-run` / `--apply` / `--standardize-workspace`） |
| `scripts/whale_dashboard.py` | 唯一本地创作台统一启动入口（自动建档并拉起 `sd_core/dashboard_server.py`） |
| `scripts/sd_core/` | 对齐 `short-drama` 底座的全套确定性引擎（`dashboard_server` / `creator_views` / `creator_markdown_check` / `project_tool` / `episode_intake` / `screenplay_index` / `duration_estimate` / `storyboard_check` / `container_check` / `motion_timing_check` / `asset_check` / `image_prompt_check` / `review_check`） |
| `scripts/whale_pipeline_check.py` | Markdown 闭环 + 台词估时 + 动作真源 + H3 编译 + 音色账本联合核验入口 |
| `scripts/whale_gatekeeper.py` | 六大刚性步进门禁状态机 |
| `scripts/whale_pose_guard.py` | 动作真源校验、跨维度防呆与高危动作安全降级转换器 |
| `scripts/whale_h3_prompt.py` / `whale_core.py` | H3 统一三段式 / 六段式 / 多镜容器提示词编译器 + `VoiceRegistry` 音色账本 |
| `scripts/whale_scene.py` / `whale_dialogue.py` / `whale_storyboard.py` | 自动拆镜、文戏调度与单镜多节拍精修引擎 |
| `scripts/whale_compiler.py` / `whale_diff_audit.py` | 提示词体检与生成前盲检审计 |
| `scripts/whale_runner.py` / `whale_mastering.py` | ComfyUI 后台批跑点火与后期母带音画缝合 |
| `scripts/whale_advisor.py` | 旧项目/废稿接盘诊断顾问 |
| `references/sd_core/` | 文档契约、制作形态 profiles 与 6 张 UTF-8 `form-cards/*.md` |
| `references/whale_poses_matrix.json` | 净化后 94 条动作与机位真源矩阵 |
| `references/transition_recipes.json` / `oneshot_transitions.json` | 40 条物理衔接配方与 9 套一键转换模板 |
| `references/h3-official/` | MiniMax-AI 官方 `h3-prompt-writing` 原件真源 |
