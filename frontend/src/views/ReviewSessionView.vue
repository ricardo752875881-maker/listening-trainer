<script setup>
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { get } from '../api/client'
import { useReviewStore, REVIEW_TYPE_LABELS } from '../stores/review'

const router = useRouter()
const store = useReviewStore()

const index = ref(0)
const flipped = ref(false) // 词/短语卡：自评"不认识"后翻面
const revealed = ref(false) // 盲听卡：自评"还是没听懂"后展开文稿
const rating = ref(false)
const rateError = ref('')
const playing = ref(false)
const results = reactive({}) // itemId → passed（多次自评以最后一次计）

const matCache = reactive({}) // materialId → { loading, error, title, sentencesById }
const audioEl = ref(null)
const audioMaterialId = ref('')
let stopAt = null

const items = computed(() => store.dueItems)
const total = computed(() => items.value.length)
const finished = computed(() => total.value > 0 && index.value >= total.value)
const current = computed(() => items.value[index.value] || null)
const currentMat = computed(() => (current.value ? matCache[current.value.materialId] : null))
const currentSentence = computed(() => {
  if (!current.value || !currentMat.value?.sentencesById) return null
  return currentMat.value.sentencesById[current.value.sentenceId] || null
})
const isBlind = computed(() => current.value?.type === 'sentence')

const knownCount = computed(() => Object.values(results).filter(Boolean).length)
const failedCount = computed(() => Object.values(results).filter((v) => v === false).length)
const remainingTomorrow = computed(() => Math.max(0, store.dueCount - total.value))

// 目标词在原句语境中高亮
function highlightParts(text, target) {
  if (!text) return []
  if (!target) return [{ text, hit: false }]
  const lower = text.toLowerCase()
  const t = target.toLowerCase()
  if (!t) return [{ text, hit: false }]
  const parts = []
  let i = 0
  while (i < text.length) {
    const idx = lower.indexOf(t, i)
    if (idx === -1) {
      parts.push({ text: text.slice(i), hit: false })
      break
    }
    if (idx > i) parts.push({ text: text.slice(i, idx), hit: false })
    parts.push({ text: text.slice(idx, idx + t.length), hit: true })
    i = idx + t.length
  }
  return parts
}

async function ensureMaterial(materialId) {
  if (!materialId || matCache[materialId]) return
  matCache[materialId] = { loading: true, error: '', title: '', sentencesById: {} }
  try {
    const data = await get(`/api/materials/${materialId}`)
    const sentencesById = {}
    for (const s of data.sentences || []) sentencesById[s.id] = s
    matCache[materialId] = {
      loading: false,
      error: '',
      title: (data.material ? data.material : data)?.title || '',
      sentencesById,
    }
  } catch (e) {
    matCache[materialId] = { loading: false, error: e.message || '材料加载失败', title: '', sentencesById: {} }
  }
}

// ---------- 音频 ----------

function playCurrent() {
  const el = audioEl.value
  const item = current.value
  if (!el || !item) return
  if (audioMaterialId.value !== item.materialId) {
    el.src = `/api/materials/${item.materialId}/audio`
    audioMaterialId.value = item.materialId
  }
  const s = currentSentence.value
  if (!s || s.startSec == null) return
  stopAt = s.endSec ?? null
  playing.value = true
  el.currentTime = s.startSec
  el.play().catch(() => {
    playing.value = false
  })
}

function onTimeUpdate() {
  const el = audioEl.value
  if (!el || stopAt == null) return
  if (el.currentTime >= stopAt) {
    el.pause()
    stopAt = null
  }
}

function onStop() {
  playing.value = false
  stopAt = null
}

// ---------- 自评 ----------

async function rate(passed) {
  const item = current.value
  if (!item || rating.value) return
  rating.value = true
  rateError.value = ''
  try {
    await store.rate(item.id, passed)
    results[item.id] = passed
    if (passed) {
      advance()
    } else if (isBlind.value) {
      revealed.value = true // 盲听卡：展开文稿，可重听再判
    } else {
      flipped.value = true // 语境卡：翻面显示释义/原句
    }
  } catch (e) {
    rateError.value = e.message || '自评提交失败，请重试'
  } finally {
    rating.value = false
  }
}

function advance() {
  flipped.value = false
  revealed.value = false
  rateError.value = ''
  index.value += 1
}

function exitSession() {
  const done = Object.keys(results).length
  const msg = done
    ? `退出复习？已自评的 ${done} 张已保存，未自评的卡片保持到期。`
    : '退出复习？本次未自评任何卡片。'
  if (window.confirm(msg)) {
    router.push('/library')
  }
}

onMounted(async () => {
  await store.fetchDue()
  if (items.value.length) {
    // 预取第一张卡的材料
    await ensureMaterial(items.value[0].materialId)
  }
})
onBeforeUnmount(() => audioEl.value?.pause())

// 切卡时按需加载材料
watch(current, (item) => {
  if (item) ensureMaterial(item.materialId)
})
</script>

<template>
  <div class="page">
    <header class="topbar">
      <button class="btn ghost" @click="exitSession">← 退出</button>
      <h1>今日复习</h1>
      <span v-if="!finished && total" class="progress-text">{{ index + 1 }} / {{ total }}</span>
    </header>

    <div v-if="!store.dueLoaded && store.dueLoading" class="muted">加载到期卡片…</div>
    <p v-else-if="store.dueError" class="error-text">
      {{ store.dueError }} <button class="btn small" @click="store.fetchDue()">重试</button>
    </p>

    <!-- 空队列（FR-040） -->
    <section v-else-if="!total" class="panel empty">
      <p class="empty-icon">🌱</p>
      <p>今天没有到期的复习条目。</p>
      <p class="muted">先到学习界面标记生词/短语，或用句尾图标标记「没听懂」的句子，它们会在 1 天后到期进入复习队列。</p>
      <button class="btn primary" @click="router.push('/library')">返回材料库</button>
    </section>

    <!-- 小结 -->
    <section v-else-if="finished" class="panel summary">
      <p class="summary-icon">✅</p>
      <h2>本次复习完成</h2>
      <div class="summary-grid">
        <div class="cell"><b>{{ total }}</b><span>本次卡片</span></div>
        <div class="cell ok"><b>{{ knownCount }}</b><span>已掌握</span></div>
        <div class="cell warn"><b>{{ failedCount }}</b><span>待巩固</span></div>
      </div>
      <p v-if="remainingTomorrow" class="note">今日还有 {{ remainingTomorrow }} 条到期未练，明天继续到期。</p>
      <p class="note">「待巩固」的条目将于 1 天后再次到期。</p>
      <button class="btn primary" @click="router.push('/library')">完成</button>
    </section>

    <!-- 语境卡：词/短语 -->
    <section v-else-if="!isBlind" class="panel">
      <div class="card">
        <div class="type-row">
          <span class="type-badge">{{ REVIEW_TYPE_LABELS[current.type] }}卡</span>
          <span v-if="currentMat?.title" class="note" style="margin:0">来自《{{ currentMat.title }}》</span>
        </div>
        <div class="word">{{ current.text }}</div>

        <div v-if="currentMat?.loading" class="muted">加载语境音频…</div>
        <p v-else-if="currentMat?.error" class="error-text small">{{ currentMat.error }}</p>
        <template v-else>
          <button class="btn" :disabled="!currentSentence" @click="playCurrent">
            {{ playing ? '🔊 播放中…' : '🔊 播放原句' }}
          </button>
          <div v-if="current.contextText" class="ctx">
            <template v-for="(p, i) in highlightParts(current.contextText, current.text)" :key="i">
              <b v-if="p.hit">{{ p.text }}</b><span v-else>{{ p.text }}</span>
            </template>
          </div>
        </template>

        <template v-if="!flipped">
          <p class="note">边听边看，认识这个词/短语吗？</p>
          <div class="rate">
            <button class="know" :disabled="rating" @click="rate(true)">😊 认识</button>
            <button class="unknow" :disabled="rating" @click="rate(false)">🤔 不认识</button>
          </div>
        </template>
        <template v-else>
          <div class="flip-box">
            <p v-if="current.meaning" class="flip-meaning"><b>{{ current.text }}</b> — {{ current.meaning }}</p>
            <p v-else class="flip-meaning empty">未填写释义</p>
            <div v-if="current.contextText" class="ctx full">
              <template v-for="(p, i) in highlightParts(current.contextText, current.text)" :key="i">
                <b v-if="p.hit">{{ p.text }}</b><span v-else>{{ p.text }}</span>
              </template>
            </div>
            <p class="note">该条目将于 1 天后再次到期</p>
          </div>
          <button class="btn primary" @click="advance">继续下一张 →</button>
        </template>
      </div>
    </section>

    <!-- 盲听卡：没听懂句 -->
    <section v-else class="panel">
      <div class="card">
        <div class="type-row">
          <span class="type-badge blind-badge">盲听卡</span>
          <span v-if="currentMat?.title" class="note" style="margin:0">来自《{{ currentMat.title }}》</span>
        </div>
        <div class="disc-small">🔊</div>
        <div v-if="currentMat?.loading" class="muted">加载音频…</div>
        <p v-else-if="currentMat?.error" class="error-text small">{{ currentMat.error }}</p>
        <template v-else>
          <button class="btn big" :disabled="!currentSentence || playing" @click="playCurrent">
            {{ playing ? '🔊 播放中…' : '▶ 播放句子' }}
          </button>
          <p class="note">纯听音，不看文本——可反复重听，不限次数。听懂了没？</p>
        </template>

        <div v-if="!revealed" class="rate">
          <button class="know" :disabled="rating" @click="rate(true)">👍 听懂了</button>
          <button class="unknow" :disabled="rating" @click="rate(false)">✖ 还是没听懂</button>
        </div>
        <template v-else>
          <div class="transcript-box">
            <p class="transcript-text">
              {{ currentSentence?.text || current.contextText || '（原句不可用）' }}
            </p>
          </div>
          <p class="note">看看文稿，再听一遍？可以改判，次数不限。</p>
          <div class="rate">
            <button class="btn" :disabled="!currentSentence || playing" @click="playCurrent">🔊 重听</button>
            <button class="know" :disabled="rating" @click="rate(true)">👍 改判：听懂了</button>
            <button class="btn" @click="advance">仍没听懂，继续 →</button>
          </div>
        </template>
      </div>
    </section>

    <p v-if="rateError" class="error-text small">{{ rateError }}</p>

    <audio
      ref="audioEl"
      preload="metadata"
      @timeupdate="onTimeUpdate"
      @pause="onStop"
      @ended="onStop"
    ></audio>
  </div>
</template>

<style scoped>
.page {
  max-width: 680px;
  margin: 24px auto;
  padding: 0 16px;
  font-family: 'Segoe UI', 'Microsoft YaHei', sans-serif;
  color: #1f2937;
}
.topbar {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 16px;
}
.topbar h1 {
  font-size: 18px;
  flex: 1;
  margin: 0;
}
.progress-text {
  font-size: 13px;
  color: #6b7280;
  font-variant-numeric: tabular-nums;
}
.panel {
  background: #fff;
  border: 1px solid #e5e7eb;
  border-radius: 14px;
  padding: 22px;
}
.btn {
  padding: 8px 16px;
  border-radius: 8px;
  border: 1px solid #d1d5db;
  background: #fff;
  cursor: pointer;
  font-size: 14px;
}
.btn.primary {
  background: #1d4ed8;
  color: #fff;
  border-color: #1d4ed8;
}
.btn.big {
  padding: 10px 26px;
  font-size: 16px;
}
.btn.small {
  padding: 4px 10px;
  font-size: 12px;
}
.btn.ghost {
  border-color: transparent;
  color: #374151;
}
.btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}
.muted {
  color: #6b7280;
  font-size: 14px;
}
.note {
  font-size: 12px;
  color: #9ca3af;
  margin-top: 8px;
}
.error-text {
  color: #dc2626;
  font-size: 14px;
  background: #fef2f2;
  border: 1px solid #fecaca;
  border-radius: 10px;
  padding: 10px 14px;
}
.error-text.small {
  padding: 6px 10px;
  font-size: 12px;
  margin-top: 10px;
}
.empty {
  text-align: center;
  padding: 36px 24px;
}
.empty-icon {
  font-size: 40px;
  margin: 0 0 8px;
}
.empty p {
  margin: 6px 0;
}
.card {
  text-align: center;
}
.type-row {
  display: flex;
  justify-content: center;
  align-items: center;
  gap: 10px;
  margin-bottom: 10px;
}
.type-badge {
  font-size: 12px;
  color: #1d4ed8;
  background: #eff6ff;
  border: 1px solid #bfdbfe;
  padding: 2px 10px;
  border-radius: 10px;
}
.blind-badge {
  color: #c2410c;
  background: #fff7ed;
  border-color: #fed7aa;
}
.word {
  font-size: 28px;
  font-weight: 700;
  margin-bottom: 10px;
}
.ctx {
  background: #f9fafb;
  border-radius: 10px;
  padding: 12px;
  font-size: 15px;
  line-height: 1.8;
  margin: 12px 0;
  text-align: left;
}
.ctx b {
  background: #fef9c3;
  padding: 0 3px;
  border-radius: 3px;
}
.ctx.full {
  margin-bottom: 4px;
}
.rate {
  display: flex;
  gap: 12px;
  justify-content: center;
  margin-top: 14px;
  flex-wrap: wrap;
}
.rate button {
  padding: 12px 18px;
  border-radius: 10px;
  border: 1px solid #d1d5db;
  background: #fff;
  font-size: 15px;
  cursor: pointer;
  min-width: 130px;
}
.rate .know:hover {
  background: #ecfdf5;
  border-color: #047857;
}
.rate .unknow:hover {
  background: #fef2f2;
  border-color: #dc2626;
}
.rate button:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}
.rate .btn {
  min-width: 0;
  padding: 12px 16px;
}
.flip-box {
  background: #fefce8;
  border: 1px solid #fde68a;
  border-radius: 10px;
  padding: 12px;
  margin-top: 12px;
}
.flip-meaning {
  margin: 0 0 6px;
  font-size: 15px;
  text-align: left;
}
.flip-meaning.empty {
  color: #b45309;
  font-size: 13px;
}
.disc-small {
  font-size: 40px;
  margin: 6px 0 10px;
}
.transcript-box {
  background: #f9fafb;
  border: 1px dashed #d1d5db;
  border-radius: 10px;
  padding: 12px;
  margin-top: 12px;
}
.transcript-text {
  margin: 0;
  font-size: 15px;
  line-height: 1.8;
  text-align: left;
}
.summary {
  text-align: center;
}
.summary-icon {
  font-size: 40px;
  margin: 0;
}
.summary h2 {
  font-size: 17px;
  margin: 6px 0 16px;
}
.summary-grid {
  display: flex;
  gap: 12px;
  justify-content: center;
  margin-bottom: 12px;
}
.cell {
  background: #f9fafb;
  border-radius: 10px;
  padding: 14px 22px;
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.cell b {
  font-size: 26px;
}
.cell span {
  font-size: 12px;
  color: #6b7280;
}
.cell.ok b {
  color: #047857;
}
.cell.warn b {
  color: #c2410c;
}
.summary .btn {
  margin-top: 10px;
}
</style>
