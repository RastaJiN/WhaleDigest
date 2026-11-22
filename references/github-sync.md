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
- **装配唯一性**：`scripts/whale_core.py` 为六段式提示词装配与 `with_scene_surface` 场地适配的唯一内核，`whale_scene.py` 与 `whale_storyboard.py` 统一调用该内核，严禁各写一份。
- **仓库卫生**：推送远端前必须清理 `__pycache__/` 与任何临时运行目录（严禁将 `16x9/`、`9x16/` 等项目产物流入仓库根目录），确保远端仓库永远处于干净整洁的 Master 状态。
