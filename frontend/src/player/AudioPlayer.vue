<template>
  <audio
    ref="el"
    :src="src"
    preload="auto"
    style="display: none"
    @timeupdate="onTimeUpdate"
    @play="emit('playstate', true)"
    @pause="emit('playstate', false)"
    @ended="onEnded"
    @loadedmetadata="onLoadedMetadata"
  ></audio>
</template>

<script setup>
import { ref, watch } from 'vue'

const props = defineProps({
  src: { type: String, required: true },
  // 当前句的逐词时间戳 [{ w, start, end }]，用于逐词高亮（卡拉OK）二分定位
  words: { type: Array, default: () => [] },
})
const emit = defineEmits(['word', 'ended', 'timeupdate', 'playstate', 'loadedmetadata'])

const el = ref(null)
const loopSpan = ref(null) // 单句循环区间 { start, end }
let lastWordIndex = -1

watch(
  () => props.src,
  () => {
    loopSpan.value = null
    lastWordIndex = -1
  }
)

watch(
  () => props.words,
  () => {
    if (lastWordIndex !== -1) {
      lastWordIndex = -1
      emit('word', { index: -1, word: null })
    }
  }
)

function seek(sec) {
  const a = el.value
  if (a && Number.isFinite(sec)) a.currentTime = Math.max(0, sec)
}

function play() {
  el.value?.play()?.catch(() => {})
}

function pause() {
  el.value?.pause()
}

// 跳转到 sec 并播放（单词/句子点击跳转用）
function playAt(sec) {
  seek(sec)
  play()
}

// 设定单句循环区间 [start, end] 并从 start 播放；传 null 清除
function playSpan(start, end) {
  if (start == null || end == null || !(end > start)) {
    loopSpan.value = null
    playAt(start)
    return
  }
  loopSpan.value = { start, end }
  playAt(start)
}

function stopSpan() {
  loopSpan.value = null
}

function setRate(x) {
  const a = el.value
  if (a) a.playbackRate = x
}

function getCurrentTime() {
  return el.value?.currentTime ?? 0
}

function onTimeUpdate() {
  const a = el.value
  if (!a) return
  let t = a.currentTime
  const span = loopSpan.value
  if (span && t >= span.end) {
    a.currentTime = span.start
    t = span.start
  }
  emit('timeupdate', t)
  const words = props.words
  if (!words.length) return
  // 二分：最后一个 start <= t 的词；t 早于首词开始时间时为 -1
  let lo = 0
  let hi = words.length - 1
  let idx = -1
  while (lo <= hi) {
    const mid = (lo + hi) >> 1
    const ws = words[mid].start
    if (ws != null && ws <= t) {
      idx = mid
      lo = mid + 1
    } else {
      hi = mid - 1
    }
  }
  if (idx !== lastWordIndex) {
    lastWordIndex = idx
    emit('word', { index: idx, word: idx >= 0 ? words[idx].w : null })
  }
}

function onEnded() {
  const span = loopSpan.value
  const a = el.value
  if (span && a) {
    // 音频自然结束但循环区间仍有效（句尾即音频结尾）：回到区间起点继续循环
    a.currentTime = span.start
    play()
    return
  }
  emit('ended')
}

function onLoadedMetadata() {
  emit('loadedmetadata', el.value?.duration ?? 0)
}

defineExpose({ play, pause, playAt, playSpan, stopSpan, setRate, seek, getCurrentTime })
</script>
