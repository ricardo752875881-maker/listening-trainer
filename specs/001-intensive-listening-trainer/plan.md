# Implementation Plan: 精听工坊（Intensive Listening Trainer）

**Branch**: `001-intensive-listening-trainer` | **Date**: 2026-10-27 | **Spec**: [spec.md](../spec.md)

**Input**: Feature specification from `/specs/001-intensive-listening-trainer/spec.md`

## Summary

单机本地运行的精听训练工具：用户导入"音频 + 官方文稿"，系统解析文稿话轮结构、转写对齐生成句子级时间轴，在学习界面提供官方样式的文稿联动播放、标记模式（划词+释义入生词本）与句尾"没听懂"开关、跟读训练；复习阶段隐藏文稿做整句听写测验（90% 达标流转）；练习产出的生词/短语/没听懂句汇入跨材料全局复习队列（简单间隔重复 + 首页到期入口）。技术方案：Python FastAPI 本地后端（faster-whisper 本地转写 + 阿里百炼可选 + OpenAI 兼容大模型推荐）+ Vue 3 + Vite 前端（构建产物由后端伺服）+ JSON 文件存储，Windows 优先。

## Technical Context

**Language/Version**: Python 3.11+（后端）；Node 20+（仅前端构建）；Vue 3 + ES2022

**Primary Dependencies**: FastAPI（Starlette ≥ 0.49.1）+ uvicorn；faster-whisper（本地转写）；dashscope（Paraformer 云端，可选）；openai（大模型，可选）；前端：vue / vue-router（hash）/ pinia / vite。详见 [research.md](research.md) R1–R6。

**Storage**: JSON 文件（`data/settings.json`、全局 `review-queue.json`、每材料 `data/materials/<id>/`），原子写。见 research.md R7 与 [data-model.md](data-model.md)。

**Testing**: pytest + httpx TestClient；核心逻辑（文稿解析、对齐、判分、抽题、间隔调度）为后端纯函数强制单测（宪法 III）；前端按 [quickstart.md](quickstart.md) 场景验证。

**Target Platform**: Windows 优先；本机浏览器（Edge/Chrome）访问 `http://localhost:8000`

**Project Type**: web-app（本地优先 SPA + 本机后端，单仓库前后端分离）

**Performance Goals**: 转写 small/int8 ≥ 4× 实时率（实测约 7.6×，10 分钟音频 ≈ 1.5 分钟）；交互响应 < 100ms；单词级跳转偏差 ≤ 0.5s（SC-003）

**Constraints**: 离线核心功能完整（转写本地默认、大模型可关）；音频与数据不出本机（云端引擎主动选择时除外）；写文件原子替换防中断损坏；前端构建为开发期步骤、发布随附预构建 `dist`（用户零编译）；内存占用可控（无 torch 等重量级依赖）

**Scale/Scope**: 单用户单机；材料数十篇；复习条目数千以内；单次测验 10 句、单次复习会话 ≤20 卡

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.* — **Phase 0/1 后复检：全部通过，无违规。**

| 条款 | 结论 | 依据 |
|------|------|------|
| I. 本地优先 | PASS | faster-whisper 本地默认引擎；云端转写与大模型均为可选可关；全部数据本机 JSON（research.md R2/R4/R7） |
| II. 开箱即用 | PASS | 默认 small 模型 + 零必填配置；启动 → 新建导入 ≤ 3 步进入学习 |
| III. 核心逻辑可测试 | PASS | 解析/对齐/判分/抽题/调度全部置于 backend `core/` 纯函数层，pytest 覆盖（quickstart 冒烟） |
| IV. 流畅与进度可恢复 | PASS | `playheadSec`/标记/阶段实时原子持久化（data-model Material/ReviewItem） |
| V. 简洁单一职责 | PASS | 功能全部服务听/说训练目标；无社交、账号、推荐流 |
| 技术约束 | PASS | Windows 优先；FastAPI 为轻量 ASGI（非重量级）；Vue 3 为官方主流前端栈、无 torch 类重依赖；开放格式 MP3/WAV + JSON；本地 `pip install + npm run build + uvicorn` 即可构建运行，无外部 CI 依赖 |

**Phase 1 后复检说明**: R1–R7 的选型（FastAPI/零依赖前端/difflib 对齐/JSON 存储）未引入任何与宪法冲突的新依赖或架构；无 Complexity Tracking 条目。

## Project Structure

### Documentation (this feature)

```text
specs/001-intensive-listening-trainer/
├── plan.md              # 本文件
├── research.md          # Phase 0：技术选型决策
├── data-model.md        # Phase 1：实体/状态机/校验规则
├── quickstart.md        # Phase 1：端到端验证指南
├── contracts/api.md     # Phase 1：REST/SSE 接口契约
└── tasks.md             # Phase 2 产物（/skill:speckit-tasks，本命令不创建）
```

### Source Code (repository root)

```text
backend/
├── app/
│   ├── main.py              # FastAPI 装配：路由/静态文件/异常处理
│   ├── api/                 # materials / import / markings / quiz / shadowing / review / settings 路由
│   ├── core/                # 纯函数核心逻辑（宪法 III：单测强制覆盖）
│   │   ├── transcript_parser.py   # 文稿结构解析（标签/切句/译文/兜底，FR-007）
│   │   ├── aligner.py             # difflib 词级对齐 → 句子/逐词时间戳 + 未对齐标记（FR-011）
│   │   ├── scoring.py             # 判分归一化（FR-031）
│   │   ├── quiz_selector.py       # 测验抽题优先级（FR-029）
│   │   └── scheduler.py           # 间隔重复调度（FR-038）
│   ├── asr/
│   │   ├── transcriber.py         # Provider 抽象，统一 words[] 输出
│   │   ├── faster_whisper_provider.py
│   │   └── paraformer_provider.py
│   ├── llm/recommend.py           # OpenAI 兼容客户端 + OpenAI/DeepSeek/Kimi 预设（FR-028/048）
│   ├── storage/json_store.py      # JSON 原子写/读（research.md R7）
│   └── jobs.py                    # 导入任务：进度（服务端常驻，前端轮询）/取消
├── tests/                   # test_parser / test_aligner / test_scoring / test_scheduler / test_quiz / test_api
└── requirements.txt

frontend/
├── index.html
├── vite.config.js           # build outDir=dist；dev 代理 /api → 8000
├── package.json
├── src/
│   ├── main.js / App.vue
│   ├── router/              # hash 路由：library/import/learn/shadow/review/quiz/review-session/vocab-book/settings
│   ├── stores/              # Pinia：material/player/reviewQueue/settings
│   ├── api/                 # REST 客户端封装（含导入进度轮询）
│   ├── player/              # <audio> 封装组件：单词/句子跳转、变速、单句循环、逐词高亮驱动
│   └── views/               # 各视图 .vue 组件
└── dist/                    # 构建产物（gitignore；发布随附），由 FastAPI 伺服

data/                      # 运行时生成（gitignore）：settings.json / review-queue.json / materials/<id>/
```

**Structure Decision**: 单仓库前后端分离（backend/ + frontend/）；前端为 Vite 标准工程，构建产物 `dist/` 由 FastAPI 以静态文件伺服，`uvicorn backend.app.main:app` 单进程对外服务。核心逻辑全部收敛于 `backend/app/core/` 纯函数层，与 API 层解耦以满足宪法 III 的可测试性要求。

## Complexity Tracking

> Vue 前端栈为宪法"禁止引入重量级框架"条款下的唯一记录条目。

| Violation | Why Needed | Simpler Alternative Rejected Because |
|-----------|------------|-------------------------------------|
| 引入 Vue 3 + Vite + Pinia（前端框架与构建链） | 约 10 个高交互视图（联动播放器、测验、复习会话）+ 跨视图共享状态；用户明确指定 Vue；组件化与响应式状态管理在此交互规模下显著降低维护成本 | vanilla ES modules：零依赖但视图/播放器状态同步代码在 10 视图规模下失控；Vue CDN global build：无 SFC/热更新/工具链支持，与 Vue 生态不一致。构建链仅开发期使用，发布随附预构建产物，用户端仍"浏览器打开即用"，不违反"开箱即用"条款 |
