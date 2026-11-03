<template>
  <div class="learn" :class="{ marking: markMode }">
    <!-- 顶部栏 -->
    <header class="topbar">
      <button class="btn" @click="router.push('/library')">← 材料库</button>
      <h2>{{ material?.title || '学习' }}</h2>
      <span class="tag">{{ stageLabel }}</span>
      <template v-if="!audioOnly">
        <span class="spacer"></span>
        <button class="btn" @click="goShadow">🎙 跟读</button>
        <button class="btn primary" @click="goReview">进入复习 →</button>
      </template>
    </header>

    <!-- 仅音频模式提示 -->
    <div v-if="audioOnly" class="audioonly-tip">对齐失败，仅音频模式</div>

    <div v-if="loading" class="state">加载中…</div>
    <div v-else-if="loadError" class="state">{{ loadError }}</div>
    <template v-else>
      <!-- 文稿区 -->
      <div v-if="!audioOnly" ref="transcriptEl" class="transcript" @mouseup="onMouseUp">
        <template v-if="showTranscript">
        <div v-for="turn in turns" :key="turn.id" class="turn">
          <div v-if="turn.speakerName" class="speaker">
            {{ speakerTitle(turn) }}
            <span class="playturn" @click="playTurn(turn)">▶ 从这话轮播放</span>
          </div>
          <template v-for="block in turn.blocks" :key="block.id">
            <p v-show="showTranscript" class="en">
              <span
                v-for="rec in block.sentences"
                :key="rec.sentence.id"
                :ref="(el) => setSentEl(rec.sentence.id, el)"
                class="sentence"
                :data-sid="rec.sentence.id"
                :class="sentenceClass(rec)"
                @click="onSentenceClick(rec)"
              >
                <span
                  v-for="(tok, ti) in rec.tokens"
                  :key="ti"
                  class="word"
                  :class="{ marked: tok.marked, karaoke: isKaraokeWord(rec, tok) }"
                  @click.stop="onWordClick(rec, tok)"
                >{{ tok.text }}</span>{{ ' ' }}<span
                  v-if="!rec.sentence.aligned"
                  class="unaligned-badge"
                >未对齐</span><span
                  class="nuicon"
                  :class="{ on: rec.sentence.notUnderstood }"
                  :title="rec.sentence.notUnderstood ? '没听懂（点击取消）' : '标记没听懂'"
                  @click.stop="toggleNotUnderstood(rec)"
                >⚠</span>
              </span>
            </p>
            <p v-if="showTranscript && showTranslation && block.translationLines?.length" class="zh">
              {{ block.translationLines.join('') }}
            </p>
          </template>
        </div>
        </template>
        <!-- 隐藏原文：只显示当前播放句（聚焦模式） -->
        <div v-else-if="focusMode" class="focus-box">
          <template v-if="currentRec">
            <p class="focus-en">
              <span
                v-for="(tok, ti) in currentRec.tokens"
                :key="ti"
                class="focus-word"
                :class="{ karaoke: isKaraokeWord(currentRec, tok) }"
              >{{ tok.text }}</span>
            </p>
            <p v-if="focusTranslation" class="focus-zh">{{ focusTranslation }}</p>
            <p v-else class="focus-empty">（本句无译文）</p>
          </template>
          <p v-else class="focus-empty">开始播放后，这里只显示当前句</p>
        </div>
        <div v-else class="transcript-hidden-tip">原文已隐藏 · 按 J 显示当前句 · 按 H 恢复</div>
      </div>

      <!-- 仅音频模式：降级说明 + 重试对齐 -->
      <div v-else class="degraded">
        <p>对齐失败，本文稿数据不可用，当前仅可播放音频（播放/暂停/变速/进度拖动）。</p>
        <p>可粘贴官方原文稿后重试对齐，成功后补齐文稿数据：</p>
        <textarea v-model="retryTranscript" rows="6" placeholder="粘贴官方原文稿…"></textarea>
        <div class="retry-row">
          <button class="btn primary" :disabled="retrying || !retryTranscript.trim()" @click="retryTranscribe">
            {{ retrying ? '重试中…' : '重试对齐' }}
          </button>
          <span v-if="retryMsg" class="hint">{{ retryMsg }}</span>
        </div>
      </div>
    </template>

    <!-- 划词释义弹层 -->
    <div v-if="popover.show" class="popover" :style="{ left: popover.x + 'px', top: popover.y + 'px' }">
      添加到生词本：
      <input
        v-model="popover.meaning"
        placeholder="释义（可留空），如：adj. 节日的"
        @keydown.enter="saveVocab"
      />
      <select v-model="popover.type">
        <option value="word">单词</option>
        <option value="phrase">短语</option>
      </select>
      <button @click="saveVocab">保存</button>
    </div>

    <!-- 回到当前句 -->
    <button v-if="!store.follow && store.currentSentenceId" class="backbtn" @click="resumeFollow">
      ↓ 回到当前句
    </button>

    <!-- 底部停靠区：工具栏 + 播放条 -->
    <div class="dock">
      <div v-if="!audioOnly" class="toolbar">
        <label><input v-model="showTranscript" type="checkbox" /> 显示原文（H）</label>
        <label v-if="!showTranscript"><input v-model="focusMode" type="checkbox" /> 只显示当前句（J）</label>
        <label v-if="hasTranslation && (showTranscript || !focusMode)"><input v-model="showTranslation" type="checkbox" /> 显示译文</label>
        <label><input v-model="wordHl" type="checkbox" /> 逐词高亮（卡拉OK）</label>
        <button class="markmode" :class="{ on: markMode }" @click="toggleMarkMode">✎ 标记模式</button>
        <span class="hint">{{ markMode ? '当前：划选词/短语添加生词（点击不再跳转）' : '当前：点击单词 = 从该词播放' }}</span>
        <span v-if="noticeMsg" class="notice">{{ noticeMsg }}</span>
      </div>
      <!-- 底部播放条 -->
      <footer class="playerbar">
        <button class="pbtn main" @click="togglePlay">{{ store.playing ? '⏸' : '▶' }}</button>
        <button class="pbtn" title="重播当前句" @click="replaySentence">↺</button>
        <button class="pbtn loop" :class="{ on: store.loopSentence }" title="单句循环" @click="toggleLoop">
          🔁<small>单句</small>
        </button>
        <div ref="progressEl" class="progress" @pointerdown="onSeekDown">
          <div class="bar" :style="{ width: progressPct + '%' }"></div>
        </div>
        <select v-model="rate">
          <option :value="0.5">0.5×</option>
          <option :value="0.75">0.75×</option>
          <option :value="1">1.0×</option>
          <option :value="1.25">1.25×</option>
          <option :value="1.5">1.5×</option>
        </select>
        <span class="time">{{ fmt(store.currentTime) }} / {{ fmt(store.duration) }}</span>
        <AudioPlayer
          ref="player"
          :src="audioSrc"
          :words="currentWords"
          @word="onWord"
          @timeupdate="onTimeUpdate"
          @playstate="onPlayState"
          @loadedmetadata="onLoadedMetadata"
        />
      </footer>
    </div>
  </div>
</template>

<script setup>
import { ref, reactive, computed, watch, onMounted, onBeforeUnmount, nextTick } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { get, post, put, patch } from '../api/client'
import { usePlayerStore } from '../stores/player'
import AudioPlayer from '../player/AudioPlayer.vue'

const RATES = [0.5, 0.75, 1, 1.25, 1.5]

const route = useRoute()
const router = useRouter()
const store = usePlayerStore()
const materialId = route.params.id

const material = ref(null)
const audioOnly = computed(() => !!material.value?.audioOnly)
const stageLabel = computed(
  () => ({ learning: '学习中', reviewing: '复习中', mastered: '已掌握' })[material.value?.stage] || '学习中'
)
const turns = ref([])
const loading = ref(true)
const loadError = ref('')

const showTranslation = ref(true)
const showTranscript = ref(true)
const focusMode = ref(false) // 隐藏原文时只显示当前播放句

// 当前句所在块的译文（聚焦模式展示用）
const focusTranslation = computed(() => {
  const rec = currentRec.value
  if (!rec) return ''
  for (const t of turns.value) {
    for (const b of t.blocks || []) {
      if (b.id === rec.sentence.blockId) return (b.translationLines || []).join('')
    }
  }
  return ''
})
const wordHl = ref(false)
const markMode = ref(false)
const hasTranslation = computed(() =>
  turns.value.some((t) => t.blocks.some((b) => (b.translationLines || []).length))
)

const audioSrc = computed(() => `/api/materials/${materialId}/audio`)

const player = ref(null)
const progressEl = ref(null)
const sentEls = new Map()

let alignedSents = [] // 已对齐句（按 index 排序），用于当前句二分
let recById = new Map() // sentenceId → render record
let markingsBySentence = new Map() // sentenceId → 生词/短语标记
let restored = false
let lastPersistAt = 0
let noticeTimer = null

const seeking = ref(false)
const noticeMsg = ref('')
const popover = reactive({
  show: false,
  x: 0,
  y: 0,
  meaning: '',
  type: 'word',
  text: '',
  sid: null,
  wordStart: 0,
  wordEnd: 0,
})

const retryTranscript = ref('')
const retrying = ref(false)
const retryMsg = ref('')

const rate = computed({
  get: () => store.rate,
  set: (v) => {
    store.setRate(v)
    player.value?.setRate(v)
  },
})

const currentRec = computed(() => (store.currentSentenceId ? recById.get(store.currentSentenceId) : null))
const currentWords = computed(() => currentRec.value?.sentence.words || [])
const progressPct = computed(() =>
  store.duration ? Math.min(100, (store.currentTime / store.duration) * 100) : 0
)

/* ---------- 数据加载与渲染模型 ---------- */

function groupBy(arr, key) {
  const m = new Map()
  for (const it of arr) {
    const k = it[key]
    if (!m.has(k)) m.set(k, [])
    m.get(k).push(it)
  }
  return m
}

function buildTokens(s) {
  const words = Array.isArray(s.words) ? s.words : []
  const parts = String(s.text || '').split(/\s+/).filter((p) => p.length)
  // AI 对齐（官方词 1:1）：words 与官方分词等长，逐词给时间戳；start 为 null 的词不可点击
  if (words.length && words.length === parts.length) {
    return words.map((w, i) => ({
      text: parts[i],
      wordIndex: w.start != null ? i : null,
      marked: false,
    }))
  }
  if (!words.length) return [{ text: s.text || '', wordIndex: null, marked: false }]
  // 旧版基线对齐（ASR 词）：滑动窗口搜索——个别识别误差/缺词只影响该词本身，不级联拖累整句
  const norm = (t) =>
    String(t || '')
      .toLowerCase()
      .replace(/[^\w\s]|_/g, '')
      .replace(/\s+/g, '')
  const tokens = []
  let wi = 0
  for (const p of parts) {
    const target = norm(p)
    let hit = -1
    let consumed = 0
    const limit = Math.min(wi + 5, words.length)
    for (let j = wi; j < limit; j++) {
      let acc = ''
      let k = j
      while (k < words.length && acc.length < target.length) {
        acc += norm(words[k].w)
        k++
      }
      if (acc === target && k > j) {
        hit = j
        consumed = k - j
        break
      }
    }
    if (hit >= 0) {
      tokens.push({ text: p, wordIndex: hit, marked: false })
      wi = hit + consumed
    } else {
      tokens.push({ text: p, wordIndex: null, marked: false })
    }
  }
  return tokens
}

function makeRec(s) {
  return { sentence: s, tokens: buildTokens(s) }
}

function buildModel(detail) {
  const ts = [...(detail.turns || [])].sort((a, b) => a.index - b.index)
  const bs = [...(detail.blocks || [])].sort((a, b) => a.index - b.index)
  const ss = [...(detail.sentences || [])].sort((a, b) => a.index - b.index)

  const markings =
    detail.markings ||
    detail.vocabMarkings ||
    detail.vocab ||
    (detail.reviewItems || []).filter((it) => it.type === 'word' || it.type === 'phrase') ||
    []
  markingsBySentence = groupBy(markings, 'sentenceId')

  alignedSents = ss.filter((s) => s.aligned && s.startSec != null)
  recById = new Map()
  const blocksByTurn = groupBy(bs, 'turnId')
  const sentsByBlock = groupBy(ss, 'blockId')

  turns.value = ts.map((t) => ({
    ...t,
    blocks: (blocksByTurn.get(t.id) || []).map((b) => {
      const sentences = (sentsByBlock.get(b.id) || []).map((s) => makeRec(s))
      for (const r of sentences) recById.set(r.sentence.id, r)
      return { ...b, sentences }
    }),
  }))
  applyMarkings()
}

function resolveMarkingRange(rec, m) {
  const n = rec.tokens.length
  if (
    Number.isInteger(m.wordStart) &&
    Number.isInteger(m.wordEnd) &&
    m.wordStart >= 0 &&
    m.wordEnd < n &&
    m.wordStart <= m.wordEnd
  ) {
    return { start: m.wordStart, end: m.wordEnd }
  }
  if (m.text) {
    const wanted = String(m.text).split(/\s+/).filter(Boolean).map((w) => w.toLowerCase())
    if (wanted.length && wanted.length <= n) {
      outer: for (let i = 0; i + wanted.length <= n; i++) {
        for (let j = 0; j < wanted.length; j++) {
          if ((rec.tokens[i + j].text || '').toLowerCase() !== wanted[j]) continue outer
        }
        return { start: i, end: i + wanted.length - 1 }
      }
    }
  }
  return null
}

function applyMarkings() {
  for (const t of turns.value)
    for (const b of t.blocks)
      for (const rec of b.sentences)
        for (const tok of rec.tokens) tok.marked = false
  for (const [sid, list] of markingsBySentence) {
    const rec = recById.get(sid)
    if (!rec) continue
    for (const m of list) {
      const range = resolveMarkingRange(rec, m)
      if (!range) continue
      for (let i = range.start; i <= range.end; i++) rec.tokens[i].marked = true
    }
  }
}

async function loadDetail() {
  loading.value = true
  loadError.value = ''
  try {
    const detail = await get(`/api/materials/${materialId}`)
    material.value = detail.material || detail
    buildModel(detail)
    maybeRestorePlayhead()
  } catch (e) {
    loadError.value = e.message || '加载失败'
  } finally {
    loading.value = false
  }
}

async function loadPrefs() {
  try {
    const s = await get('/api/settings')
    showTranslation.value = s.showTranslationDefault !== false
    const spd = Number(s.defaultSpeed)
    if (RATES.includes(spd)) store.setRate(spd)
  } catch {
    showTranslation.value = true
  }
}

/* ---------- 播放联动 ---------- */

function findSentenceAt(t) {
  let lo = 0
  let hi = alignedSents.length - 1
  let ans = null
  while (lo <= hi) {
    const mid = (lo + hi) >> 1
    if (alignedSents[mid].startSec <= t) {
      ans = alignedSents[mid]
      lo = mid + 1
    } else {
      hi = mid - 1
    }
  }
  return ans
}

function onTimeUpdate(t) {
  store.setCurrentTime(t)
  const s = findSentenceAt(t)
  if (s && s.id !== store.currentSentenceId) {
    store.setCurrentSentence(s.id)
    syncLoopSpan(s)
  } else if (!s && store.currentSentenceId) {
    store.setCurrentSentence(null)
  }
  persistPlayhead()
}

function onWord({ index }) {
  if (!wordHl.value) return
  store.setCurrentWord(index >= 0 && store.currentSentenceId ? { sentenceId: store.currentSentenceId, index } : null)
}

watch(wordHl, (v) => {
  if (!v) store.setCurrentWord(null)
})

function onPlayState(v) {
  store.setPlaying(v)
  if (!v) persistPlayhead(true)
}

function maybeRestorePlayhead() {
  if (restored || !material.value || !store.duration) return
  restored = true
  const ph = material.value.playheadSec || 0
  if (ph > 0.5 && ph < store.duration - 0.5) player.value?.seek(ph)
}

function onLoadedMetadata(d) {
  store.setDuration(d || material.value?.durationSec || 0)
  maybeRestorePlayhead()
}

function syncLoopSpan(s) {
  if (store.loopSentence && s?.aligned && s.endSec != null) {
    player.value?.playSpan(s.startSec, s.endSec)
  }
}

function playFromSentence(s) {
  if (!s?.aligned || s.startSec == null) return
  if (store.loopSentence && s.endSec != null) player.value?.playSpan(s.startSec, s.endSec)
  else player.value?.playAt(s.startSec)
  store.setFollow(true)
}

function onSentenceClick(rec) {
  if (markMode.value) return
  playFromSentence(rec.sentence)
}

function onWordClick(rec, tok) {
  if (markMode.value || tok.wordIndex == null) return
  const s = rec.sentence
  if (!s.aligned) return
  const w = (s.words || [])[tok.wordIndex]
  if (!w) return
  store.setLoopSentence(false)
  player.value?.stopSpan()
  player.value?.playAt(w.start)
  store.setFollow(true)
}

function playTurn(turn) {
  const first = turn.blocks
    .flatMap((b) => b.sentences)
    .find((r) => r.sentence.aligned && r.sentence.startSec != null)
  if (first) playFromSentence(first.sentence)
}

function replaySentence() {
  const s = currentRec.value?.sentence || alignedSents[0]
  if (s) playFromSentence(s)
}

function togglePlay() {
  if (!player.value) return
  if (store.playing) player.value.pause()
  else player.value.play()
}

/* ---------- 键盘快捷键：空格 播放/暂停；←/→ 快退/快进 5 秒 ---------- */

function seekBy(deltaSec) {
  const target = Math.max(0, (store.currentTime || 0) + deltaSec)
  store.setLoopSentence(false)
  player.value?.stopSpan()
  player.value?.playAt(target)
  store.setFollow(true)
}

function toggleTranscriptView() {
  showTranscript.value = !showTranscript.value
}

function onKeyDown(e) {
  const tag = e.target?.tagName
  if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT' || e.target?.isContentEditable) return
  if (e.code === 'Space') {
    e.preventDefault()
    togglePlay()
  } else if (e.key === 'h' || e.key === 'H') {
    e.preventDefault()
    toggleTranscriptView()
  } else if (e.key === 'j' || e.key === 'J') {
    e.preventDefault()
    if (!showTranscript.value) focusMode.value = !focusMode.value
  } else if (e.key === 'ArrowLeft') {
    e.preventDefault()
    seekBy(-5)
  } else if (e.key === 'ArrowRight') {
    e.preventDefault()
    seekBy(5)
  }
}

function toggleLoop() {
  store.setLoopSentence(!store.loopSentence)
  if (store.loopSentence) {
    const s = currentRec.value?.sentence || alignedSents[0]
    if (s?.aligned && s.endSec != null) player.value?.playSpan(s.startSec, s.endSec)
  } else {
    player.value?.stopSpan()
  }
}

/* ---------- 进度条与持久化 ---------- */

function patchMaterial(body) {
  return patch(`/api/materials/${materialId}`, body).catch((e) => console.warn('保存进度失败', e))
}

function persistPlayhead(force = false) {
  if (!material.value) return
  const now = Date.now()
  if (!force && now - lastPersistAt < 2000) return
  lastPersistAt = now
  patchMaterial({ playheadSec: Math.round(store.currentTime * 10) / 10 })
}

function seekFromEvent(e) {
  const el = progressEl.value
  if (!el || !store.duration) return
  const rect = el.getBoundingClientRect()
  const ratio = Math.min(1, Math.max(0, (e.clientX - rect.left) / rect.width))
  store.setCurrentTime(ratio * store.duration)
  player.value?.seek(store.currentTime)
}

function onSeekDown(e) {
  seeking.value = true
  player.value?.stopSpan() // 允许拖出循环句；跟随到新句后会重新锚定
  e.currentTarget.setPointerCapture?.(e.pointerId)
  seekFromEvent(e)
  const move = (ev) => {
    if (seeking.value) seekFromEvent(ev)
  }
  const up = () => {
    seeking.value = false
    window.removeEventListener('pointermove', move)
    window.removeEventListener('pointerup', up)
    persistPlayhead(true)
  }
  window.addEventListener('pointermove', move)
  window.addEventListener('pointerup', up)
}

function onHide() {
  persistPlayhead(true)
}

/* ---------- 自动跟随 ---------- */

watch(
  () => store.currentSentenceId,
  (id) => {
    if (id && store.follow) scrollToSentence(id)
  }
)

function setSentEl(id, el) {
  if (el) sentEls.set(id, el)
  else sentEls.delete(id)
}

function scrollToSentence(id) {
  if (!showTranscript.value) return // 原文隐藏时目标不可见，跳过自动滚动
  nextTick(() => {
    sentEls.get(id)?.scrollIntoView({ block: 'center', behavior: 'smooth' })
  })
}

function onUserScroll() {
  if (store.follow) store.setFollow(false)
}

function resumeFollow() {
  store.setFollow(true)
  if (store.currentSentenceId) scrollToSentence(store.currentSentenceId)
}

/* ---------- 标记模式（生词/短语） ---------- */

function toggleMarkMode() {
  markMode.value = !markMode.value
  hidePopover()
  window.getSelection()?.removeAllRanges()
}

function hidePopover() {
  popover.show = false
  popover.meaning = ''
}

function onMouseUp() {
  if (!markMode.value) {
    hidePopover()
    const sel = window.getSelection()
    const raw = sel && !sel.isCollapsed ? sel.toString().trim() : ''
    if (raw.length >= 2) notice('先点击工具栏「✎ 标记模式」开启后，再划选添加生词')
    return
  }
  const sel = window.getSelection()
  if (!sel || sel.isCollapsed) {
    hidePopover()
    return
  }
  const raw = sel.toString().trim()
  if (!raw || raw.length >= 40) {
    hidePopover()
    return
  }
  const anchorEl =
    sel.anchorNode?.nodeType === Node.ELEMENT_NODE ? sel.anchorNode : sel.anchorNode?.parentElement
  const sentEl = anchorEl?.closest?.('[data-sid]')
  const rec = sentEl?.dataset?.sid ? recById.get(sentEl.dataset.sid) : null
  if (!rec) {
    hidePopover()
    return
  }
  const tokenEls = sentEl.querySelectorAll('.word')
  let start = -1
  let end = -1
  for (let i = 0; i < tokenEls.length && i < rec.tokens.length; i++) {
    if (sel.containsNode(tokenEls[i], true)) {
      if (start === -1) start = i
      end = i
    }
  }
  if (start === -1) {
    hidePopover()
    return
  }
  const text = rec.tokens
    .slice(start, end + 1)
    .map((t) => t.text)
    .join(' ')
  const rect = sel.getRangeAt(0).getBoundingClientRect()
  popover.text = text
  popover.sid = rec.sentence.id
  popover.wordStart = start
  popover.wordEnd = end
  popover.type = text.includes(' ') ? 'phrase' : 'word'
  popover.x = Math.max(10, Math.min(rect.left, window.innerWidth - 340))
  popover.y = Math.max(10, rect.top - 72)
  popover.show = true
}

function onDocDown(e) {
  if (popover.show && !e.target.closest?.('.popover')) hidePopover()
}

async function saveVocab() {
  if (!popover.sid) return
  try {
    await post(`/api/materials/${materialId}/sentences/${popover.sid}/vocab`, {
      text: popover.text,
      wordStart: popover.wordStart,
      wordEnd: popover.wordEnd,
      type: popover.type,
      meaning: popover.meaning.trim() || undefined,
    })
    if (!markingsBySentence.has(popover.sid)) markingsBySentence.set(popover.sid, [])
    markingsBySentence.get(popover.sid).push({
      sentenceId: popover.sid,
      text: popover.text,
      wordStart: popover.wordStart,
      wordEnd: popover.wordEnd,
      type: popover.type,
      meaning: popover.meaning.trim() || null,
    })
    applyMarkings()
    hidePopover()
    window.getSelection()?.removeAllRanges()
    notice('已加入生词本')
  } catch (e) {
    notice('保存失败：' + (e.message || e))
  }
}

/* ---------- 没听懂 ---------- */

async function toggleNotUnderstood(rec) {
  const s = rec.sentence
  const next = !s.notUnderstood
  s.notUnderstood = next
  try {
    await put(`/api/materials/${materialId}/sentences/${s.id}/not-understood`, { marked: next })
  } catch (e) {
    s.notUnderstood = !next
    notice('操作失败：' + (e.message || e))
  }
}

/* ---------- 顶部栏跳转 ---------- */

function goShadow() {
  router.push(`/shadow/${materialId}`)
}

async function goReview() {
  try {
    await patchMaterial({ stage: 'reviewing' })
  } finally {
    router.push(`/review/${materialId}`)
  }
}

// 同组件路由参数变化（材料切换）时整页重载，避免复用旧状态
watch(() => route.params.id, (v, old) => {
  if (v && old && v !== old) window.location.reload()
})

/* ---------- 仅音频模式：重试对齐 ---------- */

async function retryTranscribe() {
  if (!retryTranscript.value.trim() || retrying.value) return
  retrying.value = true
  retryMsg.value = ''
  try {
    await post(`/api/materials/${materialId}/retry-transcribe`, { transcript: retryTranscript.value })
    retryMsg.value = '对齐成功，正在载入文稿…'
    restored = false
    await loadDetail()
  } catch (e) {
    retryMsg.value = '重试失败：' + (e.message || e)
  } finally {
    retrying.value = false
  }
}

/* ---------- 其他 ---------- */

function speakerTitle(turn) {
  return turn.speakerNameZh ? `${turn.speakerName} ${turn.speakerNameZh}` : turn.speakerName
}

function sentenceClass(rec) {
  return {
    current: store.currentSentenceId === rec.sentence.id,
    nu: rec.sentence.notUnderstood,
    unaligned: !rec.sentence.aligned,
  }
}

function isKaraokeWord(rec, tok) {
  return (
    wordHl.value &&
    tok.wordIndex != null &&
    store.currentWord?.sentenceId === rec.sentence.id &&
    store.currentWord.index === tok.wordIndex
  )
}

function notice(msg) {
  noticeMsg.value = msg
  clearTimeout(noticeTimer)
  noticeTimer = setTimeout(() => (noticeMsg.value = ''), 3000)
}

function fmt(sec) {
  sec = Math.max(0, Math.floor(sec || 0))
  const m = String(Math.floor(sec / 60)).padStart(2, '0')
  const s = String(sec % 60).padStart(2, '0')
  return `${m}:${s}`
}

onMounted(async () => {
  window.addEventListener('wheel', onUserScroll, { passive: true })
  window.addEventListener('touchmove', onUserScroll, { passive: true })
  window.addEventListener('keydown', onKeyDown)
  document.addEventListener('mousedown', onDocDown)
  document.addEventListener('visibilitychange', onHide)
  window.addEventListener('beforeunload', onHide)
  store.reset()
  await Promise.all([loadPrefs(), loadDetail()])
  player.value?.setRate(store.rate)
})

onBeforeUnmount(() => {
  window.removeEventListener('wheel', onUserScroll)
  window.removeEventListener('keydown', onKeyDown)
  window.removeEventListener('touchmove', onUserScroll)
  document.removeEventListener('mousedown', onDocDown)
  document.removeEventListener('visibilitychange', onHide)
  window.removeEventListener('beforeunload', onHide)
  persistPlayhead(true)
  store.reset()
})
</script>

<style scoped>
.learn {
  min-height: 100vh;
  background: #fff;
  color: #1f2937;
  padding-bottom: 140px;
  font-size: 15px;
}
.topbar {
  display: flex;
  align-items: center;
  gap: 14px;
  padding: 12px 24px;
  border-bottom: 1px solid #e5e7eb;
  position: sticky;
  top: 0;
  background: #fff;
  z-index: 5;
}
.topbar h2 {
  font-size: 16px;
  margin: 0;
}
.tag {
  font-size: 12px;
  background: #dbeafe;
  color: #1d4ed8;
  padding: 2px 8px;
  border-radius: 10px;
}
.spacer {
  margin-left: auto;
}
.btn {
  padding: 7px 14px;
  border-radius: 8px;
  border: 1px solid #d1d5db;
  background: #fff;
  cursor: pointer;
  font-size: 13px;
}
.btn.primary {
  background: #1d4ed8;
  color: #fff;
  border-color: #1d4ed8;
}
.audioonly-tip {
  margin: 16px 24px 0;
  padding: 10px 14px;
  background: #fef2f2;
  border: 1px solid #fecaca;
  color: #b91c1c;
  border-radius: 8px;
  font-size: 13px;
}
.toolbar {
  display: flex;
  gap: 14px;
  padding: 6px 24px 2px;
  font-size: 13px;
  color: #6b7280;
  align-items: center;
  flex-wrap: wrap;
}
.transcript-hidden-tip {
  text-align: center;
  color: #9ca3af;
  padding: 80px 0;
  font-size: 14px;
}
.focus-box {
  max-width: 760px;
  margin: 40px auto 0;
  text-align: center;
  padding: 0 24px;
}
.focus-en {
  font-size: 24px;
  line-height: 1.9;
  font-weight: 500;
}
.focus-word + .focus-word::before {
  content: ' ';
}
.focus-word.karaoke {
  background: #bfdbfe;
  border-radius: 4px;
}
.focus-zh {
  margin-top: 16px;
  font-size: 15px;
  color: #6b7280;
  line-height: 1.8;
}
.focus-empty {
  color: #9ca3af;
  padding: 60px 0;
}
.toolbar label {
  cursor: pointer;
  user-select: none;
}
.markmode {
  background: #ecfdf5;
  border: 1px solid #a7f3d0;
  color: #047857;
  padding: 3px 10px;
  border-radius: 8px;
  cursor: pointer;
  font-size: 13px;
}
.markmode.on {
  background: #047857;
  color: #fff;
}
.hint {
  font-size: 12px;
  color: #9ca3af;
}
.notice {
  font-size: 12px;
  color: #b45309;
}
.state {
  padding: 48px 24px;
  text-align: center;
  color: #6b7280;
}
.transcript {
  max-width: 760px;
  margin: 0 auto;
  padding: 24px;
}
.turn {
  margin-bottom: 26px;
}
.speaker {
  font-weight: 700;
  font-size: 16px;
  margin-bottom: 6px;
}
.playturn {
  font-weight: 400;
  font-size: 12px;
  color: #9ca3af;
  cursor: pointer;
  margin-left: 8px;
  user-select: none;
}
.playturn:hover {
  color: #1d4ed8;
}
.en {
  font-size: 17px;
  line-height: 2;
  margin: 0 0 4px;
}
.zh {
  font-size: 14.5px;
  line-height: 1.7;
  color: #6b7280;
  margin: 6px 0 12px;
}
.sentence {
  padding: 1px 2px;
  border-radius: 3px;
  cursor: pointer;
  box-decoration-break: clone;
  -webkit-box-decoration-break: clone;
}
.sentence.current {
  background: #fef9c3;
}
.sentence.nu {
  border-bottom: 2px dashed #dc2626;
}
.sentence.unaligned {
  opacity: 0.55;
  cursor: default;
}
.word + .word::before {
  content: ' ';
}
.word:hover {
  background: #f3f4f6;
}
.sentence.current .word:hover {
  background: #fde68a;
}
.marking .word {
  cursor: text;
}
.marking .sentence {
  cursor: text;
}
.word.marked {
  background: #fef9c3;
  border-bottom: 2px solid #f59e0b;
  padding: 0 2px;
  border-radius: 2px;
}
.word.karaoke {
  background: #bfdbfe;
  border-radius: 2px;
}
.unaligned-badge {
  font-size: 11px;
  color: #9ca3af;
  border: 1px solid #d1d5db;
  border-radius: 4px;
  padding: 0 4px;
  margin-left: 4px;
  user-select: none;
}
.nuicon {
  display: inline-block;
  margin-left: 8px;
  font-size: 14px;
  color: #d1d5db;
  cursor: pointer;
  vertical-align: middle;
  user-select: none;
}
.nuicon:hover {
  color: #f59e0b;
}
.nuicon.on {
  color: #dc2626;
}
.degraded {
  max-width: 760px;
  margin: 0 auto;
  padding: 24px;
  color: #6b7280;
}
.degraded textarea {
  width: 100%;
  border: 1px solid #d1d5db;
  border-radius: 8px;
  padding: 10px;
  font-size: 14px;
  box-sizing: border-box;
  resize: vertical;
}
.retry-row {
  margin-top: 10px;
  display: flex;
  align-items: center;
  gap: 10px;
}
.popover {
  position: fixed;
  background: #111827;
  color: #fff;
  padding: 12px;
  border-radius: 10px;
  font-size: 13px;
  z-index: 9;
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.25);
  display: flex;
  align-items: center;
  gap: 8px;
}
.popover input {
  padding: 6px 8px;
  border-radius: 6px;
  border: none;
  font-size: 13px;
  width: 180px;
}
.popover select {
  font-size: 13px;
  padding: 5px 4px;
  border-radius: 6px;
  border: none;
}
.popover button {
  background: #f59e0b;
  color: #fff;
  border: none;
  padding: 6px 12px;
  border-radius: 6px;
  cursor: pointer;
}
.backbtn {
  position: fixed;
  right: 24px;
  bottom: 110px;
  background: #1d4ed8;
  color: #fff;
  border: none;
  padding: 10px 16px;
  border-radius: 999px;
  cursor: pointer;
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.2);
  z-index: 8;
}
.dock {
  position: fixed;
  bottom: 0;
  left: 0;
  right: 0;
  background: #fff;
  border-top: 1px solid #e5e7eb;
  z-index: 6;
}
.playerbar {
  padding: 8px 24px 10px;
  display: flex;
  align-items: center;
  gap: 14px;
}
.pbtn {
  width: 38px;
  height: 38px;
  border-radius: 50%;
  border: 1px solid #d1d5db;
  background: #fff;
  cursor: pointer;
  font-size: 14px;
  line-height: 1;
  display: inline-flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
}
.pbtn small {
  font-size: 9px;
  transform: scale(0.9);
}
.pbtn.main {
  background: #1d4ed8;
  color: #fff;
  border-color: #1d4ed8;
  width: 44px;
  height: 44px;
}
.pbtn.loop.on {
  background: #dbeafe;
  border-color: #93c5fd;
}
.progress {
  flex: 1;
  height: 6px;
  background: #e5e7eb;
  border-radius: 3px;
  position: relative;
  cursor: pointer;
  touch-action: none;
}
.progress .bar {
  position: absolute;
  left: 0;
  top: 0;
  bottom: 0;
  background: #1d4ed8;
  border-radius: 3px;
}
.playerbar select {
  font-size: 13px;
  padding: 4px;
}
.time {
  font-size: 12px;
  color: #6b7280;
  white-space: nowrap;
}
</style>
