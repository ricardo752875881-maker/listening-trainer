# Tasks: 精听工坊（Intensive Listening Trainer）

**Input**: Design documents from `/specs/001-intensive-listening-trainer/`

**Prerequisites**: plan.md (required), spec.md (required for user stories), research.md, data-model.md, contracts/

**Tests**: 包含测试任务——项目宪法 III（NON-NEGOTIABLE）要求核心逻辑必须有单元测试覆盖并遵循先写失败测试再实现（Red-Green-Refactor）。前端视图不强制自动化测试，按 quickstart.md 场景人工验证。

**Organization**: Tasks are grouped by user story to enable independent implementation and testing of each story.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (e.g., US1, US2, US3)
- Include exact file paths in descriptions

## Path Conventions

- 后端: `backend/app/`（api/ core/ asr/ llm/ storage/），测试 `backend/tests/`
- 前端: `frontend/src/`（router/ stores/ api/ player/ views/），构建产物 `frontend/dist/`
- 数据: `data/`（settings.json / review-queue.json / materials/<id>/），运行时生成

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: 项目初始化与目录结构

- [x] T001 创建仓库目录结构：`backend/app/{api,core,asr,llm,storage}`、`backend/tests/{unit,contract}`、`frontend/src/{router,stores,api,player,views}`、`data/`，编写 `.gitignore`（data/、.venv、node_modules、frontend/dist）
- [x] T002 [P] 初始化后端 Python 工程：`backend/requirements.txt`（fastapi、uvicorn[standard]、faster-whisper、av、dashscope、openai、python-multipart、pytest、httpx），`backend/app/__init__.py` 各级包初始化
- [x] T003 [P] 初始化前端 Vue 工程：`frontend/package.json`（vue、vue-router、pinia、vite）、`frontend/vite.config.js`（build.outDir=dist、dev 代理 /api→localhost:8000）、`frontend/index.html`、`frontend/src/main.js`
- [x] T004 [P] 配置 pytest（`backend/tests/conftest.py`、空 `unit/__init__.py`/`contract/__init__.py`）并验证 `pytest -q` 空跑通过

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: 所有用户故事依赖的地基——存储、模型、应用装配、前端骨架

**⚠ CRITICAL**: 本阶段完成前任何用户故事不得开工

- [x] T005 实现 `backend/app/storage/json_store.py`：JSON 原子写（临时文件 + `os.replace`）、按路径读写、文件损坏时抛 `DataError`；对应 CHK029 需求待评审项先按"抛错并保留原文件"实现
- [x] T006 [P] 定义 `backend/app/models.py`：Pydantic 模型 Material/Turn/Block/Sentence/ReviewItem/ShadowingItem/Quiz/Settings，字段与校验照 [data-model.md](data-model.md)（含 `aligned` 必填、notUnderstood 为纯布尔（2026-10-28 起无 reason 枚举）、stage 枚举、intervalDays ∈ {1,3,7,15,30}）
- [x] T007 [P] 实现 `backend/app/main.py`：FastAPI 装配、CORS（dev）、静态伺服 `frontend/dist`、全局异常处理映射（400/404/409/502 + `{detail}`，照 [contracts/api.md](contracts/api.md) 错误约定）
- [x] T008 [P] 实现 `backend/app/api/settings.py`：GET/PUT `/api/settings`，读写 `data/settings.json`，响应中 apiKey 掩码（保留后 4 位）
- [x] T009 前端骨架：`frontend/src/main.js`、`App.vue`、hash 路由（router/index.js：library/import/learn/shadow/review/quiz/review-session/vocab-book/settings）、`api/client.js`（fetch 封装 + 导入进度轮询）、pinia 占位 store

**Checkpoint**: `uvicorn backend.app.main:app` 启动，前端 `npm run build` 后浏览器打开 8000 端口可见空壳应用，GET/PUT settings 往返成功

---

## Phase 3: User Story 1 - 导入材料并完成首次学习 (Priority: P1) 🎯 MVP

**Goal**: 音频+官方文稿导入（解析预览→转写→对齐→差异分析→入库），学习界面按官方样式渲染并实现全部播放联动与标记

**Independent Test**: quickstart.md 场景 1、2——导入 BBC 风格材料后在学习界面完成播放高亮/单词跳转/自动跟随暂停恢复/生词与没听懂标记/重点句听音指引，重开后进度恢复

### Tests for User Story 1（先写，必须 FAIL）

- [x] T010 [P] [US1] 单元测试 `backend/tests/unit/test_parser.py`：说话人标签行（含 `Neil 尼尔`、`Beth:`、行内 `Beth: Hello`）、按 `. ? ! ;` 切句、中文占比过半判译文并挂最近段落块、无标签材料空行分话轮、异常行按正文兜底
- [x] T011 [P] [US1] 单元测试 `backend/tests/unit/test_aligner.py`：归一化管线（小写/NFKC/标点/缩写展开 I'm→I am）、opcodes 映射句子起止时间与逐词时间戳、无法映射的句子标记"未对齐"
- [x] T012 [P] [US1] 单元测试 `backend/tests/unit/test_scoring.py`：判分归一化（忽略大小写/首尾空格/全部标点/全角转半角、缩写不展开）
- [x] T013 [P] [US1] 合约测试 `backend/tests/contract/test_api_materials.py`：materials CRUD + audio Range 请求（206/Accept-Ranges）+ 404/409 约定

### Implementation for User Story 1

- [x] T014 [US1] 实现 `backend/app/core/transcript_parser.py`：输出 Turn→Block→Sentence 层级（speakers 名/中文译名归一），供 parse 预览与正式入库共用
- [x] T015 [US1] 实现 `backend/app/core/aligner.py`（difflib.SequenceMatcher `autojunk=False` + 双侧归一化）与 `core/scoring.py`（差异率、重点句判定、判分归一化）
- [x] T016 [P] [US1] 实现 `backend/app/asr/transcriber.py`（Provider 抽象，统一输出 `words[]` 毫秒时间戳）与 `faster_whisper_provider.py`（`word_timestamps=True`、small/medium 规格、取消检查点、用 av 探测时长）
- [x] T017 [US1] 实现 `backend/app/asr/paraformer_provider.py`（dashscope 异步任务、words 毫秒时间戳）与 `backend/app/jobs.py`（导入任务：stage/progress/cancel/SSE 事件帧）
- [x] T018 [US1] 实现 `backend/app/api/import.py`：`/api/import/parse`（预览不落库）、`/api/import/start`（multipart：audio/title/transcript/engine）、`GET /api/import/jobs/{id}`（轮询进度，任务服务端常驻支持重开重连）、cancel；转写失败按"仅音频模式"降级入库（FR-012）并提供 `POST /api/materials/{id}/retry-transcribe` 重试
- [x] T019 [US1] 实现 `backend/app/api/materials.py`：GET list（含 stats 派生统计：vocab/notUnderstood）/GET detail/PATCH（title/stage/playheadSec）/DELETE（级联清除目录 + 复习条目 + 跟读 + 测验）、audio 流（FileResponse Range）；实现 `backend/app/core/review_store.py`（ReviewItem 创建/按 (materialId,sentenceId,text,type) 去重/按材料级联清除）
- [x] T020 [P] [US1] 前端导入向导 `frontend/src/views/ImportWizard.vue`：选音频→填标题→粘贴文稿→调 parse 预览（说话人/话轮/译文计数）→确认→引擎选择→进度展示（轮询）→取消→关闭重开可回连进度页
- [x] T021 [P] [US1] 前端播放器封装 `frontend/src/player/`：`<audio>` 封装（单词/句/话轮跳转、playbackRate 0.5×~1.5×、单句循环 timeupdate 回设、逐词高亮回调）
- [x] T022 [US1] 实现 `backend/app/api/markings.py`：vocab 标记（创建/删除 ReviewItem）、not-understood（置标记+建条目，取消即删）、key-sentence 手动增删（PUT）
- [x] T023 [US1] 学习视图 `frontend/src/views/LearnView.vue`：话轮/段落块渲染（加粗标题含译名、句连成段、译文紧随弱化+全局开关）、句内高亮、自动滚动跟随（手动上翻即停、回当前句恢复）、点击单词从该词播放、「标记模式」开关（开启禁跳转、划词+释义输入加入生词本、荧光笔持久标记）、句尾「没听懂」图标开关（红色虚线、再点取消）、未对齐句标识；调 markings API
- [x] T024 [US1] 最小材料库 `frontend/src/views/LibraryView.vue` 基础版（卡片列表含阶段/成绩/统计、新建导入与学习入口；重命名/删除留待 US4）+ playheadSec 节流持久化

**Checkpoint**: 场景 1、2 全通；US1 独立可用（导入→学习闭环）

---

## Phase 4: User Story 2 - 复习检测与掌握判定 (Priority: P2)

**Goal**: 泛听模式（藏文稿、只读进度条）+ 整句听写测验（抽题优先级/无状态判分/90% 流转）

**Independent Test**: quickstart.md 场景 3——进入复习隐藏文稿泛听，开始检测默写 10 句，判分并流转/回学习

### Tests for User Story 2（先写，必须 FAIL）

- [x] T025 [P] [US2] 单元测试 `backend/tests/unit/test_quiz_selector.py`：抽题优先级（没听懂>含生词/短语>随机）、排除未对齐句、不足 10 句全出、归一化判分对错边界
- [x] T026 [P] [US2] 合约测试 `backend/tests/contract/test_api_quiz.py`：generate（草稿持久化）/GET 恢复（已答保留）/submit、≥90 流转 mastered 与 bestScore 取最大、<90 只记成绩

### Implementation for User Story 2

- [x] T027 [US2] 实现 `backend/app/core/quiz_selector.py`：按优先级抽题（没听懂 > 含生词/短语 > 随机；默认 10，排除 aligned=false），照 data-model Quiz 结构
- [x] T028 [US2] 实现 `backend/app/api/quiz.py`：POST generate（抽题并创建 in_progress 草稿，作答即写 userInput）、GET `/api/quiz/{quizId}`（恢复未完成的测验）、POST submit（无状态判分、草稿转 completed、stage 流转/bestScore、错句回顾数据）
- [x] T029 [P] [US2] 复习视图 `frontend/src/views/ReviewView.vue`：进入复习隐藏文稿与译文、进度条只读、播放/暂停/变速、随时「开始检测」
- [x] T030 [US2] 测验视图 `frontend/src/views/QuizView.vue`：逐题听写（可反复重听/变速）、逐题提交、交卷统一判分、得分页（错句"我的输入 vs 原文"、可查看文稿与听音指引）、「回到学习」/「再测一次」

**Checkpoint**: 场景 3 全通；US2 与 US1 互不破坏

---

## Phase 5: User Story 3 - 跟读训练 (Priority: P3)

**Goal**: 任意片段标记跟读 + 大模型推荐（手动触发）+ 简单跟读模式（播-停-模仿）

**Independent Test**: quickstart.md 场景 5——手动标记片段跟读一轮；配置大模型后获取推荐并采纳

### Tests for User Story 3（先写，必须 FAIL）

- [x] T031 [P] [US3] 合约测试 `backend/tests/contract/test_api_shadowing.py`：CRUD、含未对齐句片段 409、recommend 未配置 400、ignore 不重复推荐

### Implementation for User Story 3

- [x] T032 [US3] 实现 `backend/app/api/shadowing.py`：清单/创建（锚点 sentenceId+wordIndex、audioStart/End 由逐词时间戳推导、范围含未对齐句 409）/删除/ignore（status 流转）
- [x] T033 [P] [US3] 实现 `backend/app/llm/recommend.py`：OpenAI 兼容客户端 + 三厂商预设 base_url（OpenAI/DeepSeek/Kimi），prompt 仅含文稿文本（不上传音频），候选映射回锚点
- [x] T034 [US3] 学习界面跟读面板（LearnView 内嵌组件）：选中任意文本标记「想跟读」、未配置大模型时无推荐入口、「获取推荐」调用与采纳/忽略交互
- [x] T035 [US3] 跟读模式视图 `frontend/src/views/ShadowView.vue`：逐条播放-自动停顿、重听/跳条/变速/单条循环、清单管理（移除）

**Checkpoint**: 场景 5 全通

---

## Phase 6: User Story 4 - 材料库总览与管理 (Priority: P4)

**Goal**: 完整材料库（卡片统计、重命名、删除确认级联、三个入口 + 待复习入口占位）

**Independent Test**: 重命名即时生效；删除材料后音频/数据/复习条目全部清除并需确认

- [x] T036 [US4] 增强 `frontend/src/views/LibraryView.vue`：重命名（内联编辑）、删除（确认弹窗+级联说明）、空态引导
- [x] T037 [US4] 后端删除级联完整性核对：materials DELETE 同时清除 review-queue.json 条目、shadowing.json、quizzes.json、音频目录（T019 已实现则补集成测试 `backend/tests/contract/test_api_materials.py` 中 cascades 用例）

**Checkpoint**: 库管理操作全通；为 US5 的首页入口预留位置

---

## Phase 7: User Story 5 - 全局复习队列与卡片复习 (Priority: P5)

**Goal**: 生词/短语/没听懂句汇入跨材料队列，间隔重复调度，首页"今日待复习"入口，语境卡/盲听卡复习会话，总览管理

**Independent Test**: quickstart.md 场景 4——到期入口可见、混合卡片自评、调度生效、总览筛选/删除

### Tests for User Story 5（先写，必须 FAIL）

- [x] T038 [P] [US5] 单元测试 `backend/tests/unit/test_scheduler.py`：新条目 +1 天到期、通过升档（1→3→7→15→30→30 循环）、未通过重置 1 天、去重、材料删除级联、≤20 张取卡
- [x] T039 [P] [US5] 合约测试 `backend/tests/contract/test_api_review.py`：due/rate/items 筛选排序删除

### Implementation for User Story 5

- [x] T040 [US5] 实现 `backend/app/core/scheduler.py`：到期查询（dueAt ≤ today、≤20 张）、rate 后调度状态机；`data/review-queue.json` 读写
- [x] T041 [US5] 实现 `backend/app/api/review.py`：GET due、POST rate、GET items（materialId/type/familiarity 筛选排序）、DELETE
- [x] T042 [P] [US5] 首页"今日待复习 N 条"入口（LibraryView）+ 复习会话视图 `frontend/src/views/ReviewSessionView.vue`：语境卡（原句+高亮+原声，自评认识/不认识）、盲听卡（仅音频+原因提示，自评听懂/没懂→可看指引重听）、空队列提示、中途退出未自评卡保持到期
- [x] T043 [US5] 生词本总览视图 `frontend/src/views/VocabBookView.vue`：三类条目汇总、按材料/类型筛选、按熟悉度排序、删除（手动移除）

**Checkpoint**: 场景 4 全通

---

## Phase 8: User Story 6 - 设置 (Priority: P6)

**Goal**: 转写引擎/模型规格/云端 Key/大模型/默认速度/译文偏好全部可配，连通性可测

**Independent Test**: quickstart.md 场景 5 前置——配置 DeepSeek 后推荐可用；切换引擎对导入生效

- [x] T044 [P] [US6] 设置视图 `frontend/src/views/SettingsView.vue`：引擎切换（本地 faster-whisper / Paraformer，常驻隐私提示）、模型规格选择与下载状态展示、API Key 填写+连通性测试、大模型（provider 三选/apiKey/model/启停）、默认速度、译文默认显示
- [x] T045 [US6] 实现 `backend/app/api/settings.py` 扩展：POST `/api/settings/test-paraformer`、POST `/api/settings/test-llm`（三厂商 base_url 预设）、faster-whisper 模型下载状态接口（模型目录探测）

**Checkpoint**: 全部配置项生效且可测

---

## Phase 9: Polish & Cross-Cutting Concerns

**Purpose**: 跨故事收尾

- [x] T046 [P] 未对齐句全链路核对：文稿标识、测验排除、跟读拒绝、跳转禁用（与 CHK001 一致）
- [x] T047 [P] 按 [quickstart.md](quickstart.md) 六个场景全量走查并修复偏差
- [x] T048 [P] README 启动指南（venv→pip→npm build→uvicorn；发布版含 dist 说明）
- [x] T049 宪法冒烟验证：加载音频→播放→复读→变速→标记→记录进度，确认离线可用（断网核心功能回归）
- [x] T050 成功标准核对（SC-001~012 可测性）与性能确认（转写倍速、交互 <100ms）

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: 无依赖，立即开工；T001 先于 T002/T003（目录存在）
- **Foundational (Phase 2)**: 依赖 Setup；T007 main.py 依赖 T005/T006；T009 依赖 T003。**本阶段阻塞所有用户故事**
- **User Stories (Phase 3-8)**: 均依赖 Foundational 完成；推荐按 P1→P6 顺序（单人）；US4/US5/US6 之间无强依赖可并行
- **Polish (Phase 9)**: 依赖目标故事完成

### User Story Dependencies

- **US1 (P1)**: Foundational 后开工，无故事间依赖；T014/T015 被 T010-T012 阻塞（先测试后实现）；T016 与 T017 可并行；T018 依赖 T014-T017；T023 依赖 T018-T022；T024 依赖 T023
- **US2 (P2)**: 依赖 US1 的 materials/sentences 数据（T019）；T027/T028 被 T025/T026 阻塞；T030 依赖 T028/T029
- **US3 (P3)**: 依赖 US1 学习视图（T023）；T033 与 T032 可并行；T034 依赖 T032/T033
- **US4 (P4)**: 依赖 US1（T023 基础库视图）；与 US2/US3 可并行
- **US5 (P5)**: 依赖 US1（T019 review_store 条目创建）；T042/T043 依赖 T040/T041
- **US6 (P6)**: 依赖 T008（settings 基础）；T045 依赖 T033（三厂商预设共用）

### Within Each User Story

- 先写测试（T010-T013 等）并确认 FAIL → 再实现（宪法 III）
- Models(T006) → core 纯函数 → providers/API → 前端视图 → 集成

### Parallel Opportunities

- Phase 1 全部 [P] 任务；Phase 2 中 T006/T008 与 T005/T007/T009 可并行
- 各故事内：单元测试文件之间 [P]；T016 与 T017；T020 与 T021；T029 与 T030 的前后端可 [P]
- 单人执行建议顺序：T001→T002→T003→T004→T005→T006→T007→T008→T009→US1 全序列→US2→US5→US3→US4→US6→Polish（US5 提前：其基础 review_store 在 US1 已建，scheduler 独立可插）

---

## Parallel Example: User Story 1

```bash
# 测试先行，三份单测并行：
Task: "T010 单元测试 test_parser.py"
Task: "T011 单元测试 test_aligner.py"
Task: "T012 单元测试 test_scoring.py"

# 实现期并行：
Task: "T016 faster_whisper_provider.py"
Task: "T017 paraformer_provider.py + jobs.py"

# 前端并行：
Task: "T020 ImportWizard.vue"
Task: "T021 player/ 播放器封装"
```

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Phase 1 → Phase 2（地基）
2. Phase 3 US1 全序列（含测试先行）
3. **STOP**：跑通 quickstart 场景 1、2，独立验证导入→学习闭环
4. 此后每个故事按优先级增量交付，互不破坏

### Incremental Delivery

1. Setup + Foundational → 空壳可启动
2. US1 → 导入学习闭环（核心价值，MVP）
3. US2 → 检测验收闭环
4. US5 → 全局复习（生词本价值兑现）
5. US3 → 跟读口语训练
6. US4/US6 → 管理与配置补齐
7. Polish → 全场景走查 + 宪法冒烟

### 备注

- ⚠ **门禁提醒**：`checklists/spec-review.md`（32 项需求质量评审）当前全部未打勾，`speckit-implement` 会读取其状态作为门禁；建议实现前先完成评审，尤其 CHK009/010/011/012/014/015/016（UX 缺口）与 CHK024（ImportJob 瞬态语义）
- [P] tasks = different files, no dependencies
- 每个故事独立完成、独立验证（quickstart 对应场景）
- 提交信息遵循 `type(scope): summary`（宪法 Development Workflow）
