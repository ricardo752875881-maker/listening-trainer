# Data Model: 精听工坊

**Feature**: [spec.md](../spec.md) | **Date**: 2026-10-27

本文件定义系统的持久化实体、字段、关系、状态机与校验规则。存储落地为可读 JSON 文件（每材料一个目录），字段命名采用 camelCase。

## 实体关系总览

```text
Material 1───* Turn 1───* Block(段落块) 1───* Sentence
Material 1───* ReviewItem（跨材料汇总于 review-queue.json）
Material 1───* ShadowingItem
Material 1───* Quiz
Settings（单例）          ImportJob（瞬态，运行时仅存内存）
```

## Material（材料）

| 字段 | 类型 | 校验 / 说明 |
|------|------|-------------|
| id | string | 生成时唯一（目录名） |
| title | string | 必填，1–200 字符，重命名即时生效 |
| audioFileName | string | `audio.<ext>`，ext ∈ mp3/wav/m4a/flac/ogg |
| durationSec | number | > 0，导入时由后端探测 |
| stage | enum | `learning`（默认）/ `reviewing` / `mastered` |
| audioOnly | bool | true = 对齐失败降级（FR-012）：仅播放可用，文稿交互禁用 |
| bestScore | number\|null | 0–100，测验成绩的历史最高 |
| engineUsed | string | 本次导入所用对齐引擎标识（新导入恒为 `wav2vec2`；旧材料可能保留 `faster-whisper`/`paraformer`） |
| playheadSec | number | 学习位置，实时持久化（FR-026） |
| createdAt / updatedAt | ISO8601 | |

**派生统计**（材料库卡片，FR-001，均由子实体计算，不冗余存储）：生词数 = word/phrase 类型 ReviewItem 数；没听懂句数 = notUnderstood 为 true 的句数。

## Turn（话轮）

| 字段 | 类型 | 说明 |
|------|------|------|
| id | string | |
| materialId | string | |
| index | number | 材料内顺序 |
| speakerName | string\|null | 无标签材料为 null |
| speakerNameZh | string\|null | 中文译名（如 `乔治`），解析自 `Georgie 乔治` |

## Block（段落块）

话轮内的渲染/译文挂载单位（FR-015/016、FR-007 修订）。

| 字段 | 类型 | 说明 |
|------|------|------|
| id | string | |
| turnId | string | |
| index | number | 话轮内顺序 |
| translationLines | string[] | 紧随该英文段落的译文行，原顺序拼接 |

## Sentence（句子）

| 字段 | 类型 | 校验 / 说明 |
|------|------|-------------|
| id | string | |
| materialId / turnId / blockId | string | |
| index | number | 材料内全局顺序（播放/测验按此排序） |
| text | string | 官方原文句子（按 `. ? ! ;` 切分） |
| aligned | bool | false = "未对齐"（FR-011、Clarifications 2026-10-27 Q1） |
| startSec / endSec | number\|null | 仅 aligned=true 时有值 |
| words | Array<{w, start, end}> | 逐词时间戳；aligned=false 时为 [] |
| notUnderstood | bool | 句尾「没听懂」图标开关状态（FR-020，2026-10-28 起为纯布尔，无原因/备注） |

**未对齐句约束**：`aligned=false` 时不得出现在测验抽题池、不得组成跟读片段、不支持单词点击跳转；文稿中正常显示并带"未对齐"标识。

## ReviewItem（复习条目）

全局复习队列元素（FR-038~044）。

| 字段 | 类型 | 校验 / 说明 |
|------|------|-------------|
| id | string | |
| type | enum | `word` / `phrase` / `sentence`（没听懂句） |
| text | string | 标记的词/短语/句文本 |
| meaning | string\|null | 释义，用户在标记模式下可选填（FR-019） |
| materialId / sentenceId | string | 来源 |
| contextText | string | 使用场景：所在官方原句（卡面展示，目标词高亮） |
| knownCount / reviewCount | number | ≥0，自评"认识/听懂了"累加 knownCount |
| intervalDays | number | ∈ {1,3,7,15,30}；新条目 = 1 |
| dueAt | date | 新条目 = 创建日 +1 天 |
| lastReviewAt | ISO\|null | |

**去重**：(materialId, sentenceId, text, type) 唯一；重复标记不产生新条目。
**移除**：仅手动删除（FR-044）与材料删除级联；无自动毕业。

**调度状态机**：

```text
[new: dueAt = createdAt + 1d]
  └─ 自评通过 → intervalDays 升一档（1→3→7→15→30，30 档后保持 30 循环）
  └─ 自评未通过 → intervalDays = 1，dueAt = +1d
```

**会话规则**（FR-039）：单次复习会话最多取 20 张 dueAt ≤ 今天的卡片，练完或中途结束即收尾，剩余明天继续到期。

## ShadowingItem（跟读片段）

| 字段 | 类型 | 校验 / 说明 |
|------|------|-------------|
| id | string | |
| materialId | string | |
| text | string | 可跨句、可含多个句子（修订四） |
| anchorStart / anchorEnd | {sentenceId, wordIndex} | 片段起止位置 |
| audioStartSec / audioEndSec | number | 由起止词逐词时间戳确定；跨句取首词 start / 末词 end |
| source | enum | `manual` / `llm` |
| status | enum | `active` / `ignored` / `removed` |

**约束**：片段覆盖范围内任何句子 `aligned=false` 时不可创建（FR-027）；忽略的 llm 片段不重复推荐（Edge Cases）；与既有 active 片段范围完全相同的去重。

## Quiz（测验）

| 字段 | 类型 | 说明 |
|------|------|------|
| id | string | |
| materialId | string | |
| status | enum | `in_progress`（暂存中）/ `completed`；题目生成即持久化，刷新/中断后可恢复继续（FR-030） |
| createdAt / completedAt | ISO8601 | |
| items | Array<{sentenceId, userInput\|null, correct\|null}> | userInput 在作答时即写入（草稿保留），完成后填 correct |
| correctCount / totalCount | number | 每句 1 得分点 |
| score | number | 0–100 = correctCount ÷ totalCount × 100 |

**抽题规则**（FR-029）：池 = aligned 且按优先级（没听懂 > 含生词/短语 > 随机）抽取，默认 10 句不足全出；判分归一化 = trim + 忽略大小写 + 忽略全部标点 + 全角转半角（Assumptions，2026-10-28）。
**流转**（FR-036/037）：score ≥ 90 → material.stage = `mastered`（bestScore 取最大）；< 90 → 展示错句，用户选择回学习/再测；已掌握重测只记成绩不降级。

## Settings（单例，settings.json）

| 字段 | 类型 | 校验 / 说明 |
|------|------|-------------|
| alignModel | enum | `base`（默认，wav2vec2-base-960h）/ `large`（wav2vec2-large-960h-lv60-self），强制对齐模型（FR-041） |
| llm | {provider, apiKey, model, enabled} | provider ∈ `openai`/`deepseek`/`kimi`（Clarifications Q4） |
| defaultSpeed | enum | 0.5 / 0.75 / 1.0（默认）/ 1.25 / 1.5 |
| showTranslationDefault | bool | 译文默认显示 |

## ImportJob（瞬态）

| 字段 | 说明 |
|------|------|
| id / stage / progressPct / cancelRequested | 阶段：`parsing`（文稿解析）→ `aligning`（wav2vec2 强制对齐）→ `done`/`cancelled`/`error` |
| 持久化 | 仅存内存；取消后无残留（Edge Cases） |

## 存储落地（待 research.md 确认后定稿）

- `data/settings.json`：Settings 单例。
- `data/review-queue.json`：全部 ReviewItem（跨材料汇总，便于到期查询）。
- `data/materials/<materialId>/`：`audio.*`、`material.json`（Material + Turn[] + Block[] + Sentence[] 嵌套）、`shadowing.json`、`quizzes.json`（含 in_progress 草稿）。
- 全量数据可读的纯文本/JSON，符合宪法"可读格式存储"。
- 容错（spec Edge Cases）：非法 JSON 启动时备份为 `.corrupt` 以空数据启动；单材料损坏仅该材料不可用。
