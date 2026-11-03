<template>
  <div class="wizard">
    <header class="topbar">
      <a class="back" href="#/library">← 材料库</a>
      <h1>导入材料</h1>
    </header>

    <!-- 运行中：进度视图（覆盖整个表单，支持关闭重开后回连） -->
    <section v-if="phase === 'running'" class="panel progress-panel">
      <h2>步骤 5 · 导入进度</h2>
      <p class="stage-label">{{ stageLabel }}</p>
      <div class="progress-track">
        <div class="progress-fill" :style="{ width: progressPct + '%' }"></div>
      </div>
      <p class="progress-pct">{{ progressPct }}%</p>
      <div class="row">
        <button class="btn danger" :disabled="cancelling" @click="cancelJob">
          {{ cancelling ? '正在取消…' : '取消导入' }}
        </button>
      </div>
      <p class="hint">任务在后台运行；即使关闭页面也不会中断，重新打开本页可继续查看进度。</p>
    </section>

    <!-- 已取消 -->
    <section v-else-if="phase === 'cancelled'" class="panel result-panel">
      <h2>导入已取消</h2>
      <p class="hint">临时文件已清理，未产生任何数据。</p>
      <div class="row">
        <button class="btn primary" @click="resetWizard">重新导入</button>
        <button class="btn" @click="goLibrary">返回材料库</button>
      </div>
    </section>

    <!-- 出错 -->
    <section v-else-if="phase === 'error'" class="panel result-panel">
      <h2>导入失败</h2>
      <p class="error-text">{{ jobError || '导入处理失败，请重试。' }}</p>
      <div class="row">
        <button class="btn primary" @click="resetWizard">重新导入</button>
        <button class="btn" @click="goLibrary">返回材料库</button>
      </div>
    </section>

    <!-- 对齐失败降级提示 -->
    <section v-else-if="phase === 'done' && audioOnly" class="panel result-panel">
      <h2>导入完成（仅音频模式）</h2>
      <p class="warn-text">对齐失败（文稿与音频不匹配或模型异常），已降级为仅音频模式，可稍后重试对齐。</p>
      <div class="row">
        <button class="btn primary" @click="goLearn">进入学习</button>
        <button class="btn" @click="goLibrary">返回材料库</button>
      </div>
    </section>

    <!-- 正常完成：直接跳转学习页（goLearn 已执行） -->
    <section v-else-if="phase === 'done'" class="panel result-panel">
      <h2>导入完成</h2>
      <div class="row">
        <button class="btn primary" @click="goLearn">进入学习</button>
      </div>
    </section>

    <!-- 表单六步 -->
    <template v-else>
      <section class="panel" :class="{ readonly: phase === 'preview' }">
        <h2>步骤 1 · 选择音频文件</h2>
        <template v-if="phase === 'edit'">
          <input ref="audioInput" type="file" :accept="ACCEPT" @change="onAudioChange" />
          <p v-if="audioFile" class="ok-text">已选择：{{ audioFile.name }}（{{ formatSize(audioFile.size) }}）</p>
          <p v-if="audioError" class="error-text">{{ audioError }}</p>
          <p class="hint">支持 mp3 / wav / m4a / flac / ogg</p>
        </template>
        <p v-else class="summary">{{ audioFile ? audioFile.name : '未选择' }}</p>
      </section>

      <section class="panel" :class="{ readonly: phase === 'preview' }">
        <h2>步骤 2 · 填写标题</h2>
        <input v-if="phase === 'edit'" v-model="title" class="text-input" type="text" maxlength="200" placeholder="材料标题（必填）" />
        <p v-else class="summary">{{ title }}</p>
      </section>

      <section class="panel" :class="{ readonly: phase === 'preview' }">
        <h2>步骤 3 · 粘贴官方文稿</h2>
        <template v-if="phase === 'edit'">
          <textarea v-model="transcript" class="transcript-input" rows="12"
            placeholder="粘贴含说话人标签与中文译文的原文稿，例如：&#10;Georgie 乔治&#10;Hello and welcome to 6 Minute English.&#10;你好，欢迎收听六分钟英语。"></textarea>
          <div class="row">
            <input ref="transcriptFileInput" type="file" accept=".txt" class="file-small" @change="onTranscriptFile" />
            <span class="hint">也可上传 .txt 文稿文件</span>
          </div>
        </template>
        <p v-else class="summary">共 {{ transcript.trim().split(/\r?\n/).length }} 行文稿</p>
      </section>

      <p v-if="formError" class="error-text form-error">{{ formError }}</p>

      <section v-if="phase === 'edit'" class="panel">
        <h2>步骤 4 · 解析预览</h2>
        <p class="hint">系统将解析话轮结构（说话人、正文句、译文），先预览确认再开始对齐。</p>
        <button class="btn primary" :disabled="!canParse" @click="doParse">
          {{ parsing ? '解析中…' : '解析预览' }}
        </button>
        <p v-if="parseError" class="error-text">{{ parseError }}</p>
      </section>

      <section v-if="phase === 'preview' && preview" class="panel">
        <h2>步骤 4 · 解析预览（结构概览）</h2>
        <div class="stats">
          <div class="stat"><span class="stat-num">{{ speakerCount }}</span><span class="stat-label">说话人</span></div>
          <div class="stat"><span class="stat-num">{{ num(preview.turnCount) }}</span><span class="stat-label">话轮</span></div>
          <div class="stat"><span class="stat-num">{{ num(preview.translationLineCount) }}</span><span class="stat-label">译文行</span></div>
          <div class="stat"><span class="stat-num">{{ num(preview.blockCount) }}</span><span class="stat-label">段落块</span></div>
        </div>
        <p v-if="preview.speakers && preview.speakers.length" class="speakers">
          识别说话人：{{ preview.speakers.map(speakerLabel).join('、') }}
        </p>
        <div v-if="preview.turns && preview.turns.length" class="turn-overview">
          <div v-for="(turn, i) in preview.turns" :key="i" class="turn-item">
            <strong v-if="turnSpeaker(turn)">{{ turnSpeaker(turn) }}</strong>
            <span>{{ truncate(turnText(turn), 120) }}</span>
          </div>
        </div>
        <div class="row">
          <button class="btn" @click="backToEdit">返回修改文稿</button>
        </div>
      </section>

      <section v-if="phase === 'preview'" class="panel">
        <h2>步骤 5 · 开始导入</h2>
        <p class="hint">导入将使用 wav2vec2 强制对齐，把官方文稿逐词钉到音频上（本机离线）。</p>
        <button class="btn primary" :disabled="starting" @click="startImport">
          {{ starting ? '正在启动…' : '开始导入' }}
        </button>
        <p v-if="jobError" class="error-text">{{ jobError }}</p>
      </section>
    </template>
  </div>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'

import { get, pollJob, post } from '../api/client'

const router = useRouter()

const ACCEPT = '.mp3,.wav,.m4a,.flac,.ogg'
const ALLOWED_EXTS = ['mp3', 'wav', 'm4a', 'flac', 'ogg']
const JOB_KEY = 'importJobId'
const STAGE_LABELS = {
  queued: '排队中',
  parsing: '解析文稿中',
  aligning: '强制对齐中（wav2vec2）',
  done: '已完成',
  cancelled: '已取消',
  error: '处理出错',
}

const audioInput = ref(null)
const transcriptFileInput = ref(null)
const audioFile = ref(null)
const audioError = ref('')
const title = ref('')
const transcript = ref('')
const formError = ref('')
const phase = ref('edit') // edit | preview | running | done | cancelled | error
const preview = ref(null)
const parsing = ref(false)
const parseError = ref('')
const starting = ref(false)
const job = ref(null)
const jobId = ref(null)
const jobError = ref('')
const cancelling = ref(false)
const audioOnly = ref(false)
const materialId = ref(null)
let abortCtl = null
let autoNavTimer = null

const canParse = computed(
  () => !!audioFile.value && !!title.value.trim() && !!transcript.value.trim() && !parsing.value,
)
const speakerCount = computed(() => (preview.value?.speakers?.length ?? 0))
const stageLabel = computed(() => STAGE_LABELS[job.value?.stage] || '处理中')
const progressPct = computed(() => Math.max(0, Math.min(100, Math.round(job.value?.progressPct ?? 0))))

function num(v) {
  return typeof v === 'number' ? v : '—'
}

function truncate(s, n) {
  const text = (s || '').replace(/\s+/g, ' ').trim()
  return text.length > n ? text.slice(0, n) + '…' : text
}

function speakerLabel(s) {
  if (!s) return ''
  const name = s.name || s.speakerName || ''
  const zh = s.nameZh || s.speakerNameZh || ''
  return zh ? `${name} ${zh}` : name
}

function turnSpeaker(turn) {
  if (!turn || typeof turn === 'string') return ''
  return speakerLabel(turn) || speakerLabel({ name: turn.speaker, nameZh: turn.speakerZh })
}

function turnText(turn) {
  if (!turn) return ''
  if (typeof turn === 'string') return turn
  if (turn.text) return turn.text
  const sentences = turn.sentences || turn.blocks
  if (Array.isArray(sentences)) {
    return sentences.map((x) => (typeof x === 'string' ? x : x.text || '')).join(' ')
  }
  return ''
}

function formatSize(bytes) {
  if (bytes > 1024 * 1024) return (bytes / 1024 / 1024).toFixed(1) + ' MB'
  return Math.max(1, Math.round(bytes / 1024)) + ' KB'
}

function onAudioChange(e) {
  audioError.value = ''
  const file = e.target.files?.[0]
  if (!file) {
    audioFile.value = null
    return
  }
  const ext = file.name.includes('.') ? file.name.split('.').pop().toLowerCase() : ''
  if (!ALLOWED_EXTS.includes(ext)) {
    audioFile.value = null
    audioError.value = '不支持的音频格式，请使用 mp3 / wav / m4a / flac / ogg'
    return
  }
  audioFile.value = file
  if (!title.value.trim()) {
    title.value = file.name.replace(/\.[^.]+$/, '')
  }
}

function onTranscriptFile(e) {
  const file = e.target.files?.[0]
  if (!file) return
  const reader = new FileReader()
  reader.onload = () => {
    transcript.value = String(reader.result || '')
  }
  reader.readAsText(file)
  e.target.value = ''
}

function validateForm() {
  if (!audioFile.value) return '请先选择音频文件'
  if (!title.value.trim()) return '请填写标题'
  if (!transcript.value.trim()) return '请粘贴或上传文稿'
  return ''
}

async function doParse() {
  formError.value = validateForm()
  if (formError.value) return
  parsing.value = true
  parseError.value = ''
  try {
    preview.value = await post('/api/import/parse', { transcript: transcript.value })
    phase.value = 'preview'
  } catch (e) {
    parseError.value = e.message || '解析失败，请检查文稿内容'
  } finally {
    parsing.value = false
  }
}

function backToEdit() {
  phase.value = 'edit'
}

async function startImport() {
  formError.value = validateForm()
  if (formError.value) return
  starting.value = true
  jobError.value = ''
  const form = new FormData()
  form.append('audio', audioFile.value)
  form.append('title', title.value.trim())
  form.append('transcript', transcript.value)
  try {
    const res = await fetch('/api/import/start', { method: 'POST', body: form })
    const body = await res.json().catch(() => ({}))
    if (!res.ok) throw new Error(body.detail || `request failed: ${res.status}`)
    jobId.value = body.jobId
    job.value = { stage: 'queued', progressPct: 0 }
    phase.value = 'running'
    trackJob(body.jobId)
  } catch (e) {
    jobError.value = e.message || '启动导入失败'
  } finally {
    starting.value = false
  }
}

async function trackJob(id) {
  sessionStorage.setItem(JOB_KEY, id)
  abortCtl = new AbortController()
  const signal = abortCtl.signal
  // pollJob 负责等待终态；并行的轻量轮询用于实时刷新阶段与进度条
  const displayLoop = (async () => {
    try {
      for (;;) {
        const j = await get(`/api/import/jobs/${id}`)
        job.value = j
        if (['done', 'cancelled', 'error'].includes(j.stage) || signal.aborted) return
        await new Promise((resolve) => setTimeout(resolve, 1000))
      }
    } catch {
      /* 展示轮询失败不阻断 pollJob */
    }
  })()
  let finished = null
  try {
    finished = await pollJob(id, { signal })
  } catch (e) {
    if (!signal.aborted) jobError.value = e.message || '查询任务进度失败'
  }
  await displayLoop
  if (signal.aborted || !finished) return
  job.value = finished
  sessionStorage.removeItem(JOB_KEY)
  if (finished.stage === 'done') {
    audioOnly.value = !!finished.audioOnly
    materialId.value = finished.materialId || null
    phase.value = 'done'
    if (audioOnly.value) {
      // 停留本页展示降级提示
    } else {
      autoNavTimer = setTimeout(() => goLearn(), 600)
    }
  } else if (finished.stage === 'cancelled') {
    phase.value = 'cancelled'
  } else if (finished.stage === 'error') {
    jobError.value = '导入处理失败，请重试。'
    phase.value = 'error'
  }
}

async function cancelJob() {
  if (!jobId.value) return
  cancelling.value = true
  abortCtl?.abort()
  try {
    await post(`/api/import/jobs/${jobId.value}/cancel`, {})
  } catch {
    /* 取消请求失败也视为已本地终止 */
  }
  sessionStorage.removeItem(JOB_KEY)
  phase.value = 'cancelled'
  cancelling.value = false
}

function resetWizard() {
  abortCtl?.abort()
  sessionStorage.removeItem(JOB_KEY)
  audioFile.value = null
  audioError.value = ''
  title.value = ''
  transcript.value = ''
  formError.value = ''
  preview.value = null
  parseError.value = ''
  job.value = null
  jobId.value = null
  jobError.value = ''
  audioOnly.value = false
  materialId.value = null
  phase.value = 'edit'
  if (audioInput.value) audioInput.value.value = ''
}

function goLearn() {
  if (autoNavTimer) clearTimeout(autoNavTimer)
  router.push(materialId.value ? `/learn/${materialId.value}` : '/library')
}

function goLibrary() {
  if (autoNavTimer) clearTimeout(autoNavTimer)
  router.push('/library')
}

onMounted(() => {
  const saved = sessionStorage.getItem(JOB_KEY)
  if (saved) {
    jobId.value = saved
    job.value = { stage: 'queued', progressPct: 0 }
    phase.value = 'running'
    trackJob(saved)
  }
})

onBeforeUnmount(() => {
  if (autoNavTimer) clearTimeout(autoNavTimer)
  abortCtl?.abort()
})
</script>

<style scoped>
.wizard {
  max-width: 760px;
  margin: 0 auto;
  padding: 16px 20px 48px;
  font-family: 'Segoe UI', 'Microsoft YaHei', system-ui, sans-serif;
  color: #1f2933;
}
.topbar {
  display: flex;
  align-items: baseline;
  gap: 16px;
  margin-bottom: 16px;
}
.topbar h1 {
  font-size: 20px;
  margin: 0;
}
.back {
  color: #6b7280;
  text-decoration: none;
  font-size: 14px;
}
.back:hover {
  color: #2563eb;
}
.panel {
  background: #fff;
  border: 1px solid #e5e7eb;
  border-radius: 10px;
  padding: 16px 20px;
  margin-bottom: 14px;
}
.panel h2 {
  font-size: 15px;
  margin: 0 0 12px;
}
.panel.readonly {
  background: #f9fafb;
}
.summary {
  margin: 0;
  color: #374151;
  font-size: 14px;
}
.text-input {
  width: 100%;
  box-sizing: border-box;
  padding: 8px 10px;
  border: 1px solid #d1d5db;
  border-radius: 6px;
  font-size: 14px;
}
.transcript-input {
  width: 100%;
  box-sizing: border-box;
  padding: 8px 10px;
  border: 1px solid #d1d5db;
  border-radius: 6px;
  font-size: 14px;
  font-family: inherit;
  resize: vertical;
}
.row {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-top: 10px;
  flex-wrap: wrap;
}
.btn {
  padding: 7px 16px;
  border: 1px solid #d1d5db;
  border-radius: 6px;
  background: #fff;
  font-size: 14px;
  cursor: pointer;
}
.btn:hover {
  background: #f3f4f6;
}
.btn.primary {
  background: #2563eb;
  border-color: #2563eb;
  color: #fff;
}
.btn.primary:hover {
  background: #1d4ed8;
}
.btn.primary:disabled {
  background: #93c5fd;
  border-color: #93c5fd;
  cursor: not-allowed;
}
.btn.danger {
  border-color: #dc2626;
  color: #dc2626;
}
.btn.danger:hover {
  background: #fef2f2;
}
.btn.danger:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}
.hint {
  color: #9ca3af;
  font-size: 13px;
  margin: 8px 0 0;
}
.error-text {
  color: #dc2626;
  font-size: 13px;
  margin: 8px 0 0;
}
.form-error {
  margin: 0 0 14px;
}
.ok-text {
  color: #059669;
  font-size: 13px;
  margin: 8px 0 0;
}
.warn-text {
  color: #b45309;
  font-size: 14px;
  margin: 8px 0 0;
}
.stats {
  display: flex;
  gap: 12px;
  flex-wrap: wrap;
  margin-bottom: 10px;
}
.stat {
  background: #eff6ff;
  border-radius: 8px;
  padding: 10px 18px;
  text-align: center;
  min-width: 72px;
}
.stat-num {
  display: block;
  font-size: 20px;
  font-weight: 700;
  color: #2563eb;
}
.stat-label {
  font-size: 12px;
  color: #6b7280;
}
.speakers {
  font-size: 13px;
  color: #374151;
  margin: 0 0 10px;
}
.turn-overview {
  max-height: 220px;
  overflow-y: auto;
  border: 1px solid #e5e7eb;
  border-radius: 6px;
  padding: 8px 12px;
  font-size: 13px;
}
.turn-item {
  padding: 4px 0;
  border-bottom: 1px dashed #f3f4f6;
}
.turn-item:last-child {
  border-bottom: none;
}
.turn-item strong {
  color: #111827;
  margin-right: 6px;
}
.turn-item span {
  color: #6b7280;
}
.radio-row {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 6px 0;
  font-size: 14px;
  cursor: pointer;
}
.file-small {
  font-size: 13px;
}
.progress-panel {
  text-align: center;
  padding: 32px 20px;
}
.stage-label {
  font-size: 16px;
  font-weight: 600;
  margin: 12px 0 16px;
}
.progress-track {
  height: 10px;
  background: #e5e7eb;
  border-radius: 999px;
  overflow: hidden;
}
.progress-fill {
  height: 100%;
  background: #2563eb;
  border-radius: 999px;
  transition: width 0.4s ease;
}
.progress-pct {
  color: #6b7280;
  font-size: 13px;
  margin: 8px 0 16px;
}
.progress-panel .row {
  justify-content: center;
}
.result-panel {
  text-align: center;
  padding: 32px 20px;
}
.result-panel .row {
  justify-content: center;
}
</style>
