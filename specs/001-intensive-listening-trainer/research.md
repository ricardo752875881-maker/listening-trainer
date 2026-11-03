# Research: 精听工坊技术选型

**Feature**: [spec.md](../spec.md) | **Date**: 2026-10-27 | **Phase 0 产物**

每个决策按 "Decision / Rationale / Alternatives considered" 记录。规格中的 NEEDS CLARIFICATION 已全部消解。

## R1. 后端框架与运行时

**Decision**: Python 3.11+ / FastAPI（Starlette ≥ 0.49.1）+ uvicorn；导入进度采用**轮询**（`GET /api/import/jobs/{id}`）；转写长任务用 `asyncio.create_task` + `task.cancel()` 实现取消。

**Rationale**: 本机单用户但有两个硬需求——音频 Range 流式（进度条拖动/单句循环）与长任务进度+取消。Starlette `FileResponse` 自 0.39 起原生支持 HTTP Range（≥0.49.1 修复 CVE-2025-62727）；ASGI 异步模型下取消即取消协程。进度推送 2026-10-28 按用户决策从 SSE 改为轮询：任务状态在服务端常驻，前端定时查询即可，页面关闭重开后自然恢复查看，实现与调试更简单（SSE 的断线重连与连接管理对单机场景属多余复杂度）。FastAPI 属轻量 ASGI 框架，不违反宪法"禁止重量级框架"。

**Alternatives**: SSE（单向推送更快但连接管理复杂，已被轮询取代——单机本地延迟无感）；WebSocket 双向过重；Flask（同步模型，长任务需另起线程，取消要自拼）；`http.server`（无路由/并发/Range，维护最贵）。

## R2. 转写引擎（可插拔 Provider）

> **2026-11-03 修订**：本决策已被取代。转写引擎（faster-whisper / Paraformer）整体退役，
> 导入改为 **wav2vec2 CTC 强制对齐**（`core/forced_aligner.py`，官方文稿直接钉到音频，
> 本机离线），difflib 比对与 LLM 对齐精修一并移除。保留本节作为历史记录。

**Decision**: 抽象 `Transcriber` Provider 接口，统一输出 `words[]`（毫秒 start/end）格式。本地默认 **faster-whisper**（`word_timestamps=True`），云端可选 **阿里百炼 Paraformer**（`paraformer-v2` 异步任务，结果含逐词 begin/end_time）。

**Rationale**: faster-whisper 内建 DTW 逐词时间戳，官方 CPU 基准 small/int8 ≈ 7.6 倍实时率（10 分钟音频约 1.5 分钟出稿），满足"句子对齐+单词跳转"精度；Paraformer 文件转写返回 sentences→words 毫秒级时间戳，两条路线功能完全对齐，云端只是备选引擎而非降级路径。

**Alternatives**: 仅本地（云端需求来自规格 FR-045/047，不能砍）；WhisperX/stable-ts 强制对齐（见 R4，过重且与 CTranslate2 链不兼容）。

## R3. 文稿-ASR 对齐算法

**Decision**: `difflib.SequenceMatcher(autojunk=False)` + 双侧统一归一化（小写、NFKC、Unicode 标点切分、缩写展开 I'm→I am、数词 fifty↔50）。opcodes 仅用于把官方句子词块映射到 ASR 词时间戳（起止时间 + 逐词时间戳）；无法映射的句子标记"未对齐"。**2026-10-28 修订**：差异分析（重点句判定、keyWords、不符告警）按用户决策整体移除，导入管线只保留"转写 + 对齐"。

**Rationale**: 时间戳由转写提供，对齐本质是"两个词序列的匹配"，几百词规模 SequenceMatcher 毫秒级、零依赖、引擎无关（本地/云端输出统一走同一对齐管线）。归一化保证口语缩读、标点差异不影响映射质量。`autojunk=False` 必设——默认会把 the/and 等高频词当 junk 跳过导致对齐错位。

**Alternatives**: 自实现 Needleman-Wunsch（全局最优，若实测重复句式下贪心错位明显则切换，约 50 行可测，作为后备）；stable-whisper（对音频强制对齐，与 faster-whisper 输出链不兼容）；WhisperX（拖入 torch + 数百 MB 模型，单机过重）。

## R4. 大模型接入（跟读推荐）

**Decision**: `openai` Python SDK + 三家预设服务商（OpenAI / DeepSeek / Kimi），均为 OpenAI 兼容 Chat Completions；设置页存 provider/apiKey/model；用户点击「获取推荐」时后端拼接文稿文本调用（手动触发，Clarifications Q2）。

**Rationale**: 三家均提供 OpenAI 兼容端点，一个 SDK + base_url 预设即可全覆盖；仅传文稿文本不传音频，符合隐私提示与本地优先。

**Alternatives**: 各家 SDK 分别接入（三倍适配成本）；内置单厂商（限制用户选择）。

## R5. 前端架构（Vue 3 + Vite）

**Decision**: Vue 3（Composition API + SFC）+ Vite + vue-router（hash 模式，本地服务免配置路径）+ Pinia。构建产物输出 `frontend/dist`，由 FastAPI 以静态文件伺服；发布随附预构建产物，最终用户浏览器打开即用、无需任何编译。

**Rationale**: 约 10 个高交互视图（联动播放器、测验、复习会话、导入向导）+ 跨视图共享状态（当前材料/播放器/复习队列），Vue 官方栈提供组件化与响应式状态管理；构建仅为开发期步骤，不违反宪法"用户无需编译"（编译发生在开发侧，交付物为静态文件）。

**Alternatives**: vanilla ES modules（零依赖，但此交互规模下 DOM 同步与事件管理代码失控，按用户方向放弃）；Vue CDN global build（免构建但无 SFC/热更新/单文件工具链，与 Vue 生态不一致）；React/Svelte（用户指定 Vue；React 运行时与生态对本项目偏重）。

## R6. 音频播放

**Decision**: HTMLAudioElement：服务端 Range 支持后 `currentTime` 拖动即正常 seek；`playbackRate` 原生 0.5×–1.5×（浏览器默认 preservesPitch 保调）；单句循环用 `timeupdate`（约 250ms 精度足够）检测越界回设句首。

**Rationale**: 零依赖满足全部播放需求；无缝循环等进阶需求出现再升级 Web Audio。

## R7. 数据存储

**Decision**: 纯 JSON 文件：`data/settings.json`、全局 `data/review-queue.json`、每材料 `data/materials/<id>/`（音频 + `material.json` 嵌套 Turn/Block/Sentence + `shadowing.json` + `quizzes.json`）。写入一律"临时文件 + `os.replace` 原子替换"；全局文件写操作在后端内串行化。

**Rationale**: 几十篇材料规模 JSON 总量小，全量载入/惰性读取无压力；纯文本可 diff、手改，符合宪法"可读格式存储"。

**Alternatives**: SQLite（二进制违反宪法明文规定，此规模无查询性能收益；记录达数千条再迁移，JSON 易导出）。

## 性能与规模目标（来自规格 + 实测数据）

- 转写：small/int8 ≈ 7.6× 实时率（优于规格预期的 1/5~1/2 时长）；medium 备选 2–4×
- 交互：点击单词跳转/高亮跟随 < 100ms（本地回环）
- 规模：单机单用户，材料数十篇，复习条目数千条以内
