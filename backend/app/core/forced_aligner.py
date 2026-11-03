"""wav2vec2 CTC 强制对齐（forced alignment）：官方文稿直接钉到音频上。

转写时代的替代方案：官方文稿本来就是正确文本，无需"听写"。
``Wav2Vec2ForCTC``（CPU）产出 CTC emission，``torchaudio.functional.forced_align``
把文稿字符序列对齐到音频帧，字符帧区间按词聚合，得到**官方原词**粒度的 start/end。

输出契约与转写时代一致：``{"words": [{"w", "start", "end"}], "durationSec"}``；
words 为文稿按空格切分的原始词（大小写/标点保留），无对应字符的词 start/end 为 None。

取消/失败语义沿用：分段循环间检查 ``should_cancel``（取消抛 ``JobCancelled``）；
一切对齐失败统一抛 ``TranscribeError``（导入管线按 FR-012 降级为"仅音频模式"）。

国内网络直连 HuggingFace 会超时：未显式配置时默认走 hf-mirror 镜像并禁用 Xet。

质量守卫（防错配文稿产出垃圾对齐）：
- 音频帧数装不下文稿字符数 → ``TranscribeError``；
- 对齐路径平均后验概率 < ``MIN_AVG_POSTERIOR`` 或模型首选命中率 < ``MIN_ARGMAX_HIT``
  → ``TranscribeError``（降级仅音频模式）。
"""

import logging
import os
import unicodedata
from typing import Callable, Optional

os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")
os.environ.setdefault("HF_HUB_DISABLE_XET", "1")

logger = logging.getLogger(__name__)


class TranscribeError(Exception):
    """对齐失败（模型/音频错误、文稿与音频不匹配、音频不可读等）。"""


class JobCancelled(Exception):
    """对齐被用户取消。"""


MODEL_IDS = {
    "base": "facebook/wav2vec2-base-960h",
    "large": "facebook/wav2vec2-large-960h-lv60-self",
}

SAMPLE_RATE = 16_000
CHUNK_SEC = 30.0
# CTC 帧率：16kHz / 卷积总步长 320
FRAMES_PER_SEC = 50
# 质量守卫阈值（实测 base 模型：正确文稿 ≈0.94 / 同长度错误文稿 ≈0.42）：
# 对齐路径非 blank 帧的平均后验概率下限
MIN_AVG_POSTERIOR = 0.5
# 同上路径中"放置字符 = 该帧模型首选字符"的最低占比
MIN_ARGMAX_HIT = 0.5

# 逐字符数字展开（"6" → "SIX"），使数字词也能钉上时间
_DIGIT_WORDS = {
    "0": "ZERO", "1": "ONE", "2": "TWO", "3": "THREE", "4": "FOUR",
    "5": "FIVE", "6": "SIX", "7": "SEVEN", "8": "EIGHT", "9": "NINE",
}


def probe_duration_sec(audio_path: str) -> float:
    """用 av 探测音频时长（秒）；失败抛 TranscribeError。"""
    try:
        import av

        with av.open(str(audio_path)) as container:
            if container.duration and container.duration > 0:
                return float(container.duration) / 1_000_000
            duration = 0.0
            for stream in container.streams:
                if stream.duration and stream.time_base:
                    duration = max(duration, float(stream.duration * stream.time_base))
            if duration > 0:
                return duration
    except Exception as exc:  # noqa: BLE001 - 统一归为对齐前置失败
        raise TranscribeError(f"无法读取音频文件: {audio_path}: {exc}") from exc
    raise TranscribeError(f"无法探测音频时长: {audio_path}")


def load_audio_mono16k(audio_path: str):
    """av 解码为 16kHz 单声道 float32 一维数组；无声音轨/解码失败抛 TranscribeError。"""
    try:
        import av
        import numpy as np

        container = av.open(str(audio_path))
        resampler = av.AudioResampler(format="flt", layout="mono", rate=SAMPLE_RATE)
        chunks: list = []
        for frame in container.decode(audio=0):
            for rf in resampler.resample(frame):
                chunks.append(rf.to_ndarray().reshape(-1))
        for rf in resampler.resample(None):
            chunks.append(rf.to_ndarray().reshape(-1))
        container.close()
        if not chunks:
            raise TranscribeError(f"音频无声音轨: {audio_path}")
        waveform = np.concatenate(chunks).astype(np.float32)
    except TranscribeError:
        raise
    except Exception as exc:  # noqa: BLE001 - 解码失败统一归为对齐前置失败
        raise TranscribeError(f"音频解码失败: {audio_path}: {exc}") from exc
    if waveform.size == 0:
        raise TranscribeError(f"音频无声音轨: {audio_path}")
    return waveform


def build_targets(text: str, tokenizer) -> tuple[list[int], list[int]]:
    """官方文稿 → CTC 目标序列。

    归一化：NFKC + 大写；按空格分词，词间插 ``|``（词间停顿归入前一词末尾，
    词结束时间 ≈ 下一词开始）；词内保留词表支持的字符，标点丢弃，
    数字逐字符展开为英文数词。返回 ``(target_ids, word_of_target)``：
    ``word_of_target[i]`` 是第 i 个目标字符属于原始文本第几个词
    （空格切分下标），用于把字符帧区间聚合回原始词。
    """
    vocab = tokenizer.get_vocab()
    separator = vocab.get("|")
    target_ids: list[int] = []
    word_of_target: list[int] = []
    for word_idx, token in enumerate((text or "").split()):
        if word_idx > 0 and separator is not None:
            target_ids.append(separator)
            word_of_target.append(word_idx - 1)
        for ch in unicodedata.normalize("NFKC", token).upper():
            chars = _DIGIT_WORDS.get(ch, ch)
            for c in chars:
                tid = vocab.get(c)
                if tid is None:
                    continue
                target_ids.append(tid)
                word_of_target.append(word_idx)
    return target_ids, word_of_target


def spans_from_path(path: list[int], n_targets: int) -> list[Optional[tuple[int, int]]]:
    """逐帧对齐路径（0=blank，k>0=目标位置 k-1）→ 每个目标字符的帧区间 [start, end)。"""
    spans: list[Optional[list[int]]] = [None] * n_targets
    for frame, value in enumerate(path):
        if value <= 0:
            continue
        pos = value - 1
        if pos >= n_targets:
            continue
        span = spans[pos]
        if span is None:
            spans[pos] = [frame, frame + 1]
        else:
            span[1] = frame + 1
    return [tuple(s) if s is not None else None for s in spans]


def words_from_spans(
    text: str, spans: list[Optional[tuple[int, int]]], word_of_target: list[int]
) -> list[dict]:
    """字符帧区间按词聚合 → 官方原词时间戳（秒）；无字符的词 start/end 为 None。"""
    tokens = (text or "").split()
    by_word: list[list[tuple[int, int]]] = [[] for _ in tokens]
    for span, word_idx in zip(spans, word_of_target):
        if span is not None and 0 <= word_idx < len(by_word):
            by_word[word_idx].append(span)
    words: list[dict] = []
    for token, spans_of_word in zip(tokens, by_word):
        if spans_of_word:
            start = min(s[0] for s in spans_of_word) / FRAMES_PER_SEC
            end = max(s[1] for s in spans_of_word) / FRAMES_PER_SEC
            words.append({"w": token, "start": round(start, 3), "end": round(end, 3)})
        else:
            words.append({"w": token, "start": None, "end": None})
    return words


def group_words_to_sentences(sentences: list, words: list[dict]) -> None:
    """把整段对齐词序列按各句词数顺序写回 Sentence（句内词数按空格切分）。

    对齐词数与文稿词数不一致时容错：多了截断，少了补 None 词，绝不抛错。
    """
    pos = 0
    for sentence in sentences:
        count = len(sentence.text.split())
        chunk = words[pos : pos + count]
        pos += count
        if len(chunk) < count:
            # 对齐词数不足：补占位词，保持词数与官方句子一致（None 时间戳 = 不可点击/不高亮）
            rest = sentence.text.split()[len(chunk) :]
            chunk = chunk + [{"w": w, "start": None, "end": None} for w in rest]
        sentence.words = [w if isinstance(w, Word) else Word(**w) for w in chunk]
        mapped = [w for w in sentence.words if w.start is not None]
        if mapped:
            sentence.aligned = True
            sentence.startSec = min(w.start for w in mapped)
            sentence.endSec = max(w.end for w in mapped)
        else:
            sentence.aligned = False
            sentence.startSec = None
            sentence.endSec = None


def _path_stats(emission, path: list[int], targets: list[int]) -> tuple[float, float]:
    """对齐路径质量：(非 blank 帧平均后验概率, 放置字符命中模型首选的比例)。

    只统计"被声称发出文稿字符"的非 blank 帧——blank 帧在高/低匹配下概率都高，
    纳入会稀释判别力；非 blank 帧概率低才说明文稿与音频不匹配
    （模型在那些帧实际听到了别的字符）。
    """
    import torch

    row = emission[0]
    probs = row.exp()
    argmax = row.argmax(dim=-1)
    total = 0.0
    hits = 0
    count = 0
    for frame, value in enumerate(path):
        if value <= 0:
            continue
        tid = targets[value - 1]
        total += float(probs[frame, tid])
        if int(argmax[frame]) == tid:
            hits += 1
        count += 1
    count = max(1, count)
    return total / count, hits / count


class ForcedAligner:
    """wav2vec2 CTC 强制对齐器（懒加载，按模型尺寸缓存）。"""

    def __init__(self, model_size: str = "base", device: str = "cpu"):
        if model_size not in MODEL_IDS:
            raise ValueError(f"model_size must be one of {sorted(MODEL_IDS)}")
        self.model_size = model_size
        self.device = device
        self._processor = None
        self._model = None

    def _load(self) -> None:
        if self._model is not None:
            return
        try:
            from transformers import Wav2Vec2ForCTC, Wav2Vec2Processor
        except ImportError as exc:
            raise TranscribeError("transformers 未安装，无法执行强制对齐") from exc
        repo = MODEL_IDS[self.model_size]
        try:
            self._processor = Wav2Vec2Processor.from_pretrained(repo)
            self._model = Wav2Vec2ForCTC.from_pretrained(repo).to(self.device).eval()
        except Exception as exc:  # noqa: BLE001 - 模型加载失败（含下载失败）统一归类
            raise TranscribeError(f"对齐模型加载失败（{repo}）: {exc}") from exc

    # -- 对外主流程 --

    def align(
        self,
        audio_path: str,
        text: str,
        should_cancel: Optional[Callable[[], bool]] = None,
        on_progress: Optional[Callable[[float], None]] = None,
    ) -> dict:
        duration_sec = probe_duration_sec(audio_path)
        waveform = load_audio_mono16k(audio_path)
        self._load()
        targets, word_of_target = build_targets(text, self._processor.tokenizer)
        if not targets:
            raise TranscribeError("文稿中没有可对齐的英文字符，请检查文稿内容")

        emission = self._emissions(waveform, should_cancel, on_progress)
        n_frames = emission.shape[1]
        if n_frames < len(targets):
            raise TranscribeError(
                "文稿长度超出音频可承载范围，请确认文稿与该音频匹配"
            )

        path, _blank = self._forced_align_path(emission, targets)
        avg, hit = _path_stats(emission, path, targets)
        if avg < MIN_AVG_POSTERIOR or hit < MIN_ARGMAX_HIT:
            raise TranscribeError(
                f"文稿与音频不匹配（对齐置信度 {avg:.2f}/{hit:.2f} 过低），"
                "请确认文稿对应该音频"
            )
        spans = spans_from_path(path, len(targets))
        words = words_from_spans(text, spans, word_of_target)
        return {"words": words, "durationSec": duration_sec}

    # -- 内部步骤 --

    def _emissions(self, waveform, should_cancel, on_progress):
        """分段前向，拼接整段 log_softmax emission [1, T, C]。"""
        import torch

        chunk_len = int(CHUNK_SEC * SAMPLE_RATE)
        chunks = [
            waveform[i : i + chunk_len]
            for i in range(0, len(waveform), chunk_len)
        ]
        outputs: list = []
        with torch.no_grad():
            for idx, chunk in enumerate(chunks):
                if should_cancel is not None and should_cancel():
                    raise JobCancelled()
                inputs = self._processor(
                    chunk,
                    sampling_rate=SAMPLE_RATE,
                    return_tensors="pt",
                )
                input_values = inputs.input_values.to(self.device)
                logits = self._model(input_values).logits
                outputs.append(torch.log_softmax(logits, dim=-1).cpu())
                if on_progress is not None:
                    on_progress((idx + 1) / len(chunks))
        return torch.cat(outputs, dim=1)

    def _forced_align_path(self, emission, targets: list[int]) -> tuple[list[int], int]:
        """torchaudio CTC 强制对齐 → (逐帧路径, blank id)。版本适配集中在此。"""
        import torch

        blank = int(self._processor.tokenizer.pad_token_id or 0)
        tgt = torch.tensor([targets], dtype=torch.int32)
        try:
            import torchaudio

            alignments, _scores = torchaudio.functional.forced_align(
                emission, tgt, blank=blank
            )
        except (ImportError, AttributeError, RuntimeError) as exc:
            raise TranscribeError(f"强制对齐执行失败: {exc}") from exc
        # 返回的是逐帧 token id（0=blank）；按序消耗目标序列转成位置编号
        # （0=blank，k>0=目标位置 k-1），连续重复目标也能正确区分次序
        return _token_ids_to_positions(alignments[0].tolist(), targets), blank


def _token_ids_to_positions(path: list[int], targets: list[int]) -> list[int]:
    """逐帧 token id → 目标位置编号：非 blank 帧按序匹配目标。

    CTC 中连续重复的目标必须由 blank 分隔（如 "LL" = L blank L）：
    出现 blank 后当前目标闭合，下一个同值帧推进到下一目标位置。
    """
    out: list[int] = []
    pos = 0
    closed = False
    n = len(targets)
    for value in path:
        if value <= 0:
            closed = True
            out.append(0)
            continue
        if pos < n and value == targets[pos]:
            if closed and pos + 1 < n and value == targets[pos + 1]:
                pos += 1
            closed = False
            out.append(pos + 1)
        elif pos + 1 < n and value == targets[pos + 1]:
            pos += 1
            closed = False
            out.append(pos + 1)
        else:
            out.append(0)
    return out


from ..models import Word  # noqa: E402  (底部导入避免循环依赖)

_ALIGNERS: dict[str, ForcedAligner] = {}


def get_aligner(model_size: str = "base") -> ForcedAligner:
    """按尺寸取缓存的 ForcedAligner（合约测试可 monkeypatch 整个 align）。"""
    aligner = _ALIGNERS.get(model_size)
    if aligner is None:
        aligner = ForcedAligner(model_size)
        _ALIGNERS[model_size] = aligner
    return aligner


def align(
    audio_path: str,
    text: str,
    model_size: str = "base",
    should_cancel: Optional[Callable[[], bool]] = None,
    on_progress: Optional[Callable[[float], None]] = None,
) -> dict:
    """便捷入口：``{"words": [{"w", "start", "end"}], "durationSec"}``。"""
    return get_aligner(model_size).align(
        audio_path, text, should_cancel=should_cancel, on_progress=on_progress
    )
