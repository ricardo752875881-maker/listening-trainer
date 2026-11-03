<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { get, post, request } from '../api/client'
import { useSettingsStore, SPEED_OPTIONS } from '../stores/settings'

const route = useRoute()
const router = useRouter()
const settingsStore = useSettingsStore()
const materialId = route.params.id

const QUIZ_ID_KEY = `ilt:quiz:${materialId}`
const answersKey = (quizId) => `ilt:quizAnswers:${quizId}`

const phase = ref('loading') // loading | quiz | result
const error = ref('')
const material = ref(null)
const sentencesById = ref({})
const quizId = ref('')
const items = ref([]) // [{sentenceId}]
const answers = reactive({}) // sentenceId → userInput
const currentIndex = ref(0)
const inputEl = ref(null)
const submitting = ref(false)

const speed = ref(1.0)
const playingSentenceId = ref('')
const audioEl = ref(null)
let stopAt = null
const TAIL_PADDING_SEC = 0.3 // 词尾衰减余量：ASR 词的 end 早于可听尾音，补一点余量防"最后一个词被切"

const result = ref(null)
const expanded = reactive({}) // sentenceId → bool（错句展开看文稿）

const currentSentence = computed(
  () => sentencesById.value[items.value[currentIndex.value]?.sentenceId] || null
)
const currentAnswered = computed(() => {
  const sid = items.value[currentIndex.value]?.sentenceId
  return sid != null && answers[sid] != null
})
const allAnswered = computed(() => items.value.every((it) => answers[it.sentenceId] != null))

function fmtSentenceLabel(s) {
  return s ? `第 ${currentIndex.value + 1}/${items.value.length} 句` : ''
}

// ---------- 音频：句子区间播放 ----------

function applySpeed() {
  if (audioEl.value) audioEl.value.playbackRate = speed.value
}

function playSentence(sentence) {
  const el = audioEl.value
  if (!el || !sentence || sentence.startSec == null) return
  stopAt = sentence.endSec != null ? sentence.endSec + TAIL_PADDING_SEC : null
  playingSentenceId.value = sentence.id
  el.currentTime = sentence.startSec
  el.play().catch(() => {
    playingSentenceId.value = ''
  })
}

function replayCurrent() {
  playSentence(currentSentence.value)
}

function onTimeUpdate() {
  const el = audioEl.value
  if (!el || stopAt == null) return
  if (el.currentTime >= stopAt) {
    el.pause()
    stopAt = null
  }
}

function onEnded() {
  stopAt = null
  playingSentenceId.value = ''
}

// ---------- 测验初始化 ----------

function loadLocalAnswers(qid) {
  try {
    return JSON.parse(localStorage.getItem(answersKey(qid)) || '{}')
  } catch {
    return {}
  }
}

function saveLocalAnswers() {
  try {
    localStorage.setItem(answersKey(quizId.value), JSON.stringify({ ...answers }))
  } catch {
    /* 本地缓存失败不阻塞 */
  }
}

function setupQuiz(data) {
  const qid = data.id || data.quizId || quizId.value
  quizId.value = qid
  const list = (data.items || []).filter((it) => sentencesById.value[it.sentenceId])
  items.value = list
  // 已答内容回填（FR-030）：服务端 answers 与本地缓存合并，服务端优先
  const local = loadLocalAnswers(qid)
  for (const it of data.items || []) {
    if (it.userInput != null) local[it.sentenceId] = it.userInput
  }
  for (const k of Object.keys(answers)) delete answers[k]
  Object.assign(answers, local)
  if (!list.length) {
    error.value = '没有可测验的句子（材料可能尚未完成对齐）'
    phase.value = 'error'
    return
  }
  phase.value = 'quiz'
  // 跳到第一道未作答的题
  const firstOpen = list.findIndex((it) => answers[it.sentenceId] == null)
  currentIndex.value = firstOpen === -1 ? 0 : firstOpen
  nextTick(() => inputEl.value?.focus())
}

async function init() {
  speed.value = settingsStore.settings.defaultSpeed || 1.0
  settingsStore.load().then(() => {
    speed.value = settingsStore.settings.defaultSpeed || 1.0
    applySpeed()
  })
  let data
  try {
    data = await get(`/api/materials/${materialId}`)
  } catch (e) {
    error.value = e.message || '材料加载失败'
    phase.value = 'error'
    return
  }
  material.value = data.material ? data.material : data
  const map = {}
  for (const s of data.sentences || []) map[s.id] = s
  sentencesById.value = map
  watchRefinement()

  // 恢复未完成的草稿（FR-030）；无草稿则生成新测验
  const stored = localStorage.getItem(QUIZ_ID_KEY)
  if (stored) {
    try {
      const q = await get(`/api/quiz/${stored}`)
      if (q.status && q.status !== 'in_progress') {
        // 旧草稿已交卷，重新生成
        localStorage.removeItem(QUIZ_ID_KEY)
      } else {
        setupQuiz(q)
        return
      }
    } catch {
      localStorage.removeItem(QUIZ_ID_KEY)
    }
  }
  try {
    const gen = await post(`/api/materials/${materialId}/quiz/generate`, { count: 10 })
    localStorage.setItem(QUIZ_ID_KEY, gen.quizId)
    const q = await get(`/api/quiz/${gen.quizId}`)
    setupQuiz({ ...q, quizId: gen.quizId })
  } catch (e) {
    error.value = e.message || '测验生成失败'
    phase.value = 'error'
  }
}

// ---------- 作答 ----------

const draftInput = ref('')

watchCurrent()

function watchCurrent() {
  // 草稿输入随题目切换
  const sid = items.value[currentIndex.value]?.sentenceId
  draftInput.value = sid != null && answers[sid] != null ? answers[sid] : ''
}

function gotoQuestion(i) {
  currentIndex.value = i
  watchCurrent()
  nextTick(() => inputEl.value?.focus())
}

function submitCurrent() {
  const item = items.value[currentIndex.value]
  if (!item) return
  const text = draftInput.value.trim()
  if (!text) return
  answers[item.sentenceId] = text
  saveLocalAnswers()
  if (allAnswered.value) {
    submitAll()
  } else {
    gotoQuestion(currentIndex.value + 1)
  }
}

async function submitAll() {
  submitting.value = true
  try {
    const res = await post(`/api/materials/${materialId}/quiz/submit`, {
      quizId: quizId.value,
      items: items.value.map((it) => ({
        sentenceId: it.sentenceId,
        userInput: answers[it.sentenceId] ?? '',
      })),
    })
    result.value = res
    if (res.material) {
      material.value = { ...material.value, ...res.material }
    }
    phase.value = 'result'
    localStorage.removeItem(QUIZ_ID_KEY)
    localStorage.removeItem(answersKey(quizId.value))
    audioEl.value?.pause()
  } catch (e) {
    error.value = e.message || '判分提交失败，请重试'
  } finally {
    submitting.value = false
  }
}

// ---------- 结果页 ----------

const passed = computed(() => (result.value ? result.value.score >= 90 : false))
const resultRows = computed(() => {
  if (!result.value) return []
  const byId = {}
  for (const r of result.value.results || []) byId[r.sentenceId] = r
  return items.value.map((it) => {
    const sentence = sentencesById.value[it.sentenceId]
    const r = byId[it.sentenceId] || {}
    return {
      sentenceId: it.sentenceId,
      correct: !!r.correct,
      userInput: r.userInput ?? answers[it.sentenceId] ?? '',
      original: sentence?.text ?? '',
    }
  })
})

function normalizeToken(t) {
  return t.toLowerCase().replace(/[^\p{L}\p{N}']/gu, '')
}

// 简单差异高亮：原文中未出现在用户输入里的词高亮
function diffParts(original, mine) {
  const mineSet = new Set(
    (mine || '')
      .split(/\s+/)
      .map(normalizeToken)
      .filter(Boolean)
  )
  return original
    .split(/(\s+)/)
    .map((tok) => ({
      text: tok,
      hit: /\S/.test(tok) && !mineSet.has(normalizeToken(tok)),
    }))
}

function resetQuiz() {
  localStorage.removeItem(QUIZ_ID_KEY)
  if (quizId.value) localStorage.removeItem(answersKey(quizId.value))
  result.value = null
  phase.value = 'loading'
  error.value = ''
  init()
}

async function backToLearning() {
  try {
    await request(`/api/materials/${materialId}`, {
      method: 'PATCH',
      body: JSON.stringify({ stage: 'learning' }),
    })
  } catch {
    /* 流转失败仍跳转 */
  }
  router.push(`/learn/${materialId}`)
}

onMounted(init)
onBeforeUnmount(() => {
  clearInterval(refineTimer)
  audioEl.value?.pause()
})

// AI 对齐后台优化期间进入测验：轮询，完成后用新时间戳重建句子表
let refineTimer = null
function watchRefinement() {
  clearInterval(refineTimer)
  if (material.value?.alignment !== 'refining') return
  refineTimer = setInterval(async () => {
    try {
      const d = await get(`/api/materials/${materialId}`)
      const state = d.material?.alignment
      if (state && state !== 'refining') {
        clearInterval(refineTimer)
        if (state === 'refined') {
          const map = {}
          for (const s of d.sentences || []) map[s.id] = s
          sentencesById.value = map
          material.value = d.material ? d.material : d
        }
      }
    } catch {
      /* 下轮重试 */
    }
  }, 15000)
}
</script>

<template>
  <div class="page">
    <header class="topbar">
      <button class="btn ghost" @click="router.push(`/review/${materialId}`)">← 返回复习</button>
      <h1>检测 · {{ material?.title || '…' }}</h1>
      <span></span>
    </header>

    <p v-if="error" class="error-text">
      {{ error }}
      <button v-if="phase !== 'loading'" class="btn small" @click="init">重试</button>
    </p>
    <p v-else-if="phase === 'loading'" class="muted">正在准备测验…</p>

    <!-- 逐题听写 -->
    <section v-else-if="phase === 'quiz'" class="panel">
      <div class="quiz-head">
        <h2>整句听写 · {{ fmtSentenceLabel(currentSentence) }}</h2>
        <div class="dots">
          <span
            v-for="(it, i) in items"
            :key="it.sentenceId"
            class="dot"
            :class="{ done: answers[it.sentenceId] != null, cur: i === currentIndex }"
            @click="gotoQuestion(i)"
          ></span>
        </div>
      </div>

      <div class="listen-row" v-if="currentSentence">
        <button class="btn" :disabled="playingSentenceId === currentSentence.id" @click="replayCurrent">
          {{ playingSentenceId === currentSentence.id ? '🔊 播放中…' : '🔊 播放句子' }}
        </button>
        <button class="btn" @click="replayCurrent">↺ 重听</button>
        <select v-model.number="speed" class="speed" @change="applySpeed" aria-label="播放速度">
          <option v-for="s in SPEED_OPTIONS" :key="s" :value="s">{{ s }}×</option>
        </select>
        <span class="note">可反复重听 · 变速 0.5×~1.5×</span>
      </div>

      <div v-if="currentAnswered" class="locked-box">
        <p class="muted">本题已提交，不可修改。</p>
        <p class="locked-input">{{ answers[items[currentIndex].sentenceId] }}</p>
        <button
          v-if="currentIndex < items.length - 1"
          class="btn primary"
          @click="gotoQuestion(currentIndex + 1)"
        >
          下一题 →
        </button>
        <button v-else class="btn primary" :disabled="submitting" @click="submitAll">
          {{ submitting ? '判分中…' : '交卷判分' }}
        </button>
      </div>
      <div v-else class="dict">
        <input
          ref="inputEl"
          v-model="draftInput"
          placeholder="默写你听到的完整句子…"
          @keyup.enter="submitCurrent"
        />
        <button class="btn primary" :disabled="!draftInput.trim()" @click="submitCurrent">
          提交
        </button>
      </div>
      <p class="note">逐题提交后不可修改 · 全部提交后统一判分（忽略大小写与全部标点）</p>
    </section>

    <!-- 结果页 -->
    <section v-else-if="phase === 'result'" class="panel">
      <div class="score-block" :class="{ pass: passed }">
        <div class="score-num">{{ result.score }}</div>
        <div class="score-sub">
          {{ result.correctCount }}/{{ result.totalCount }} 句正确 · 达标线 90 分
        </div>
        <div v-if="passed" class="celebrate">🎉 恭喜达标，本材料已进入「已掌握」！</div>
        <div v-else class="fail-note">未达 90 分达标线，建议回到学习巩固或再测一次。</div>
      </div>

      <h3 class="review-title">逐句对照</h3>
      <div
        v-for="row in resultRows"
        :key="row.sentenceId"
        class="result-item"
        :class="row.correct ? 'ok' : 'bad'"
      >
        <div v-if="row.correct">✓ {{ row.original }}</div>
        <template v-else>
          <div>
            ✗ 我的输入：<span class="mine">{{ row.userInput || '（空）' }}</span>
          </div>
          <div class="orig-line">
            原文：
            <template v-for="(p, i) in diffParts(row.original, row.userInput)" :key="i">
              <mark v-if="p.hit" class="hl">{{ p.text }}</mark>
              <span v-else>{{ p.text }}</span>
            </template>
          </div>
          <div class="row-actions">
            <button class="btn small" @click="expanded[row.sentenceId] = !expanded[row.sentenceId]">
              {{ expanded[row.sentenceId] ? '收起文稿' : '查看该句文稿' }}
            </button>
            <button
              class="btn small"
              @click="playSentence(sentencesById[row.sentenceId])"
            >
              🔊 重听
            </button>
          </div>
          <p v-if="expanded[row.sentenceId]" class="transcript-line">{{ row.original }}</p>
        </template>
      </div>

      <div class="result-actions">
        <template v-if="passed">
          <button class="btn" @click="resetQuiz">再测一次</button>
          <button class="btn primary" @click="router.push('/library')">返回材料库</button>
        </template>
        <template v-else>
          <button class="btn" @click="backToLearning">回到学习</button>
          <button class="btn primary" @click="resetQuiz">再测一次</button>
        </template>
      </div>
    </section>

    <audio
      ref="audioEl"
      :src="`/api/materials/${materialId}/audio`"
      preload="metadata"
      @timeupdate="onTimeUpdate"
      @ended="onEnded"
      @pause="playingSentenceId = ''"
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
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  text-align: center;
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
.panel {
  background: #fff;
  border: 1px solid #e5e7eb;
  border-radius: 14px;
  padding: 20px;
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
  display: flex;
  gap: 10px;
  align-items: center;
}
.quiz-head h2 {
  font-size: 16px;
  margin: 0 0 10px;
}
.dots {
  display: flex;
  gap: 6px;
  margin-bottom: 14px;
  flex-wrap: wrap;
}
.dot {
  width: 10px;
  height: 10px;
  border-radius: 50%;
  background: #e5e7eb;
  cursor: pointer;
}
.dot.done {
  background: #93c5fd;
}
.dot.cur {
  background: #1d4ed8;
  outline: 2px solid #bfdbfe;
}
.listen-row {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}
.speed {
  padding: 7px;
  border: 1px solid #d1d5db;
  border-radius: 8px;
  font-size: 14px;
  background: #fff;
}
.dict {
  display: flex;
  gap: 10px;
  margin-top: 14px;
}
.dict input {
  flex: 1;
  padding: 10px;
  border: 1px solid #d1d5db;
  border-radius: 8px;
  font-size: 15px;
}
.locked-box {
  margin-top: 14px;
  background: #f9fafb;
  border-radius: 10px;
  padding: 14px;
}
.locked-box .muted {
  margin: 0 0 6px;
  font-size: 12px;
}
.locked-input {
  font-size: 15px;
  margin: 0 0 10px;
  color: #111827;
}
.score-block {
  text-align: center;
  padding: 10px 0 18px;
  border-bottom: 1px dashed #e5e7eb;
  margin-bottom: 14px;
}
.score-num {
  font-size: 56px;
  font-weight: 700;
  color: #dc2626;
  line-height: 1.1;
}
.score-block.pass .score-num {
  color: #047857;
}
.score-sub {
  color: #6b7280;
  font-size: 14px;
  margin-top: 4px;
}
.celebrate {
  margin-top: 12px;
  background: #ecfdf5;
  border: 1px solid #a7f3d0;
  color: #047857;
  border-radius: 10px;
  padding: 10px;
  font-size: 15px;
}
.fail-note {
  margin-top: 12px;
  background: #fff7ed;
  border: 1px solid #fed7aa;
  color: #c2410c;
  border-radius: 10px;
  padding: 10px;
  font-size: 14px;
}
.review-title {
  font-size: 15px;
  margin: 6px 0 10px;
}
.result-item {
  font-size: 14px;
  padding: 8px 10px;
  border-radius: 8px;
  margin-top: 6px;
  line-height: 1.7;
}
.result-item.ok {
  background: #ecfdf5;
}
.result-item.bad {
  background: #fef2f2;
}
.mine {
  color: #b45309;
}
.orig-line mark.hl {
  background: #fef9c3;
  padding: 0 2px;
  border-radius: 3px;
  color: inherit;
}
.row-actions {
  margin-top: 6px;
  display: flex;
  gap: 8px;
}
.transcript-line {
  margin: 8px 0 0;
  background: #fff;
  border: 1px dashed #fca5a5;
  border-radius: 8px;
  padding: 8px 10px;
  color: #374151;
}
.result-actions {
  margin-top: 16px;
  display: flex;
  gap: 10px;
  justify-content: flex-end;
}
</style>
