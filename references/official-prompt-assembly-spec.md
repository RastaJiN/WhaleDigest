# H3 多参考视频：单镜送模格式

适用范围：宝典现用的 `MiniMaxH3ReferenceToVideo`（Ref2VA）工作流。这里规范交给模型的一个字符串，不是项目 Markdown 的排版，也不是文生视频或首尾帧模式的通用模板。

## 谁决定内容

剧本确定场次、物件、事件、说话人和台词原文。采用分镜确定谁入画、机位、起止状态及与下一镜的衔接；动作确认卡给出已采用的动作顺序、发起者、支点、节奏和退场。提示词阶段只翻译，不按性别、说话顺序或参考图槽位推断站位，不补家具或台词。

`whale_core.single_shot_prompt` 装配正文。`视频提示词.md` 是审阅件；所选批次的 `batch_shots[i].prompt` 才是工作流输入。项目标题、导演批注、动作库 ID、确认卡、Markdown 围栏和后期单都留在输入之外。

## 一次输入的六个字段

| 字段（顺序固定，各一次） | 在本镜写什么 |
| --- | --- |
| `subject_definitions` | 本镜人物、物件、场景和真实参考的关系。`<Picture N>` 是素材，`<Subject N>` 是定义后复用的主体。 |
| `summary` | 本镜发生什么，不重复台词或预演下一镜。 |
| `retention_analysis` | 每份参考要保留什么。场景可以保留布景与光线，不必复制广角构图；不得给既定身份另换参考图。 |
| `detailed_description` | 实际取景、动作及可见起止状态；真实对白只在这里。 |
| `overall_soundscape` | 环境声、拟音或静默，不重复整句台词。 |
| `non_diegetic_music` | 无生成配乐写 `N/A`。后期选用的乐曲文件、时段和确认记录不进入此段。 |

**宝典本地约束**：画面段单列一个 `Camera:`；有对白再单列一个 `SPEECH:`。在同一行标发声主体和动词，随后接 `<d>[语言]逐字台词</d>`。引文内不嵌 `<Picture N>`、`<Audio N>`、`<Video N>` 或 `<Subject N>`，也不把指导语当台词。普通词句（如演员说“Picture 1 是个文件名”）不是标签。视觉主体和声源是两种编号；有显式绑定就沿用。只拍听者时保持原画外声源，不补同号演员的脸；空镜无需写嘴部动作。

当前工作流默认原生音频，不把未接入的录音或视频当作参考。只引用本镜实际挂载的素材；扩展槽空着不等于可用。单镜允许挂载 1–9 个有序参考图（传统双人镜使用前三槽；单人反打、道具微距或独立角色层可仅挂载 1–2 槽，且不得强求 `<Picture 3>`，运行器自动断开未使用的 `ref_image_*` 端口）。道具需要额外图片时使用扩展槽，不顶掉场景图。

**CFG=1.0 正向提示词硬边界**：`Node 328 = ConditioningZeroOut` 将负向清零，因此正向提示词中严禁用否定词配衣物或字幕词根（如 `no garment / no shirt / no underwear / no subtitles / Do not generate subtitles`），因为正向里的名词词根反而会唤醒对应元素；必须改用 100% 全肯定物理/视觉状态描写（如裸体段只写可见裸肌与接触状态，字幕靠干净底图而非正向禁令）。同时严禁把未裁切的多视图拼版（三视图/九宫格）直接塞进单角色镜头参考槽。

## 可校验的完整请求：画面只拍听者

本例分镜已规定柜台前只拍听者，另一人在画外说“等等。”。它不是全剧固定站位。围栏用于工作文档排版，不随正文发送。

```text
subject_definitions:
<Subject 1> is the clerk from <Picture 1>.
<Subject 3> is the service counter from <Picture 3>.
summary: [reference generation] The clerk pauses on hearing a voice off camera.
retention_analysis:
<Subject 1>: fully_preserved for facial identity from <Picture 1>.
<Subject 3>: partially_preserved for the counter surface and window light from <Picture 3>.
detailed_description:
Camera: A static chest-up close-up holds on the clerk.
[Shot 1] The camera holds; <Subject 1> stops folding the receipt, keeping it in the same hand.
SPEECH: From 1.00s to 2.00s, only the narrator (voice S2) says in an off-screen voiceover: <d>[Chinese]等等。</d>. The clerk's lips remain closed.
overall_soundscape: Paper rustles, then only the room tone remains.
non_diegetic_music: N/A
```

## 阻断、提醒与实片验收

- **阻断**：必填段缺失、重复或乱序；引文夹素材标签或与发声锚点分行；引用未定义主体、改绑已声明身份、使用未挂载的槽位；实际任务与已确认导出不符。`Goal & Audio Contract`、`Voice discipline`、`[Visual Constraints]`、`=== NEGATIVE ===` 均非送模尾块。本地工作流还拒绝正向字幕诱导词及台词外汉字；这是本地生产约定，不是所有 H3 模式的语言上限。
- **提醒／导演审阅**：分号、手势幅度、反应时长等不代替已采用分镜；木板确实可以有竖向纹路，不因出现 “vertical lines” 就推断画面要叠辅助线。“两个可见细节、约 1.5 秒落定”是近景反应的可选拍法，不是每镜通过条件。
- **只检查，不改写**：Gate 4、离线导出、工作流组装检查当前逐镜正文。运行器还核对模型实际读取的文本节点，不接受旧模板里的指令。校验器升级后重新验门禁，不等于要求重选动作。
- **实片另验**：发声时看片确认谁张嘴、有没有烫字，连续播放相邻镜检查接戏。检查器不能从文本保证脸部稳定，也不负责擦除原片已有字幕。后期字幕、普通字卡和配乐见[后期交付](post-delivery.md)。
