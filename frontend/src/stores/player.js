import { defineStore } from 'pinia'

// 学习/复习等视图间共享的播放器状态
export const usePlayerStore = defineStore('player', {
  state: () => ({
    playing: false,
    currentSentenceId: null, // 当前播放到的句子 id
    currentWord: null, // 逐词高亮 { sentenceId, index }，无高亮为 null
    follow: true, // 文稿自动滚动跟随
    rate: 1, // 播放速度 0.5 / 0.75 / 1 / 1.25 / 1.5
    loopSentence: false, // 单句循环开关
    currentTime: 0,
    duration: 0,
  }),
  actions: {
    setPlaying(v) {
      this.playing = v
    },
    setCurrentSentence(id) {
      this.currentSentenceId = id
    },
    setCurrentWord(w) {
      this.currentWord = w
    },
    setFollow(v) {
      this.follow = v
    },
    setRate(r) {
      this.rate = r
    },
    setLoopSentence(v) {
      this.loopSentence = v
    },
    setCurrentTime(t) {
      this.currentTime = t
    },
    setDuration(d) {
      this.duration = d
    },
    reset() {
      this.playing = false
      this.currentSentenceId = null
      this.currentWord = null
      this.follow = true
      this.rate = 1
      this.loopSentence = false
      this.currentTime = 0
      this.duration = 0
    },
  },
})
