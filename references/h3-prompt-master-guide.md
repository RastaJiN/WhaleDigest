# MiniMax H3 官方提示词规范 × 吞鲸实战融合手册 (WhaleDigest v4.7.1)

> **官方真源锁定**：本手册直接融合 `MiniMax-AI/MiniMax-H3/.agents/skills/h3-prompt-writing`（锁定 commit `199b7d0e1fd95e7b3eafa8c15eca692534142427`），完整官方原件保存在 `references/h3-official/`（`SKILL.md`、`ref-en.txt`、`base-en.txt`）。
> **核心原则**：任何大模型（Claude / GPT / Gemini / DeepSeek）写 H3 提示词时，**禁止凭感觉手写格式**——必须严格按本手册规则，优先通过统一编译器 `scripts/whale_core.py` (`single_shot_prompt`) / `scripts/whale_h3_prompt.py` (`compile_h3_ref2va_prompt` / `compile_h3_base_prompt` / `compile_h3_container_prompt`) + 全集音色账本 (`VoiceRegistry` / `voice_bible.json`) 生成，再过 `whale_compiler.py` 与 `whale_gatekeeper.py` 强校验。

---

## 一、官方结构 × 吞鲸实战的明确分工

| 层面 | 权威依据 | 硬规则 |
|---|---|---|
| **三种模式与顶层结构** | 官方 `ref-en.txt` / `base-en.txt` | **Ref2VA 六段式**严格固定顺序且各仅一次：`subject_definitions` → `summary` → `retention_analysis` → `detailed_description` → `overall_soundscape` → `non_diegetic_music`；**Base/首帧/首尾帧三段式**用 `integrated_multimodal_description` → `overall_soundscape` → `non_diegetic_music`；**多镜容器 (4–15s)** 在 `subject_definitions` 对齐 `<Picture N>` 起始秒并在 `detailed_description` 用 `[Shot N] At 00:xx.xxx` 分段。前面禁止任何前言/标题/备注。 |
| **保留强度与动作/姿态隔离** | 官方 `ref-en.txt` §4 + 吞鲸 v4.7.1 | 视觉素材用 `fully_preserved` / `partially_preserved` / `attribute_transfer` / `weak_reference`；音频用 `fully_copy` / `partially_copy` / `reference` / `weak_reference`；`retention_analysis` 须标注 `(appears in [Shot N])`。动作注入须按体位姿势分支：坐/跨/跪/仰卧体位禁止混入站姿脚部重心词（如 `weight shift between the feet`），`Camera:` 仅在单行出现一次；实拍模式启 `DE_OIL` 压油，3D/2D/水墨制作形态卡关闭 `35mm` 与皮肤摄影词。 |
| **动作真源与全肯定语法** | 吞鲸 v4.7.1 | `references/whale_poses_matrix.json` 全部条目须带非空 `category`、全肯定物理描写（零 `no/not/never/without/zero`、零网站人物占位名 `Woman A/Man A`、英文段零汉字）；正剧仅放行通用调度原语（`category="staging"`/`"通用"`），其余动作一律由 `whale_pose_guard.py` 拦截。 |
| **槽位编号与角色解耦** | 官方 `ref-en.txt` §2 + 吞鲸 v4.7.1 | `ref_images` 支持 **1–9 张**自由开关；**绝不写死 1=女 / 2=男 / 3=场景**。3 人同框、群像、单人反打、道具特写放第几槽，提示词就写 `<Picture N>`，并定义为 `<Subject M>`。`<Subject N>` 是视觉主体，`(Sx)` 是全局说话人 ID，**二者不必相等**（例如 `<Subject 3> (S1)` 完全合法）。 |
| **音色锚点与任务源正则兼容** | 吞鲸 v4.7.1 | 当将 `VoiceRegistry` 音色指纹拼入 `SPEECH:` 行时，必须置于 `only <Subject N> (Sx) says:` 之前（如 `From 1.10s to 4.47s, in <timbre>, only <Subject 2> (S2) says: <d>[Chinese]...</d>`），严禁插在 `(Sx)` 与 `says:` 之间，确保 `whale_task_source.py` 与 `whale_shot_facts.py` 对说话人和逐字台词的严格锚定不被破坏。 |
| **CFG=1.0 正向全肯定** | 吞鲸实片经验 | `Node 328 = ConditioningZeroOut` 导致负向清零，因此正向提示词**严禁出现否定词配衣物/字幕词根**（`no garment / no shirt / no underwear / no subtitles / Do not generate subtitles`），必须 100% 写正面可见物理状态。 |
| **语言分工** | 官方 `ref-en.txt` + 吞鲸 | 六段正文全英文；**只有 `<d>[Chinese]逐字台词</d>` 内与画内真实招牌文字保留中文**。 |

---

## 二、6 大高频场景标准写法（直接套用，绝不写错）

### 场景 1：空镜（`shot_mode = "empty_shot"`）
- **参考图**：只挂场景/物体图（1～2 张），**绝不绑定人物图**。
- **动作描写**：只写环境、光线移动、风吹、蒸汽、水流、物体静置与受控运镜；**绝不虚构人物、不写嘴部、不强塞 `SPEECH:`**。
- **标准样板**：
```text
subject_definitions:
<Subject 1> is the misty cedar forest path at dawn, anchored in <Picture 1>.
summary: [reference generation] A quiet establishing view of <Subject 1> as morning fog drifts between the cedar trunks.
retention_analysis:
<Subject 1> (appears in [Shot 1]): weak_reference - tree spacing, damp earth texture, and cool dawn light from <Picture 1> are retained while the camera glides forward.
detailed_description:
Realistic 35mm live-action cinema with soft dawn mist.
Camera: wide architectural establishing shot; the camera pushes in with small amplitude at slow speed.
[Shot 1] Mist drifts slowly across <Subject 1> as sunbeams break through the upper canopy and pine needles sway in a faint morning breeze.
overall_soundscape: Distant morning birdsong, faint wind rustling through cedar branches, and soft damp forest ambience.
non_diegetic_music: N/A
```

---

### 场景 2：画内对白 + 多人同框防错口型（`speech.mode = "on_screen"`）
- **铁律**：当画面内有多张正脸时，H3 容易把声音对到最显眼的正脸上。因此**必须同时写两句**：
  1. 说话人标明 `<Subject N> (Sx)` + **专属英文音色指纹** + `speaking on-screen` + 发声动词 + `<d>[Chinese]逐字台词</d>`；
  2. **紧跟其后点名所有画内非说话人闭嘴**：`<Subject M> stays silent; lips remain completely closed.`
- **标准样板（3 人同框，只有第 3 槽的张大爷说话）**：
```text
SPEECH: From 0.50s to 2.30s, only <Subject 3> (S3), speaking on-screen in a gruff, raspy elderly male voice with earthy texture and lively colloquial rhythm, with defensive impatience, asks: <d>[Chinese]熏一串腊肉怎么啦？</d>. <Subject 1> and <Subject 2> stay silent; lips remain completely closed.
```

---

### 场景 3：画外音（`speech.mode = "off_screen_vo"`）
- **适用**：说话人**不在当前镜头画面里**（如拍听者反应、拍走廊/空镜、拍道具特写，另一人在画外说话）。
- **官方精确句式**（`base-en.txt` §4.4）：必须使用 **`says in an off-screen voiceover`**，并立刻声明画内人物双唇紧闭 `while <Subject 1>'s lips remain completely closed.`（若为空镜无画内人物则不必写闭嘴）。
- **标准样板**：
```text
SPEECH: From 0.60s to 2.10s, The off-screen speaker (S2), in a deep, resonant mature male baritone with slight gravel and calm authority, with quiet warning, says in an off-screen voiceover: <d>[Chinese]把门关上，别让人看见。</d> while <Subject 1>'s lips remain completely closed.
```

---

### 场景 4：内心独白（`speech.mode = "inner_monologue"`）
- **适用**：角色在画内（如盯着窗外/发呆/沉默对峙），观众听见他/她的**心里话**，本人**绝对不能张嘴**。
- **关键要点**：
  1. 声源 ID 仍用该角色本人的全局 `(Sx)` 和专属音色指纹（绝不换声线）；
  2. 明确标明 `heard as quiet internal thoughts` + 官方 **`says in an off-screen voiceover`**；
  3. 紧接台词后锁定 `while <Subject 1>'s lips remain completely closed throughout the internal monologue.`。
- **标准样板**：
```text
SPEECH: From 0.50s to 2.60s, <Subject 1> (S1), in a soft, slightly breathy young female voice with warm midrange resonance heard as quiet internal thoughts, in a hushed reflective cadence, murmurs in an off-screen voiceover: <d>[Chinese]这把钥匙，他根本没打算还给我。</d> while <Subject 1>'s lips remain completely closed throughout the internal monologue.
```

---

### 场景 5：独立旁白（`speech.mode = "narrator"`）
- **适用**：全剧画外旁白/解说（无论画面是空镜还是人物戏）。
- **关键要点**：
  1. 旁白必须分配**独立的全局声源 ID**（建议固定 `S9` 或最高号），**绝不与任何角色的 `S1/S2/S3` 共号**；
  2. 绑定中立播音感音色（如 `narrator_calm`），与剧中所有角色声线彻底拉开；
  3. 画面有人物时，一律追加 `while <Subject ...>'s lips remain completely closed.`。
- **标准样板**：
```text
SPEECH: From 0.40s to 2.80s, the narrator (S9), speaking in a steady, neutral off-screen narrator voice in a warm mid-low register with clean broadcast articulation and unhurried documentary pacing, calmly, states in an off-screen voiceover: <d>[Chinese]冬季盆地逆温像一只大锅盖，把浓烟牢牢压在小区上空。</d> while <Subject 1>'s lips remain completely closed.
```

---

### 场景 6：有人物但无对白镜（`speech.mode = "none"`）
- **规则**：不写任何 `<d>` 标签，不写多余的 `SPEECH:`；动作段正常写人物呼吸、微表情与视线，声音全部归入 `overall_soundscape`，无配乐时固定 `non_diegetic_music: N/A`（严禁省略，否则 H3 会自发乱配乐）。

---

## 三、全集人物音色绑定铁律（依赖 H3 原生语音时必做）

因为我们依赖 H3 自身直接生成对白语音，**如果提示词里只写 `says:` 而不锚定音色，或者两个角色用了雷同描述，同一集里每个人的声音就会随机漂移甚至撞车**。

### 强制做法：项目根目录建立 `voice_bible.json`
开机写提示词前，为本集**所有会发声的角色 + 旁白**注册唯一 `speaker_id` + 差异化英文音色指纹（6 维度拉齐：**性别 + 年龄段 + 音高音区 + 声带质感 + 语速节奏 + 语气特色**）：

```json
{
  "schema": "whale-voice-bible-v1",
  "voices": [
    {
      "character": "林川",
      "speaker_id": "S1",
      "timbre": "an earnest, bright young male voice in a medium register with crisp articulation and energetic steady pacing"
    },
    {
      "character": "赵斌",
      "speaker_id": "S2",
      "timbre": "a deep, resonant mature male baritone with slight gravel, calm authority, and measured delivery"
    },
    {
      "character": "张大爷",
      "speaker_id": "S3",
      "timbre": "a gruff, raspy elderly male voice with earthy texture, heavy breath, and lively colloquial rhythm"
    },
    {
      "character": "欢宝",
      "speaker_id": "S4",
      "timbre": "a nimble, animated high-pitched youthful voice with playful crisp inflection and bouncy rhythm"
    },
    {
      "character": "旁白",
      "speaker_id": "S9",
      "timbre": "a steady, neutral off-screen narrator voice in a warm mid-low register with clean broadcast articulation and unhurried documentary pacing"
    }
  ]
}
```

### 门禁自动拦截（Gate 4 & Gate 5 已接入）
1. **声源串号拦截**：同一角色在不同镜头里用了不同 `(Sx)` 直接 FAIL；
2. **音色撞车拦截**：`voice_bible.json` 中两个不同角色共用同一个 `(Sx)` 或完全雷同的 `timbre` 描述直接 FAIL；
3. **画外音/独白漏闭嘴锁拦截**：含 `off-screen voiceover` 且画面内有人物但漏写 `lips remain completely closed` 直接 FAIL。

---

## 四、统一代码入口（所有大模型共用）

```python
from whale_h3_prompt import VoiceRegistry, compile_h3_ref2va_prompt

vreg = VoiceRegistry([
    {"character": "林川", "speaker_id": "S1", "preset": "young_male_earnest"},
    {"character": "赵斌", "speaker_id": "S2", "preset": "mature_male_deep"},
    {"character": "张大爷", "speaker_id": "S3", "preset": "elder_male_raspy"},
    {"character": "旁白", "speaker_id": "S9", "preset": "narrator_calm"},
])

prompt = compile_h3_ref2va_prompt({
    "shot_mode": "standard",
    "style": "Pixar-style 3D animated cinema with crisp morning daylight",
    "slots": [
        {"picture": 1, "kind": "character", "name": "林川", "desc": "the young ranger in navy uniform"},
        {"picture": 2, "kind": "character", "name": "张大爷", "desc": "the elderly resident in quilted jacket"},
        {"picture": 3, "kind": "scene", "desc": "the sunlit courtyard smoking corner", "retention": "weak_reference"},
    ],
    "framing": "medium two-shot",
    "camera": "arc_subtle",
    "summary": "<Subject 1> stops beside the barrel while <Subject 2> turns around holding a pine branch in <Subject 3>.",
    "action": "Inside <Subject 3>, <Subject 1> raises one hand calmly while <Subject 2> turns from the barrel holding a pine branch",
    "speech": {
        "mode": "on_screen",
        "speaker_subject": 2,
        "character": "张大爷",
        "verb": "asks",
        "delivery": "with lively impatience",
        "text": "熏一串腊肉怎么啦？",
    },
    "soundscape": "Crackling wood embers and light courtyard breeze.",
    "apply_de_oil": False,
}, voice_registry=vreg)
```

---

## 五、来自实片 SOP 的 6 条黄金避坑铁律（已融合）

1. **三档视听呼吸时长法则**（禁止全片统一秒数）：
   - **爆发动作 / 关键道具微距标点镜**：`2.0 ~ 3.0s`（干脆有力，防动作软化）；
   - **行进走位 / 空间压迫镜**：`3.5 ~ 4.5s`（给足位移与环境交代）；
   - **戏剧对峙 / 情绪悬停焦点镜**：`5.0 ~ 8.0s`（给足呼吸感与情绪发酵）。
2. **0.00s 动量继承（Kinetic Continuity）**：
   - 连续动作切镜必须声明动作已在运行中（`At 0.00s, already in continuous motion inheriting the momentum of the previous shot`），禁止开局站定发呆 1 秒才起手（注意：遵循 CFG=1.0 全肯定原则，写 `continuous unbroken motion`，不写 `NO freeze`）。
3. **行进/出门矢量一致性（防“出门变进门”）**：
   - 角色上一镜背身向门外走时，下一镜必须显式写清 `rear tracking shot moving forward along the depth of the hallway`，严禁只写模糊的 `camera tracks forward`，防止模型反转角色朝向变成迎面走回。
4. **014B 非床场景材质排他锁 + 声场去床垫词**（已接入 Gate 5 机器拦截）：
   - 在工业铁桌、办公台、餐桌、椅子、走廊等非床场景拍低姿态/俯身动作时，正向必须写清硬材质纹理（如 `rigid scratched steel tabletop, cold industrial surface`），且**`overall_soundscape` 里绝对不能残留 `mattress` / `bedsheet` / `pillow` / `bed creak`**（否则模型会把铁桌脑补成软床）。
   - ⚠️ 注意与旧版 SOP 的关键升级：因为现在 H3 工作流是 `CFG=1.0`（`ConditioningZeroOut`），**不再在正向提示词里写 `strictly NO bed / NO subtitles`**，全部改为 100% 全肯定硬材质与干净画面描述。
5. **014D 极近景背景防棚拍化（15%~20% 浅景深空间标桩）**：
   - 特写/微距镜头禁止让背景退化成纯灰/纯白无影棚，必须在正向保留 15%~20% 的具体浅景深空间标桩（如模糊的窗帘、门框、台灯暖光、混凝土墙纹理、监控绿光等）并维持纵深光影。
6. **关键道具独立微距升格镜 & 字符/门牌先做母版**：
   - 钥匙、房卡、公文包、证据等推进剧情的核心道具，单独拆 2.0~2.5s 微距慢动作特写，不与全身大动作挤在同一镜；含门牌号/车牌/文件标题的镜头必须先出清晰物理母版图进参考槽，成片首尾帧逐字复核。

