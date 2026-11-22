# 分镜体位确认与离线导出

可直接导入有场次、段落标题和署名对白的 Markdown 原稿，也可逐镜写稳定镜号。标题与概述只解释正文，不生成额外镜头；导入不改写原稿。优先保留 `<d>…</d>` 中的原句；同样支持明确的加粗/引号对白。说话人按本场实名映射为参考槽，不按发言顺序猜；证据不足时可在项目 `角色映射.json` 提供“姓名 → S1/S2”。不同场的同一槽位不代表同一演员。运行 `python scripts/whale_pipeline.py 项目目录 --dry`。**退出 3 是待确认，不是已导出。** 普通站立、对白中提到体位、空镜和明确的非亲密调度不出体位卡。体位 ID 或完整矩阵名是明确指定；宽泛词只给候选，房间陈设不补动作。普通镜头留在剧本原位，不随亲密镜头移到片头或片尾。

## 在源镜头声明，或在同一张卡确认

```text
镜1：direct_entry；foreplay=none；main_pose=lap_sit。
镜2：nonlinear；foreplay=not_in_shot；女上坐姿。
镜3：nonlinear；foreplay=already_established；solo_action=toy_tease。
镜4：foreplay=kiss_fondle；main_pose=lap_sit；solo_action=pillow_hump；order=solo_action>main_pose>foreplay。
```

- `entry_mode`：`linear`（默认，照原文顺序，不要求前戏）、`direct_entry`（直接从可见动作开始）、`nonlinear`（依确认顺序切入）。`foreplay_mode` 区分 `in_shot`（有已选前戏类型）、`none`（没有）、`not_in_shot`（不在本镜）、`already_established`（前情已建立，不重演）。后面三种都是元数据，**不是动作 ID**。省略的角色类型不自动生成；要增加本镜没写的动作，先改源镜头。
- 打开 `分镜体位选择.json`；在 `steps[i].选择` 填候选 ID；单步也兼容卡顶层 `选择`。`foreplay`、`main_pose`、`solo_action`、`selected_order` 是从实际选择投影出的有序列表，不是另一套动作输入。`女上坐姿` 的五个 `main_pose` 候选是 `lap_sit`、`lap_sit_back`、`cowgirl`、`cowgirl_upright`、`reverse_cowgirl`；同卡选一次。`python scripts/whale_pose_choice.py` 可查完整矩阵。双人自定义配方见 [project-pose-recipes.md](project-pose-recipes.md)。
- `transitions_order` 是所有步骤从 0 起的索引排列。默认照原文，只有明确的排列才改顺序。每步填写 `initiator`、`pace`、`facing`、`support`、`load`，无额外要求用 `NA`；物理约束与选定姿态不能互相矛盾。`pre`/`post` 取相邻可见步骤，第一步没有过渡。后一步选 `cut`（另一个请求）或 `one_take`（同一个请求内连续完成，不另切机位）。`scene_end` 选 `none`、`hold` 或 `exit`；选择 `exit` 时注明退场者 `S1`、`S2` 或 `both`。卡内 `errors` 必须清空，超出单次请求时长的已决动作不得靠重复退场来承载对白。

**区分角色缺席、动作标签和待选项。** 本镜明确只有单人动作时，可在源镜写 `main_pose=none`；`none` 不会送进动作库查找，也不能在一张模糊主体位卡上用于跳过确认。同镜把一个角色类型既声明为 `none` 又指定具体动作，是冲突。校验免打扰规则时请用成对用例：如“只有言语挑逗，无身体接触”或“单人动作：他站着看表”不应触发；同镜随后若另写未定的可见亲密姿态，仍应只为后一个动作出候选。不能因为前半句是文戏就屏蔽整镜。

## 验收而非渲染

保存选择后重跑同一流水线。审阅 `已决分镜.json` 的 `cards` 和 `shots[].action_steps`，与 `批量任务.json` 的 `storyboard_cards` 和各请求的 `action_steps` 对照；`action_decision` 是该请求的末步。顺序、场次收尾和逐步物理事实要在实际 `detailed_description` 中核对，而不是在音乐字段或仅在报告里查关键词。`视频提示词.md` 中的代码块应逐字对应任务 prompt，机位仍有独立 `Camera:` 行。

`.whale_pose_plan.json` 是机器收据，不要手改。改动某镜原文/场景会使该镜之前的人工选择失效。剧本、选择文件、执行分镜、最终 prompt 或所用本地配方已变更时，旧批次不能直接核验放行。已确认的项目不接受用另一条 `--chain` 或节奏覆盖重猜亲密动作。可运行 `python scripts/whale_compiler.py 项目目录/视频提示词.md` 和 `python scripts/export_comfy_payload.py 项目目录 --offline` 分别检查 Markdown 与实际任务；后者要求当前 Gate 1–5 的证据，且不连接 ComfyUI。离线通过不代表模型可用或画面质量合格。

回归时用两份字节一致的原稿副本：一份保留原始未决卡；另一份明确标为 TEST ONLY，单独填写选择和提供测试图。分别记录退出码。用源场次、说话人和逐句原文顺序对账冻结分镜及实际 `batch_shots[].prompt`，不要用台词集合或报告里的关键词代替。`cast`、`dialogue` 与有序 `ref_images` 可核对实名和槽位；真实项目须提供其实际引用的图片，不用同槽的其他角色母版顶替。
