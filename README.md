# 精听工坊（Intensive Listening Trainer）

单机本地运行的精听训练工具：导入"音频 + 官方文稿"，自动转写对齐出句子/单词级时间轴；学习界面按 BBC 官方样式联动播放，支持标记模式划词记生词、句尾图标标记没听懂句、跟读训练；复习阶段隐藏文稿做整句听写测验（90% 达标）；生词/短语/没听懂句汇入跨材料全局复习队列（简单间隔重复 + 首页"今日待复习"入口）。

## 快速启动

前置：Python 3.11+、Node 20+、Windows/macOS/Linux。

```bash
# 1. 后端环境
python -m venv .venv
.venv/Scripts/python.exe -m pip install -r backend/requirements.txt   # Git Bash 用 .venv/Scripts/python.exe

# 2. 前端构建（发布版已附带 frontend/dist 可跳过）
cd frontend && npm install && npx vite build && cd ..

# 3. 启动
.venv/Scripts/python.exe -m uvicorn backend.app.main:app --port 8000
# 浏览器打开 http://localhost:8000
```

首次导入时 faster-whisper 会自动下载 small 模型（约 460MB，设置页可切换 medium 并查看下载状态）。国内网络若访问 HuggingFace 缓慢，可设镜像后下载：`set HF_ENDPOINT=https://hf-mirror.com`（PowerShell：`$env:HF_ENDPOINT="https://hf-mirror.com"`）。

## 使用流程

1. **导入**：材料库 → 新建导入 → 选音频（mp3/wav/m4a/flac/ogg）+ 填标题 + 粘贴官方文稿 → 确认解析预览 → 开始转写（可取消，可关页面稍后回来看进度）
2. **学习**：点击单词从该词播放；「✎ 标记模式」开启后划词+填释义加入生词本；句尾 ⚠ 标记没听懂；🎙 进入跟读
3. **复习**：学习完成 → 进入复习（文稿隐藏）→ 开始检测 → 整句默写 10 句 → ≥90 分掌握
4. **全局复习**：首页"今日待复习 N 条" → 语境卡（词/短语）与盲听卡（没听懂句）自评复习

## 开发

```bash
# 后端测试（宪法 III：核心逻辑单测强制）
.venv/Scripts/python.exe -m pytest backend/tests -q

# 前端开发模式（代理 /api 到 8000）
cd frontend && npm run dev
```

## 架构

- `backend/` FastAPI：core（文稿解析/对齐/判分/抽题/调度，纯函数可测）、asr（faster-whisper 本地 + 阿里百炼可选）、llm（OpenAI 兼容：OpenAI/DeepSeek/Kimi，跟读推荐）
- `frontend/` Vue 3 + Vite + Pinia（hash 路由，9 视图）
- `data/` 运行时数据（JSON 可读格式：settings / review-queue / materials/<id>/）

数据全部存储在本机；云端转写与大模型为可选能力，未配置时核心功能不受影响。

规格与计划见 `specs/001-intensive-listening-trainer/`。
