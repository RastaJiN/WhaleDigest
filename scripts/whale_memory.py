import json
from pathlib import Path

def get_project_state(project_dir):
    """提取跨集记忆状态"""
    state_file = Path(project_dir) / 'project_state.json'
    if state_file.exists():
        return json.loads(state_file.read_text(encoding='utf-8'))
    return {"episodes_written": [], "active_rules": {}}

def update_project_state(project_dir, ep_num, summary):
    """更新状态包"""
    state = get_project_state(project_dir)
    state["episodes_written"].append(ep_num)
    state["active_rules"].update(summary)
    Path(project_dir).joinpath('project_state.json').write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding='utf-8')
