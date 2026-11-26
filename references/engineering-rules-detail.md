# 吞鲸宝典 · 工程与解析细则（从主 SKILL.md 归位）

> 本文件收纳从主 `SKILL.md` 下沉的所有解析约束、正则避坑、前端安全与验收细则。主 `SKILL.md` 仅保留路由、阶段推进与核心命令入口。

## 1. 非破坏性剧本导入与格式约束
- 遵循 [screenplay-format.md](sd_core/screenplay-format.md)「规范化不改台词」，仅对齐结构外壳（`# EP001`、`## EP001-SC001 内/外 · 地点 · 时间`、`角色（表演）：台词`、`[VO]`/`[OS]`/`[SFX]`/`[画面文字]`/`[连续性]`）。
- 分集切分与解析兼容 `# EP001《标题》`、`**角色：**`/`**角色 OS：**`、`` `<d>[Chinese]...</d>` `` 包裹对白及 `### 阶段`/`### 节拍` 连续性子标题。
- 纯叙事动作句的修饰冒号与集前 `>` 摘要分别转为破折号或注释，以免触发 `screenplay_index.py` 的 `source_issue`。
- 提取 `--speaker` 前须先剥除 `[VO] ` / `[OS] ` 前缀；读 `duration_estimate.py` JSON 时须读嵌套 `counts.*` 字段。
- `whale_script_intake.py`、`whale_pipeline.py`、`whale_gatekeeper.py` (`audit_step_2`) 与 `sd_core/creator_views.py` (`parse_screenplay`) 统一经 `detect_document_role()` 校验文档身份；命中 `SHOT-xx`+`景别`/`机位`/`f` 或 `subject_definitions:`+`detailed_description:` 立即拒绝。

## 2. 跨脚本/视图修改避坑
- 改写 `whale_gatekeeper.py` 等多步骤脚本时，校验补丁必须锚定该步独有文件变量（如 Gate 2 的 `script_file`），禁止匹配 `with open(path)` 这类与 Gate 3 共用的模板行。
- 扩展 `creator_views.py` 时须保留中文参考图文件名，并区分项目根目录与分集目录——工作台进度与 `设定`/`分镜`/`提示词` 页签只认 `剧集/<EP>/` 下的对应文件，未制作下游阶段时如实保持 `0/N` 未写，不从下游反推伪造上游 `剧本.md`。
- 修改跨脚本契约时，先全局检索并对齐全部下游校验器与回归测试（`whale_task_source.py`、`whale_shot_facts.py`、`whale_pose_guard.py`、`tests/`）。
- 全仓 CLI 脚本统一使用 `argparse` 并对内部 `subprocess.run()` 设置有限 `timeout`；修改或验收完成后须清理 `--help/`、`__pycache__/` 与临时测试进程，再执行 `py_compile`、`node --check`、`selftest.py`、`unittest`、真实浏览器 E2E 与脱敏扫描。

## 3. 前端与安全铁律
- 禁止内联 `style` / `cssText`（遵守 `style-src 'self'` CSP）；扩展 DOM 须在 `host.innerHTML = ...` 之后挂载。
- 参考图复选框按完整文件名精确比对（禁用 `.endsWith(name)`）。
- `/api/whale/shot` `GET`/`POST` 均带集号 `ep` 参数并统一扫描 `03_生成任务/<ep>/批量任务.json` 与 `剧集/<ep>/批量任务.json`。
- 正剧 (`standard_drama`) 全链路锁死 `is_nude_state=False`、支持中文资产名并严禁生成或放行 `*_nude.png` / 非零 `MysticXXX` 权重。
