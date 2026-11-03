<script setup>
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { get, request } from '../api/client'
import { useSettingsStore } from '../stores/settings'
import { SPEED_OPTIONS } from '../stores/settings'

const route = useRoute()
const router = useRouter()
const settingsStore = useSettingsStore()
const materialId = route.params.id

const material = ref(null)
const error = ref('')
const audioEl = ref(null)
const playing = ref(false)
const currentTime = ref(0)
const duration = ref(0)
const speed = ref(1.0)

const audioUrl = `/api/materials/${materialId}/audio`
const isAudioOnly = computed(() => !!material.value?.audioOnly)
const progressPct = computed(() =>
  duration.value > 0 ? Math.min(100, (currentTime.value / duration.value) * 100) : 0
)
const fmt = (sec) => {
  if (!Number.isFinite(sec) || sec < 0) sec = 0
  const m = Math.floor(sec / 60)
  const s = Math.floor(sec % 60)
  return `${m}:${String(s).padStart(2, '0')}`
}

let saveTimer = null

function persistPlayhead() {
  const el = audioEl.value
  if (!el || !material.value) return
  request(`/api/materials/${materialId}`, {
    method: 'PATCH',
    body: JSON.stringify({ playheadSec: el.currentTime }),
  }).catch(() => {})
}

function togglePlay() {
  const el = audioEl.value
  if (!el) return
  if (el.paused) {
    el.play().catch(() => {})
  } else {
    el.pause()
  }
}

function onTimeUpdate() {
  currentTime.value = audioEl.value?.currentTime || 0
}

function onLoadedMetadata() {
  const el = audioEl.value
  if (!el) return
  duration.value = el.duration || material.value?.durationSec || 0
  // 恢复上次播放位置（FR-022）
  const saved = Number(material.value?.playheadSec) || 0
  if (saved > 0 && saved < (duration.value || Infinity) - 1) {
    el.currentTime = saved
  }
  currentTime.value = el.currentTime || 0
}

function applySpeed() {
  if (audioEl.value) audioEl.value.playbackRate = speed.value
}

async function enterReviewStage() {
  // 学习 → 复习流转（FR-033）；幂等，已被其他入口设置时跳过
  try {
    const m = material.value
    if (m && m.stage === 'learning') {
      await request(`/api/materials/${materialId}`, {
        method: 'PATCH',
        body: JSON.stringify({ stage: 'reviewing' }),
      })
      m.stage = 'reviewing'
    }
  } catch {
    // 流转失败不阻塞泛听
  }
}

onMounted(async () => {
  speed.value = settingsStore.settings.defaultSpeed || 1.0
  settingsStore.load().then(() => {
    speed.value = settingsStore.settings.defaultSpeed || 1.0
    applySpeed()
  })
  try {
    const data = await get(`/api/materials/${materialId}`)
    material.value = data.material ? data.material : data
    // 进入复习即完成 学习→复习 流转
    enterReviewStage()
  } catch (e) {
    error.value = e.message || '材料加载失败'
  }
  // 播放位置节流持久化
  saveTimer = setInterval(() => {
    if (playing.value) persistPlayhead()
  }, 5000)
})

onBeforeUnmount(() => {
  clearInterval(saveTimer)
  persistPlayhead()
})
</script>

<template>
  <div class="page">
    <header class="topbar">
      <button class="btn ghost" @click="router.push('/library')">← 退出</button>
      <h1>复习 · {{ material?.title || '…' }}</h1>
      <span class="badge" v-if="material">复习中</span>
    </header>

    <p v-if="error" class="error-text">{{ error }}</p>
    <p v-else-if="!material" class="muted">加载中…</p>

    <template v-else>
      <section class="panel blind">
        <div class="disc">🎧</div>
        <h2>文稿已隐藏</h2>
        <p class="muted">进入复习阶段，全部文稿与译文已隐藏。泛听整篇，随时可开始检测。</p>
        <div class="controls">
          <button class="btn big" @click="togglePlay">{{ playing ? '⏸ 暂停' : '▶ 播放' }}</button>
          <select v-model.number="speed" class="speed" @change="applySpeed" aria-label="播放速度">
            <option v-for="s in SPEED_OPTIONS" :key="s" :value="s">{{ s }}×</option>
          </select>
        </div>
        <div class="progress-wrap" aria-label="播放进度（只读）">
          <span class="time">{{ fmt(currentTime) }}</span>
          <div class="progress-track">
            <div class="progress-fill" :style="{ width: progressPct + '%' }"></div>
          </div>
          <span class="time">{{ fmt(duration) }}</span>
        </div>
        <p class="note">进度只读 · 可用控制仅限播放/暂停与变速（FR-027/028）</p>

        <div v-if="isAudioOnly" class="warn-box">
          该材料对齐失败（仅音频模式），无法开始检测。可返回学习界面重试对齐。
        </div>
        <div class="quiz-entry">
          <button
            class="btn warn"
            :disabled="isAudioOnly"
            @click="router.push(`/quiz/${materialId}`)"
          >
            开始检测 →
          </button>
          <p class="note">不强制听完整篇，随时开始</p>
        </div>
      </section>
    </template>

    <audio
      ref="audioEl"
      :src="audioUrl"
      preload="metadata"
      @play="playing = true"
      @pause="playing = false; persistPlayhead()"
      @loadedmetadata="onLoadedMetadata"
      @timeupdate="onTimeUpdate"
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
.badge {
  font-size: 12px;
  color: #1d4ed8;
  background: #eff6ff;
  border: 1px solid #bfdbfe;
  padding: 2px 10px;
  border-radius: 10px;
  white-space: nowrap;
}
.panel {
  background: #fff;
  border: 1px solid #e5e7eb;
  border-radius: 14px;
  padding: 24px 20px;
}
.blind {
  text-align: center;
}
.disc {
  width: 110px;
  height: 110px;
  border-radius: 50%;
  background: linear-gradient(135deg, #1e3a8a, #3b82f6);
  margin: 0 auto 14px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 40px;
}
.blind h2 {
  font-size: 17px;
  margin: 0 0 6px;
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
.controls {
  margin-top: 18px;
  display: flex;
  gap: 10px;
  justify-content: center;
  align-items: center;
}
.btn {
  padding: 8px 16px;
  border-radius: 8px;
  border: 1px solid #d1d5db;
  background: #fff;
  cursor: pointer;
  font-size: 14px;
}
.btn.big {
  padding: 10px 26px;
  font-size: 16px;
}
.btn.primary {
  background: #1d4ed8;
  color: #fff;
  border-color: #1d4ed8;
}
.btn.warn {
  background: #ea580c;
  color: #fff;
  border-color: #ea580c;
}
.btn.ghost {
  border-color: transparent;
  color: #374151;
}
.btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}
.btn.warn:disabled {
  background: #d1d5db;
  border-color: #d1d5db;
  color: #6b7280;
}
.speed {
  padding: 8px;
  border: 1px solid #d1d5db;
  border-radius: 8px;
  font-size: 14px;
  background: #fff;
}
.progress-wrap {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-top: 20px;
}
.time {
  font-size: 12px;
  color: #6b7280;
  font-variant-numeric: tabular-nums;
  min-width: 34px;
}
.progress-track {
  flex: 1;
  height: 8px;
  background: #e5e7eb;
  border-radius: 999px;
  overflow: hidden;
  pointer-events: none; /* 只读：不可拖动 */
}
.progress-fill {
  height: 100%;
  background: #3b82f6;
  border-radius: 999px;
  transition: width 0.2s linear;
}
.quiz-entry {
  margin-top: 18px;
}
.warn-box {
  margin-top: 16px;
  background: #fff7ed;
  border: 1px solid #fed7aa;
  color: #c2410c;
  font-size: 13px;
  border-radius: 10px;
  padding: 10px 14px;
}
.error-text {
  color: #dc2626;
  font-size: 14px;
  background: #fef2f2;
  border: 1px solid #fecaca;
  border-radius: 10px;
  padding: 10px 14px;
}
</style>
