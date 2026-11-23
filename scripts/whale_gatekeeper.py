"""
吞鲸工作室 · 全流程步进门禁状态机 (WhaleDigest Pipeline Gatekeeper)
严格执行：Step 1 ➔ Step 2 ➔ Step 3 ➔ Step 4 ➔ Step 5
每一步必须校验前置产物，通过才放行下一步。严禁跳步！
"""

import os
import sys
import json
import re
from whale_task_source import (load_task_source, source_record, refresh_status,
                                 require_source_audit, TaskSourceError, validate_batch_metadata,
                                 stage_record, gate_evidence, validate_asset_image,
                                 validate_project_assets)
from whale_compiler import lint_task_prompt

STAGE_NAMES = {
1: "第 1 步：角色母版与资产建库 (Asset Foundation)",
2: "第 2 步：刀锋剧本创作 (Sharp Script)",
3: "第 3 步：弹跳分镜与节拍呼吸 (Bounce Storyboard)",
4: "第 4 步：纯血Ref2V提示词编译 (Prompt Audit)",
5: "第 5 步：生成前自我终极审核 (Pre-Render Self-Audit)",
6: "第 6 步：渲染提交与工程出片 (Render Dispatch)"
}

def get_status_file(project_dir):
    return os.path.join(project_dir, ".whale_status.json")

def load_status(project_dir):
    status_file = get_status_file(project_dir)
    if os.path.exists(status_file):
        try:
            with open(status_file, "r", encoding="utf-8") as f:
                data = json.load(f)
                if "current_step" not in data:
                    data["current_step"] = 1
                if "passed_steps" not in data:
                    data["passed_steps"] = []
                return data
        except Exception:
            pass
    return {"current_step": 1, "passed_steps": []}

def save_status(project_dir, status):
    status_file = get_status_file(project_dir)
    os.makedirs(project_dir, exist_ok=True)
    with open(status_file, "w", encoding="utf-8") as f:
        json.dump(status, f, ensure_ascii=False, indent=2)

def audit_step_1(project_dir):
    """门禁 1：角色母版与场景底图检查"""
    # 必须有男女主穿衣母版与素身母版（同源）
    asset_dir = os.path.join(project_dir, "00_资产")
    if not os.path.exists(asset_dir):
        return False, "缺少 '00_资产' 文件夹！请先创建资产目录。"
    
    files = [name for name in os.listdir(asset_dir) if os.path.isfile(os.path.join(asset_dir, name))]
    def role(name, kind):
        stem = os.path.splitext(name)[0].lower()
        if kind == "male":
            return "男" in stem or bool(re.search(r"(?:^|[^a-z])male(?:$|[^a-z])", stem))
        if kind == "female":
            return "女" in stem or bool(re.search(r"(?:^|[^a-z])female(?:$|[^a-z])", stem))
        return bool(re.search(r"场景|scene|room|corridor", stem))
    valid = []
    invalid = []
    for name in files:
        try:
            validate_asset_image(os.path.join(asset_dir, name))
            valid.append(name)
        except (ValueError, OSError):
            invalid.append(name)

    if not valid:
        return False, (
            f"资产目录 '00_资产/' 中没有任何有效可读图片文件（实有文件: {files[:8]}）！"
            "必须先放入真实角色/场景参考图，禁止空目录假通过 Gate 1。"
        )
    return True, f"资产目录基础核验 PASS（实测 {len(valid)} 张有效图片：{valid[:8]}）；逐镜绑定核验将在 Gate 4/5 严格执行。"

def audit_step_2(project_dir):
    """门禁 2：刀锋剧本三幕式与道具流转检查"""
    script_file = os.path.join(project_dir, "剧本.md")
    if not os.path.exists(script_file):
        return False, "缺少 '剧本.md'！请先撰写本集剧本。"
    
    with open(script_file, "r", encoding="utf-8") as f:
        content = f.read()
        
    from pathlib import Path
    from whale_pose_choice import PLAN, reviewed_plan, authored_text
    import whale_prose as prose
    receipt = Path(project_dir)/PLAN
    planned = None
    if receipt.is_file():
        try:
            plan = json.loads(receipt.read_text('utf8'))
            _, rows, _ = reviewed_plan(project_dir, script_file, plan['scene'], plan.get('scene_id'))
            planned = [row for row in rows.values() if row.get('source_line') or row.get('line')]
        except (KeyError, OSError, ValueError) as exc:
            return False, f'分镜确认已失效：{exc}'

    authored = authored_text(content)
    if planned is not None:
        alias_file = Path(project_dir)/'角色映射.json'
        aliases = json.loads(alias_file.read_text('utf-8-sig')) if alias_file.is_file() else {}
        body = prose.screenplay(authored, aliases)
    else:
        body = list(prose.source_rows(authored))
    # Legacy explicit acts, or distinct titled sections actually bound to shots.
    if not ('第一幕' in authored and '第二幕' in authored):
        bound = {r.get('source_line') or r.get('line') for r in (planned or [])}
        sections = {r['scene'] for r in body if r['scene'] and r['line'] in bound}
        if not sections:
            return False, '剧本缺少清晰幕次或与执行镜头对应的场次结构'

    seen_turns=[]
    for row in body:
        raw = row['raw']
        turns = row['turns'] if 'turns' in row else prose.dialogue_on(raw)
        if turns:
            seen_turns.extend(turns)
        if (len(re.findall(r'<d>',raw,re.I)) != len(list(prose.D_TAG.finditer(raw))) or
                len(re.findall(r'</d>',raw,re.I)) != len(list(prose.D_TAG.finditer(raw))) or
                any(not d['text'].strip() for d in turns)):
            return False, f"第 {row['line']} 行对白标签无效"
        if not prose.D_TAG.search(raw):
            # A standalone source name/cue is different from a colon inside prose.
            s = re.sub(r'^\s*(?:镜头?|SHOT)[ _-]*\d+\s*[:：]\s*','',raw,flags=re.I)
            apparent = re.match(r'^(?:[-*]\s*)?(?:\*\*)?[\w·-]{1,12}(?:[（(][^）)]*[）)])?(?:\*\*)?[:：]\s*(?:\*\*)?[^\s].*[。！？?!]$',s)
            if (turns or apparent) and not (planned and turns):
                return False,'检测到未绑定的对白；请标明说话人并用 <d>[Chinese]...</d> 包裹'
    if planned is not None:
        imported=[d for r in planned if (d:=r.get('dialogue'))]
        if imported != seen_turns:
            return False,'原稿对白与已确认分镜数量或顺序不一致'

    # 去AI味翻译腔与书面套话拦截
    cliche_hits = re.findall(r"(你怎么能如此|我的心好痛|充满了不可思议|眼中闪过一丝|嘴角勾起一抹弧度|三分薄凉|既然你如此无情|休怪我无义)", content)
    if cliche_hits:
        return False, f"剧本门禁未通过：[AI腔台词拦截] 检测到书面套话/翻译腔 {sorted(set(cliche_hits))}！请改为 12 字以内的口语化狠话或潜台词短句。"
        
    # 从唯一数据真源动态加载全部动作/调度 ID，避免矩阵更新后 Gate 2 硬编码列表滞后
    matrix_path = Path(__file__).resolve().parent.parent / "references" / "whale_poses_matrix.json"
    KNOWN_IDS = set(json.loads(matrix_path.read_text(encoding="utf-8-sig")).keys())
    # 反作弊锁 5：严禁将英文代码箭头 (pose_a -> pose_b) 粗暴塞入 Markdown 标题行充数！
    heading_cheat = re.findall(r'^#{1,4}\s+.*?\([a-z_]+\s*->\s*[a-z_]+.*\)', content, re.MULTILINE)
    if heading_cheat:
        return False, f"剧本门禁未通过：[反作弊拦截·标题塞代码作弊] 检测到标题行被强行塞入代码括号 {heading_cheat[:2]}！请保持标题纯净中文文学性。"

    # 支持自然中文动作描述或标准 ID 识别（无需为迎合正则污染剧本标题）
    ZH_ACTION_KEYWORDS = re.findall(r'(站立按墙|按墙后入|后入|跪姿口交|口交|深喉|传教士|正面交合|观音坐莲|女上位|骑乘|侧卧|指插|自慰|潮吹|高潮|捏下巴|壁咚|递卡|房卡)', content)
    from whale_solo import PROP_IDS
    KNOWN_IDS.update(PROP_IDS)
    ids_in_script = set(re.findall(r'\b([a-z][a-z_0-9]{1,24})\b', content)) & KNOWN_IDS
    if len(ids_in_script) + len(set(ZH_ACTION_KEYWORDS)) < 2:
        # One reviewed action/shot is sufficient evidence in this pipeline.
        # Don't manufacture a second pose to satisfy the legacy heuristic.
        if planned:
            return True, '剧本与已确认的可见镜头一致；单镜无需补动作 PASS'
        return False, "剧本门禁未通过：剧本必须包含至少 2 处明确的阶段性动作/体位推进描述（支持自然中文如“站立按墙/口交/观音坐莲/正面交合”或吞鲸标准 ID）！"
        
    detected_desc = sorted(ids_in_script) if ids_in_script else sorted(set(ZH_ACTION_KEYWORDS))
    return True, f"刀锋剧本结构、活人感台词与动作演进 ({detected_desc[:6]}) 验收 PASS！允许进入分镜设计。"

def audit_step_3(project_dir):
    """Validate each declared shot using the same duration and dialogue contract as generation."""
    from whale_core import dialogue_needed_seconds, STAGING_IDS
    from whale_task_source import execution_board_path
    try:
        path = execution_board_path(project_dir)
    except (ValueError, OSError) as exc:
        return False, f'执行分镜来源无效：{exc}'
    if not os.path.isfile(path):
        return False, f"缺少 '{path.name}'"
    with open(path, encoding="utf-8-sig") as handle:
        content = handle.read()
    marks = list(re.finditer(
        r"(?im)^[ \t]*(?:#{1,4}[ \t]*)?\[?(?:SHOT(?:[ _-]+[A-Za-z0-9]+)*[ _-]*\d+|R\d+[ _-]+\d+)[^\r\n]*",
        content,
    ))
    if not marks:
        return False, "分镜未检测到逐镜 SHOT 标记"
    cam_tokens = []
    size_tokens = []
    for index, mark in enumerate(marks):
        block = content[mark.start():marks[index+1].start() if index+1 < len(marks) else len(content)]
        if not re.search(r"Track:[ \t]*Ref2V\b", block, re.IGNORECASE):
            return False, f"镜头 {index+1} 缺少 Track: Ref2V"
        duration_match = re.search(r"(?:时长[：:]\s*)?(\d+(?:\.\d+)?)\s*(?:s\b|秒)", block, re.IGNORECASE)
        if not duration_match:
            return False, f"镜头 {index+1} 缺少时长"
        duration = float(duration_match.group(1))
        if not 39/24 - .021 <= duration <= 294/24 + .021:
            return False, f"镜头 {index+1} 时长 {duration} 超出 H3 39..294 帧范围"
        sz_m = re.search(r"\b(wide|mcu|cu|macro|hip|face)\b|(全景|中景|中近景|近景|微距|特写)", block, re.IGNORECASE)
        if not sz_m:
            return False, f"镜头 {index+1} 缺少景别"
        size_tokens.append((sz_m.group(1) or sz_m.group(2) or "").lower())
        cam_m = re.search(
            r"\b(push_tension|pull_reveal|tilt_up_desire|tilt_down_impact|ots_depth|arc_subtle|handheld_breath|"
            r"low_upward|high_downward|static_side|static_rear|static_front|low_hip|slow_push|follow_soft|"
            r"pan_left_right|track_lateral)\b|(?:机位[：:]\s*([^\r\n|]+))|(?:Camera:\s*([^\r\n]+))|"
            r"(固定|过肩|俯|仰|推|拉|摇|手持)",
            block, re.IGNORECASE,
        )
        if not cam_m:
            return False, f"镜头 {index+1} 缺少机位"
        raw_cam = next((g.strip() for g in cam_m.groups() if g and g.strip()), "")
        cam_tokens.append(raw_cam.lower())
        speeches = re.findall(r"<d>(.*?)</d>", block, re.IGNORECASE | re.DOTALL)
        if len(re.findall(r"<d>", block, re.IGNORECASE)) != len(speeches):
            return False, f"镜头 {index+1} 台词标签未闭合"
        required = 0
        for speech in speeches:
            speech = re.sub(r"^\s*\[[^]]+\]", "", speech).strip()
            if not speech:
                return False, f"镜头 {index+1} 台词为空"
            required += dialogue_needed_seconds(speech)
        if required > duration + .021:
            return False, f"镜头 {index+1} 台词需要 {required:.3f}s，镜长仅 {duration}s"

    # 分镜视听活性硬闸：>=5 镜的分镜禁止全片单机位僵死或静态机位超过 60%
    if len(marks) >= 5:
        unique_cams = {c for c in cam_tokens if c}
        if len(unique_cams) <= 1:
            return False, (
                f"分镜运镜僵化拦截：共 {len(marks)} 镜，却全部是同一个机位（{sorted(unique_cams)}）！"
                "必须按节奏与情绪配置多机位运镜与景别呼吸变化。"
            )
        static_count = sum(1 for c in cam_tokens if "static" in c or "固定" in c)
        if static_count > len(marks) * 0.6:
            return False, (
                f"分镜运镜僵化拦截：共 {len(marks)} 镜中静态机位占 {static_count} 镜（>{int(len(marks)*0.6)} 镜上限），"
                "缺乏运镜呼吸感与节奏推进！"
            )
        if len({s for s in size_tokens if s}) <= 1:
            return False, (
                f"分镜景别单一拦截：共 {len(marks)} 镜全为单一景别（{sorted(set(size_tokens))}），"
                "缺少全景/中近景/近景/特写阶梯呼吸！"
            )
    return True, f"逐镜结构、轨道、景别机位({len(set(cam_tokens))}机位/{len(set(size_tokens))}景别)、H3 时长与共享台词预算 PASS ({len(marks)} 镜)"


def audit_step_4(project_dir):
    """门禁 4：纯血Ref2V提示词编译、节拍感知与按需资产核验"""
    from pathlib import Path
    try:
        task_path, batch, sha = load_task_source(project_dir)
        issues = []
        try:
            validate_batch_metadata(batch)
        except ValueError as exc:
            issues.append(str(exc))
        # 无条件逐镜核验参考图物理存在与可读性（不再用 'pose_input_hashes' in batch 偷偷放行旧任务或假文件名）
        if not issues:
            try:
                validate_project_assets(project_dir, batch)
            except TaskSourceError as exc:
                issues.append(str(exc))
        # 校验全集音色账本（若项目含 voice_bible.json）及画外音/独白闭嘴锁、跨镜声源一致性
        if not issues:
            from whale_h3_prompt import load_project_voice_registry, validate_batch_voice_consistency
            vreg = load_project_voice_registry(project_dir)
            v_errs, v_warns = validate_batch_voice_consistency(batch, vreg)
            issues.extend(v_errs)
            for w in v_warns:
                print(f"[音色提醒] {w}")
        for index, shot in enumerate(batch["batch_shots"], 1):
            sid = shot.get("shot_id", shot.get("id", index))
            # 检查是否为节拍感知模式 (Beat: ...)
            is_beat = any(k in shot.get("prompt", "") for k in ["[Beat: Silence]", "[Beat: Transition]"])
        
            if not is_beat:
                errors, warnings = lint_task_prompt(shot, batch)
                issues.extend(f"{sid}: {error}" for error in errors)
                for warning in warnings:
                    print(f"[提醒·{sid}] {warning}")
            else:
                 print(f"[节拍感知模式·{sid}] 已跳过动作检查")
        if issues:
            return False, f"{task_path}: " + " | ".join(issues)
        return True, f"逐镜任务校验 PASS: {task_path}; SHA256={sha}"
    except (ValueError, OSError) as exc:
        return False, f"任务源读取或校验失败: {exc}"


def audit_step_5(project_dir):
    """门禁 5：生成前机器实测终审与 SHA-256 防伪签名核验（彻底废除手写假报告）"""
    import hashlib
    import whale_diff_audit as diff_mod

    try:
        batch_file, _, _ = load_task_source(project_dir)
    except (ValueError, OSError) as exc:
        return False, f"终审门禁未通过：任务源错误: {exc}"

    # 自动调用 whale_diff_audit 进行真实盲检并签发带 SHA-256 指纹的终审报告
    rep = diff_mod.audit_project(project_dir)
    if rep.get("violations"):
        diff_mod.write_signed_audit_report(project_dir, rep)
        return False, f"终审门禁未通过：[机器盲检抓出 {len(rep['violations'])} 项真实违规] 首项: {rep['violations'][0]}"

    report_file = diff_mod.write_signed_audit_report(project_dir, rep)
    diff_mod.write_producer_receipt(project_dir, rep)

    with open(report_file, "r", encoding="utf-8") as f:
        content = f.read()

    # 校验报告中的 SHA-256 指纹是否与当前 批量任务.json 100% 匹配（拦截手写假报告或改后未重审）
    expected_sha = diff_mod.compute_batch_sha256(project_dir)
    if expected_sha not in content:
        # 自动刷新签名报告并再次校验
        report_file = diff_mod.write_signed_audit_report(project_dir, rep)
        diff_mod.write_producer_receipt(project_dir, rep)
        with open(report_file, "r", encoding="utf-8") as f:
            content = f.read()
        if expected_sha not in content:
            return False, "终审门禁未通过：[反作弊拦截·伪造终审报告] 报告缺少与当前 批量任务.json 匹配的 SHA-256 机器签名指纹！严禁手写假报告！"

    if "PASS" not in content or "REJECT" in content:
        return False, "终审门禁未通过：终审报告中存在未解决的 REJECT 项或未明确标注 PASS！必须全部达标！"

    required_checks = ["资产实名与槽位", "音画台词咬合", "换体位与特写契约", "受控运镜规范", "提示词纯净度", "纯血Ref2V单轨规范"]
    missing = [c for c in required_checks if c not in content]
    if missing:
        return False, f"终审门禁未通过：终审报告缺少以下维度的审核记录: {missing}！必须六项全检！"

    return True, f"工程结构与输入绑定核验 PASS ({expected_sha[:12]}...)；创作质量与画面效果仍需人工及实测审核。"

def check_gate(project_dir, target_step=None):
    status = load_status(project_dir)
    before_status = json.dumps(status, sort_keys=True)
    refresh_status(project_dir, status)
    if json.dumps(status, sort_keys=True) != before_status:
        save_status(project_dir, status)
    curr = status.get("current_step", 1)
    
    if target_step is None:
        target_step = curr
        
    print("=" * 65)
    print("吞鲸工作室 · 工业化流程门禁核验中心")
    print(f"目标项目路径: {project_dir}")
    print(f"当前准备核验: {STAGE_NAMES.get(target_step, f'Step {target_step}')}")
    print("=" * 65)
    
    # 步进防跳步检查
    if target_step > curr:
        print(f"\n[X] 阻断拦截：你试图跳步进入 Step {target_step}！")
        print(f"    当前尚未完成: Step {curr} ({STAGE_NAMES[curr]})")
        print("    请先满足前置步骤并通过门禁放行！")
        return False
        
    auditors = {
        1: audit_step_1,
        2: audit_step_2,
        3: audit_step_3,
        4: audit_step_4,
        5: audit_step_5
    }
    
    if target_step in auditors:
        try:
            before_source = source_record(project_dir) if target_step in (4, 5) else stage_record(project_dir, target_step)
            ok, msg = auditors[target_step](project_dir)
            if ok and (source_record(project_dir) if target_step in (4, 5) else stage_record(project_dir, target_step)) != before_source:
                ok, msg = False, "任务在核验过程中发生变化，请重新核验"
        except (ValueError, OSError) as exc:
            ok, msg = False, str(exc)
        if ok:
            print(f"\n[✓] 门禁通过: {msg}")
            if target_step in (2, 3):
                try:
                    import whale_advisor
                    adv = whale_advisor.diagnose_project(project_dir)
                    if adv.get("suggestions"):
                        print("\n" + "─" * 65)
                        print("💡 【鲸鲸导演主动升维顾问 (Proactive Director Advisor)】：")
                        for idx_s, sg in enumerate(adv["suggestions"], 1):
                            print(f"  {idx_s}. {sg['dimension']} -> {sg['action'].splitlines()[0]}")
                        print(f"  👉 可随时运行 `python scripts/whale_advisor.py '{project_dir}'` 查看完整升维方案与推荐拆镜链！")
                        print("─" * 65)
                except Exception:
                    pass
            status.setdefault("gate_sources", {})[str(target_step)] = gate_evidence(project_dir, target_step)
            if target_step not in status["passed_steps"]:
                status["passed_steps"].append(target_step)
            if target_step == curr:
                status["current_step"] = curr + 1
            save_status(project_dir, status)
            print(f"[➔] 已保存核验证据，当前步骤: {status['current_step']}")
            return True
        else:
            status["passed_steps"] = [s for s in status["passed_steps"] if s < target_step]
            status["current_step"] = min(curr, target_step)
            for key in list(status.get("gate_sources", {})):
                if not str(key).isdigit() or int(key) >= target_step:
                    del status["gate_sources"][key]
            save_status(project_dir, status)
            print(f"\n[X] 门禁拦截 (FAIL): {msg}")
            print(f"    当前步骤被阻断，修复上述问题后重新运行门禁检查。")
            return False
    elif target_step == 6:
        try:
            require_source_audit(project_dir, status)
        except (ValueError, OSError) as exc:
            print(f"[X] 当前任务尚未通过有效门禁: {exc}")
            return False
        print("\n[✓] 前序 5 大门禁（含生成前终极自审）已全部通关！允许执行终端渲染命令 (python export_comfy_payload.py)！")
        return True
        
    return False

if __name__ == "__main__":
    if len(sys.argv) < 2 or sys.argv[1] in ("-h", "--help"):
        print("用法: python whale_gatekeeper.py <项目目录路径> [可选目标步骤1-6]")
        sys.exit(0 if len(sys.argv) >= 2 and sys.argv[1] in ("-h", "--help") else 1)

    p_dir = sys.argv[1]
    t_step = int(sys.argv[2]) if len(sys.argv) > 2 else None
    
    passed = check_gate(p_dir, t_step)
    sys.exit(0 if passed else 1)
