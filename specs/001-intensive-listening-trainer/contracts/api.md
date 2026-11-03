# API Contract: 精听工坊后端

**消费方**: 本机前端 SPA（`frontend/`）| **传输**: HTTP/JSON + SSE（进度）| **Base**: `http://localhost:8000`

错误约定：`400` 参数/校验失败（body: `{detail}`）；`404` 不存在；`409` 冲突（重复标记、范围含未对齐句等）；`502` 上游失败（对齐模型/大模型）。所有时间秒（float），日期 ISO。

## 材料 Materials

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/materials` | 材料库卡片列表 |
| GET | `/api/materials/{id}` | 全量学习数据：material + turns[]（speakerName/Zh）+ blocks[]（translationLines）+ sentences[]（含 words 时间戳、notUnderstood）+ shadowingItems[] |
| PATCH | `/api/materials/{id}` | body: `{title?, stage?, playheadSec?}`；stage ∈ learning/reviewing/mastered（支持任意手动回退） |
| DELETE | `/api/materials/{id}` | 级联删除复习条目/跟读/测验记录；音频与目录清除 |
| GET | `/api/materials/{id}/audio` | 音频流（HTTP Range 支持，供 `<audio>` seek/拖动）；仅音频模式下此端点照常可用 |
| POST | `/api/materials/{id}/retry-transcribe` | 对仅音频模式材料粘贴文稿重试强制对齐（body: `{transcript}`），成功后补齐文稿数据，失败 502 保持 audioOnly |

`GET /api/materials` 响应：`[{id, title, durationSec, stage, bestScore, stats:{vocab, notUnderstood}, createdAt}]`

## 导入 Import（两步：解析预览 → 启动）

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/import/parse` | body: `{transcript}` → 结构预览 `{speakers:[{name, nameZh}], turnCount, blockCount, translationLineCount, turns: 预览结构}`（FR-007/008，不落库） |
| POST | `/api/import/start` | multipart: `audio`, `title`, `transcript` → `{jobId}`；后台依次执行 parsing（文稿解析）→ aligning（wav2vec2 强制对齐，官方文稿逐词钉到音频）；对齐失败时材料按"仅音频模式"降级入库（FR-012） |
| GET | `/api/import/jobs/{jobId}` | 轮询查询进度：`{stage, progressPct, materialId?, audioOnly?}`；任务在服务端常驻，页面关闭重开后可继续查询（FR-010）；`done` 时返回 materialId |
| POST | `/api/import/jobs/{jobId}/cancel` | 取消并清理临时文件（不入库、无残留） |

## 学习标记 Markings（创建复习条目 / 句子状态）

标记交互：学习界面「标记模式」开关开启后前端进入划词流程（关闭时点击单词为跳转，见下）；所有标记接口均要求标记模式语义由前端控制，后端仅负责数据。

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/materials/{id}/sentences/{sid}/vocab` | body: `{text, wordStart, wordEnd, type: word\|phrase, meaning?}` → 创建 ReviewItem（去重；释义可空） |
| DELETE | `/api/materials/{id}/sentences/{sid}/vocab` | body: `{text, type}` → 删除对应 ReviewItem（即文稿上的取消标记路径） |
| PUT | `/api/materials/{id}/sentences/{sid}/not-understood` | body: `{marked: bool}` → 置/取消没听懂标记；置位时创建 ReviewItem(sentence)，取消时删除（无 reason/note 字段） |

## 测验 Quiz（无状态判分）

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/materials/{id}/quiz/generate` | body: `{count=10}` → 服务端按优先级抽题（没听懂 > 含生词/短语 > 随机；排除未对齐句），创建持久暂存的测验草稿，返回 `{quizId, items: [{sentenceId}]}`（FR-030，刷新可恢复） |
| GET | `/api/quiz/{quizId}` | 恢复未完成的测验：`{items, answers}`（已答内容保留） |
| POST | `/api/materials/{id}/quiz/submit` | body: `{quizId, items: [{sentenceId, userInput}]}` → 归一化判分（忽略大小写/首尾空格/全部标点/全角转半角），完成测验并返回 `{correctCount, totalCount, score, results: [{sentenceId, userInput, correct}], material: {stage, bestScore}}`；≥90 流转 mastered（FR-032/033） |

## 跟读 Shadowing

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/materials/{id}/shadowing` | 清单（active/ignored） |
| POST | `/api/materials/{id}/shadowing` | body: `{text, anchorStart:{sentenceId, wordIndex}, anchorEnd:{...}, source: manual}`；范围含未对齐句 → 409（FR-027） |
| DELETE | `/api/materials/{id}/shadowing/{sid}` | 移除 |
| POST | `/api/materials/{id}/shadowing/{sid}/ignore` | 忽略推荐（不再重复出现） |
| POST | `/api/materials/{id}/shadowing/recommend` | 大模型生成候选 `{candidates: [{text, anchorStart, anchorEnd}]}`；未配置 → 400（FR-028，手动触发） |

## 全局复习队列 Review Queue

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/review/due` | 返回今日到期数与本次会话卡片（≤20 张，FR-039/FR-042）：`{count, items: ReviewItem[]}` |
| POST | `/api/review/items/{rid}/rate` | body: `{passed: bool}` → 间隔重复调度（FR-042：通过升档 1→3→7→15→30 循环，未通过重置 1 天） |
| GET | `/api/review/items` | query: `materialId?, type?, sort=familiarity` → 总览（FR-043） |
| DELETE | `/api/review/items/{rid}` | 手动删除（唯一移除方式） |

## 设置 Settings

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/settings` | 返回设置（apiKey 掩码显示） |
| PUT | `/api/settings` | 全量更新 |
| POST | `/api/settings/test-llm` | 连通性测试 → `{ok, message}`（FR-043） |
| GET | `/api/models/align-status` | wav2vec2 对齐模型下载状态 → `{models: {base: {status, error}, large: {...}}}`，status ∈ downloaded/not_downloaded/downloading/error（FR-042） |
| POST | `/api/models/align/{size}/download` | 后台预下载对齐模型（size ∈ base/large） |

ReviewItem 结构见 [../data-model.md](../data-model.md)。
