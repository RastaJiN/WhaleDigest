
import json
from whale_compiler import lint_task_prompt

def doctor_review(shot, feedback):
    """根据门禁报错，生成修改指令"""
    prompt = shot.get("prompt", "")
    return f"【性能修正】你的 Prompt 存在以下问题: {feedback}。请重写，严格遵循物理反馈层、心理锚点层，禁止抽象形容词。"

def auto_fix_shot(shot, feedback):
    """自动根据报错优化该镜头"""
    # 这里接入大模型接口逻辑
    print(f"正在修复镜头 {shot.get('id')} ... 原因: {feedback}")
    return shot
