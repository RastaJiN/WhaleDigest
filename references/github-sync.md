# 吞鲸宝典 · 跨机同步与仓库维护指南 (Repository Sync Guide)

## 一、仓库信息
- **GitHub 仓库**：`https://github.com/RastaJiN/WhaleDigest.git` (`main` 分支；旧地址 `RastaJiN/tunjing-baodian` 自动重定向)
- **标准挂载路径**：`~/.hermes/skills/tunjing-baodian` 或本地 Agent Skills 目录

## 二、任意新机器 1:1 部署与验证三步法

1. **拉取或更新宝典**：
   ```bash
   git clone https://github.com/RastaJiN/WhaleDigest.git tunjing-baodian
   # 或在已有目录执行 git pull origin main
   ```
2. **运行组件完整性自检**：
   ```bash
   python scripts/selftest.py
   ```
3. **运行全仓单元测试与纯净导出复验**：
   ```bash
   python -m unittest discover -s tests
   ```
   - 推送前若需做 `git archive` 纯净包隔离复验，在 Windows 上**务必使用 Python `tarfile.extractall(..., filter="data")` 解包**，不要调用系统 `tar -xf`（Windows `tar.exe` 会破坏 UTF-8 中文文件名导致 `selftest.py` 误报缺文件）。
   - `selftest.py` 与 `unittest` 全绿仅证明代码、门禁与离线工作流构造通过；真实 ComfyUI 渲染与画面质量须在渲染机 `git pull` 后实片验收。

## 三、开发维护纪律
- **提交信息铁律**：对主仓库的 `git commit`，commit message 一律只写 `修复少量BUG`，不在提交记录中暴露具体功能细节。
- **真源唯一性**：`references/whale_poses_matrix.json`、`references/transition_recipes.json`、`references/oneshot_transitions.json` 为唯一数据真源；`references/kinetic-positions.md` 由脚本从 JSON 自动生成，严禁手改导致脱节。
- **装配唯一性与正剧物理隔离**：`scripts/whale_core.py` / `scripts/whale_h3_prompt.py` 与 `whale_scene.py` 须保持单一活跃编译入口（修改后务必核实 `whale_h3_prompt.py` 是否真正接入主链、无“写好却未调用”的死岛），严禁并存两套互相矛盾的模板拼接；`whale_scene.py`、`whale_pipeline.py`、`whale_runner.py` 须读取 `short-drama.json` 的 `project_mode`，`standard_drama` 下锁死 `is_nude_state = False`、支持中文资产名（不用 `isascii()` 过滤）、禁写 `*_nude.png` 占位名与非零 `MysticXXX` 权重，且 `whale_gatekeeper.py` 显式锁定 `standard_drama` 直接拦截任何误入 `_nude` 资产而不被假名反转模式。
- **词库正全肯定审计**：发布前扫描 `references/whale_poses_matrix.json` 的 `beatsEn`/`framingEn`，清零残留 `Woman A/Man A`、`zero tearing off`、`zero handjob`、`without ever...` 等负向毒词与空 `category`。
- **仓库卫生、CLI 安全与发布前脱敏扫描**：全仓 CLI 脚本必须用 `argparse` 接管参数（严禁位置参数把 `--help` 当输出目录建库），且 `whale_dashboard.py::_is_temp_test_dir()` 须拦截仓库内部路径与 `-` 开头目录以防误拉后台工作台；`whale_pipeline.py`、`whale_pipeline_check.py`、`whale_script_intake.py` 与 `whale_dashboard.py` 内部子进程调用均须设有限 `timeout`（如 15–180s）。推送远端前必须清理 `__pycache__/`、`*.pyc`、`.short-drama/`、`.whale_dashboard.json`、`--help/`、临时日志与任何临时运行目录（严禁将 `16x9/`、`9x16/` 等项目产物流入仓库根目录）；同步前全文检索并清零四类敏感/测试残留：① 测试项目名与本地试跑目录残留；② 个人署名/工作室旧代号；③ `C:\Users\...` 等本机绝对路径；④ `.short-drama/dashboard.json` 中的运行时回环凭据 token。
- **跨脚本契约修改前全局检索**：修改跨文件共享文本格式（如 `SPEECH:` 行格式、体位校验边界、`creator_views` 标题解析）前，先全局搜索上游生成与全部下游解析正则/单元测试（如 `whale_task_source.py`、`whale_shot_facts.py`、`whale_pose_guard.py`），确保新增字段（如音色描述）置于既有固定锚点之外（例如置于 `only <Subject N> (Sx) says:` 之前而非插在 `(Sx)` 与 `says:` 之间），避免触发连环回归；正剧模式 (`standard_drama`) 放行 `category="staging"`/`"通用"` 通用调度原语，仅拦截非正剧动作。
- **外部规范移植编码检查**：从 Windows 命令行或外部技能包同步/移植多文件（如 `form-cards/*.md` 或 `sd_core/*.py`）后，逐个核对磁盘实际文件名与 UTF-8 内容完整性，防止中文文件名乱码或写入遗漏。
- **版本号与自检清单同步**：修改核心文件或发布版本升级时，须同步对齐 `SKILL.md`、`README.md`、`references/h3-prompt-master-guide.md` 及 `scripts/*.py` 横幅版本号，并检查 `scripts/selftest.py` 的 `REQUIRED_FILES` 是否已纳管全部新增核心文件、门禁脚本、前端静态资源与方言文档，再执行 `selftest.py` + `unittest` + `node --check assets/dashboard/app.js` 验收。
- **多模式工作台与前端交付验收**：
  1. **CSP 与 DOM 约束**：静态资源 URL 须带防缓存版本串（`?v=...`）；动态注入扩展（`viewPoses` / Inspector）严禁使用内联 `style` / `cssText`（统一改走外联 CSS 类名），且必须在 `host.innerHTML = ...` 赋值之后挂载、不得在 CSS Grid 子项上混设 `overflow-x: hidden`，长列表格须用 `repeat(2, minmax(0, 1fr))` 防横向溢出；
  2. **资产匹配与跨集路由**：资产复选回显使用完整 basename 精确匹配（禁用 `.endsWith(name)` 防 `female_*` 误勾 `male_*`）；`/api/whale/shot` 的 `GET` 与 `POST` 须传集号 `ep` 并扫描根目录 `批量任务.json`、`03_生成任务/<ep>/批量任务.json` 与 `剧集/<ep>/批量任务.json`；
  3. **品牌隔离与双模式真实浏览器复验**：启动复用前校验 `.short-drama/dashboard.json` 中的 `brand` 指纹与脚本路径（`dashboard_server.py` 直接读取同目录 `project_tool.py`，不留外部兄弟技能回退路径），`whale_dashboard.py` 须透传 `--restart`；通过 HTTP API 直连复验工作台时需同时校验未授权请求返回 `401` 与携带 `X-Short-Drama-Token` 请求头返回正常数据；按 `standard_drama`（确认成人页签/体位控件隐藏）与 `adult_drama`（确认 94 真源筛选/保存与检视器无横向溢出及零 `.notice`/Console/CSP 报错）实机浏览器核验；若测试或实机验片期间拉起了临时 E2E `dashboard_server.py`，验收完毕须精准查杀临时 `tb_*e2e*` 后台进程并清理临时目录，避免残留后台进程占端口。
- **跨包差异诚实汇报**：比对原版 `short-drama` 底座时分别运行 `difflib` 文件对比并如实汇报跨子技能功能差异与本地验证边界，禁止只用局部合成夹具绿灯冒充全链路已对齐。
