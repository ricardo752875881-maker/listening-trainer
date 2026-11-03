<script setup>
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { get, post, del } from '../api/client'
import { useSettingsStore, SPEED_OPTIONS } from '../stores/settings'

const route = useRoute()
const router = useRouter()
const settingsStore = useSettingsStore()
const materialId = route.params.id

const material = ref(null)
const error = ref('')
const loading = ref(true)
const items = ref([]) // active 跟读片段（按音频起始排序）
const currentIndex = ref(-1)
const loop = ref(false)
const speed = ref(1.0)
const playingId = ref('')
const removingId = ref('')

const recommendOpen = ref(false)
const recommendLoading = ref(false)
const recommendError = ref('')
const candidates = ref([]) // [{text, anchorStart, anchorEnd, _state: 'pending'|'adopting'|'ignoring'|'done'}]

const audioEl = ref(null)
let stopAt = null
const TAIL_PADDING_SEC = 0.3 // 词尾衰减余量：ASR 词的 end 早于可听尾音，补一点余量防"最后一个词被切"

const isAudioOnly = computed(() => !!material.value?.audioOnly)
const currentItem = computed(() =>
  currentIndex.value >= 0 ? items.value[currentIndex.value] : null
)

function applySpeed() {
  if (audioEl.value) audioEl.value.playbackRate = speed.value
}

// ---------- 音频：片段区间播放，播完自动停顿 ----------

function playItem(item) {
  const el = audioEl.value
  if (!el || !item || item.audioStartSec == null) return
  stopAt = item.audioEndSec != null ? item.audioEndSec + TAIL_PADDING_SEC : null
  playingId.value = item.id
  el.currentTime = item.audioStartSec
  el.play().catch(() => {
    playingId.value = ''
  })
}

function playAt(index) {
  if (index < 0 || index >= items.value.length) return
  currentIndex.value = index
  playItem(items.value[index])
}

function replayCurrent() {
  if (currentItem.value) playItem(currentItem.value)
}

function nextItem() {
  if (currentIndex.value < items.value.length - 1) {
    playAt(currentIndex.value + 1)
  } else {
    audioEl.value?.pause()
    stopAt = null
  }
}

function onTimeUpdate() {
  const el = audioEl.value
  if (!el || stopAt == null) return
  if (el.currentTime >= stopAt) {
    if (loop.value && currentItem.value) {
      el.currentTime = currentItem.value.audioStartSec
    } else {
      el.pause()
      stopAt = null
      // 播完自动停顿：保留高亮，等用户按键推进（FR-025）
    }
  }
}

// ---------- 数据 ----------

async function loadItems() {
  const data = await get(`/api/materials/${materialId}`)
  material.value = data.material ? data.material : data
  const all = data.shadowingItems || []
  items.value = all
    .filter((it) => it.status === 'active')
    .slice()
    .sort((a, b) => (a.audioStartSec ?? 0) - (b.audioStartSec ?? 0))
  watchRefinement()
}

// AI 对齐后台优化期间进入本页：轮询，完成后刷新条目（播放区间由后端按锚点重推）
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
        if (state === 'refined') await loadItems()
      }
    } catch {
      /* 下轮重试 */
    }
  }, 15000)
}

async function init() {
  loading.value = true
  error.value = ''
  try {
    await loadItems()
    if (items.value.length && currentIndex.value === -1) {
      currentIndex.value = 0
    }
  } catch (e) {
    error.value = e.message || '跟读清单加载失败'
  } finally {
    loading.value = false
  }
}

async function removeItem(item) {
  if (!window.confirm(`移除跟读片段？\n「${item.text}」`)) return
  removingId.value = item.id
  try {
    await del(`/api/materials/${materialId}/shadowing/${item.id}`)
    const idx = items.value.findIndex((it) => it.id === item.id)
    items.value = items.value.filter((it) => it.id !== item.id)
    if (currentIndex.value >= items.value.length) {
      currentIndex.value = items.value.length - 1
    } else if (idx >= 0 && idx < currentIndex.value) {
      currentIndex.value -= 1
    }
  } catch (e) {
    error.value = e.message || '移除失败'
  } finally {
    removingId.value = ''
  }
}

// ---------- 大模型推荐 ----------

const llmReady = computed(() => {
  const llm = settingsStore.settings.llm
  return !!(llm && llm.enabled && llm.apiKey)
})

async function openRecommend() {
  recommendOpen.value = !recommendOpen.value
  if (recommendOpen.value && !candidates.value.length && !recommendError.value) {
    await fetchCandidates()
  }
}

async function fetchCandidates() {
  recommendLoading.value = true
  recommendError.value = ''
  try {
    const res = await post(`/api/materials/${materialId}/shadowing/recommend`, {})
    candidates.value = (res.candidates || []).map((c) => ({ ...c, _state: 'pending' }))
    if (!candidates.value.length) {
      recommendError.value = '没有新的推荐片段'
    }
  } catch (e) {
    recommendError.value = e.message || '推荐生成失败，请重试'
  } finally {
    recommendLoading.value = false
  }
}

const RECOMMEND_REASON_LABELS = { 1: '句型高频', 2: '连读弱读', 3: '表达地道' }

function reasonTags(reason) {
  return String(reason || '')
    .split(/[,，\s]+/)
    .map((k) => RECOMMEND_REASON_LABELS[k])
    .filter(Boolean)
}

async function adoptCandidate(c) {
  c._state = 'adopting'
  try {
    await post(`/api/materials/${materialId}/shadowing`, {
      text: c.text,
      anchorStart: c.anchorStart,
      anchorEnd: c.anchorEnd,
      source: 'llm',
    })
    c._state = 'done'
    await loadItems()
  } catch (e) {
    c._state = 'pending'
    recommendError.value = e.message || '采纳失败，请重试'
  }
}

async function ignoreCandidate(c) {
  c._state = 'ignoring'
  try {
    // 先创建为 llm 条目再忽略（与既有 active 片段去重、不再重复推荐）
    const created = await post(`/api/materials/${materialId}/shadowing`, {
      text: c.text,
      anchorStart: c.anchorStart,
      anchorEnd: c.anchorEnd,
      source: 'llm',
    })
    await post(`/api/materials/${materialId}/shadowing/${created.id}/ignore`, {})
    c._state = 'done'
  } catch (e) {
    c._state = 'pending'
    recommendError.value = e.message || '操作失败，请重试'
  }
}

onMounted(async () => {
  speed.value = settingsStore.settings.defaultSpeed || 1.0
  settingsStore.load().then(() => {
    speed.value = settingsStore.settings.defaultSpeed || 1.0
    applySpeed()
  })
  init()
})
onBeforeUnmount(() => audioEl.value?.pause())
</script>

<template>
  <div class="page">
    <header class="topbar">
      <button class="btn ghost" @click="router.push(`/learn/${materialId}`)">← 返回学习</button>
      <h1>跟读 · {{ material?.title || '…' }}</h1>
      <button v-if="llmReady" class="btn" :disabled="recommendLoading" @click="openRecommend">
        {{ recommendLoading ? '推荐生成中…' : '✨ 获取推荐' }}
      </button>
    </header>

    <p v-if="error" class="error-text">{{ error }}</p>

    <!-- 推荐候选面板 -->
    <section v-if="recommendOpen" class="panel recommend">
      <h2>跟读推荐（大模型生成）</h2>
      <p class="note">选择采纳加入跟读清单，或忽略（不再重复推荐）。</p>
      <p v-if="recommendLoading" class="muted">正在生成候选片段…</p>
      <template v-else>
        <div v-for="(c, i) in candidates" :key="i" class="candidate" v-show="c._state !== 'done'">
          <p class="candidate-text">{{ c.text }}</p>
          <div v-if="reasonTags(c.reason).length" class="candidate-reason">
            <span v-for="t in reasonTags(c.reason)" :key="t" class="reason-tag">{{ t }}</span>
          </div>
          <div class="candidate-actions">
            <button
              class="btn small primary"
              :disabled="c._state !== 'pending'"
              @click="adoptCandidate(c)"
            >
              {{ c._state === 'adopting' ? '采纳中…' : '采纳' }}
            </button>
            <button
              class="btn small"
              :disabled="c._state !== 'pending'"
              @click="ignoreCandidate(c)"
            >
              {{ c._state === 'ignoring' ? '忽略中…' : '忽略' }}
            </button>
          </div>
        </div>
        <p v-if="recommendError" class="error-text small">{{ recommendError }}</p>
        <div class="row-actions">
          <button class="btn small" :disabled="recommendLoading" @click="fetchCandidates">
            重新获取
          </button>
        </div>
      </template>
    </section>

    <p v-if="loading" class="muted">加载中…</p>

    <!-- 仅音频模式 -->
    <section v-else-if="isAudioOnly" class="panel empty">
      <p>该材料对齐失败（仅音频模式），无法定位跟读片段。请先重试对齐。</p>
      <button class="btn" @click="router.push(`/learn/${materialId}`)">回到学习</button>
    </section>

    <!-- 空清单 -->
    <section v-else-if="!items.length" class="panel empty">
      <p>跟读清单为空。</p>
      <p class="muted">
        先到学习界面选中任意文本标记「想跟读」<template v-if="llmReady">，或点击右上角「获取推荐」采纳推荐片段</template>。
      </p>
      <button class="btn primary" @click="router.push(`/learn/${materialId}`)">去标记片段</button>
    </section>

    <template v-else>
      <section class="panel">
        <div
          v-for="(item, i) in items"
          :key="item.id"
          class="shadow-line"
          :class="{ playing: i === currentIndex }"
          @click="playAt(i)"
        >
          <span class="idx">{{ i === currentIndex ? '▶' : i + 1 }}</span>
          <span class="txt">{{ item.text }}</span>
          <span v-if="item.source === 'llm'" class="tag">推荐</span>
          <button
            class="btn small danger"
            :disabled="removingId === item.id"
            @click.stop="removeItem(item)"
          >
            移除
          </button>
        </div>
        <p class="note">点击任意条目可跳转播放 · 播完自动停顿，模仿原音跟读</p>
      </section>

      <section class="panel controls-panel">
        <div class="controls">
          <button class="btn primary" @click="replayCurrent">↺ 重听本句</button>
          <button class="btn" @click="nextItem">下一句 →</button>
          <button class="btn" :class="{ active: loop }" @click="loop = !loop">
            🔁 单句循环{{ loop ? '·开' : '' }}
          </button>
          <select v-model.number="speed" class="speed" @change="applySpeed" aria-label="播放速度">
            <option v-for="s in SPEED_OPTIONS" :key="s" :value="s">{{ s }}×</option>
          </select>
        </div>
        <p v-if="currentItem" class="note now-playing">
          当前第 {{ currentIndex + 1 }}/{{ items.length }} 条 · 播完自动停顿，可变速、可循环
        </p>
      </section>
    </template>

    <audio
      ref="audioEl"
      :src="`/api/materials/${materialId}/audio`"
      preload="metadata"
      @timeupdate="onTimeUpdate"
      @pause="playingId = ''"
      @ended="playingId = ''"
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
}
.panel {
  background: #fff;
  border: 1px solid #e5e7eb;
  border-radius: 14px;
  padding: 20px;
  margin-bottom: 16px;
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
.btn.danger {
  color: #dc2626;
  border-color: #fecaca;
}
.btn.ghost {
  border-color: transparent;
  color: #374151;
}
.btn.active {
  background: #eff6ff;
  border-color: #3b82f6;
  color: #1d4ed8;
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
}
.empty {
  text-align: center;
  padding: 30px 20px;
}
.recommend h2 {
  font-size: 15px;
  margin: 0 0 4px;
}
.candidate {
  background: #f9fafb;
  border-radius: 10px;
  padding: 12px 14px;
  margin-top: 10px;
}
.candidate-text {
  margin: 0 0 8px;
  font-size: 14.5px;
  line-height: 1.7;
}
.candidate-reason {
  display: flex;
  gap: 6px;
  margin: 4px 0 6px;
}
.reason-tag {
  font-size: 11px;
  color: #b45309;
  background: #fef3c7;
  border: 1px solid #fed7aa;
  border-radius: 10px;
  padding: 1px 8px;
}
.candidate-actions {
  display: flex;
  gap: 8px;
}
.row-actions {
  margin-top: 10px;
}
.shadow-line {
  display: flex;
  align-items: center;
  gap: 12px;
  background: #f9fafb;
  border: 1px solid transparent;
  border-radius: 10px;
  padding: 12px 14px;
  margin-bottom: 10px;
  font-size: 14.5px;
  cursor: pointer;
}
.shadow-line:hover {
  background: #f3f4f6;
}
.shadow-line.playing {
  background: #eff6ff;
  border-color: #bfdbfe;
}
.shadow-line .idx {
  color: #9ca3af;
  min-width: 16px;
  text-align: center;
}
.shadow-line.playing .idx {
  color: #1d4ed8;
}
.shadow-line .txt {
  flex: 1;
  line-height: 1.6;
}
.tag {
  font-size: 11px;
  color: #7c3aed;
  background: #f3e8ff;
  border-radius: 8px;
  padding: 1px 8px;
  white-space: nowrap;
}
.controls-panel {
  position: sticky;
  bottom: 12px;
}
.controls {
  display: flex;
  gap: 10px;
  align-items: center;
  flex-wrap: wrap;
}
.speed {
  padding: 8px;
  border: 1px solid #d1d5db;
  border-radius: 8px;
  font-size: 14px;
  background: #fff;
}
.now-playing {
  margin-bottom: 0;
}
</style>
