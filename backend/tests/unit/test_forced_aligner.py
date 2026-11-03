"""wav2vec2 强制对齐纯函数/流程单测（不下载真实模型，torchaudio 为真实调用）。

覆盖：build_targets 归一化与词映射、token id→位置编号（含重复与 blank）、
字符帧区间聚合、词-句分组容错、质量守卫、音频装不下文稿的报错；
另有一条合成 emission 走真实 torchaudio forced_align 的端到端对齐（无模型）。
"""

from types import SimpleNamespace

import pytest

from backend.app.core import forced_aligner
from backend.app.core.forced_aligner import (
    JobCancelled,
    TranscribeError,
    _token_ids_to_positions,
    build_targets,
    group_words_to_sentences,
    spans_from_path,
    words_from_spans,
)
from backend.app.models import Sentence


class FakeTokenizer:
    """模拟 wav2vec2 960h 词表：| A-Z '，<pad>=0 为 blank。"""

    pad_token_id = 0

    def get_vocab(self):
        vocab = {"<pad>": 0, "<s>": 1, "</s>": 2, "<unk>": 3, "|": 4}
        for i, ch in enumerate("ABCDEFGHIJKLMNOPQRSTUVWXYZ"):
            vocab[ch] = 5 + i
        vocab["'"] = 5 + 26
        return vocab


FAKE_VOCAB = FakeTokenizer().get_vocab()


# ---------- build_targets ----------


def test_build_targets_maps_chars_to_original_words():
    targets, word_of = build_targets("Hello world.", FakeTokenizer())
    # "HELLO" → 5 字符，"|" 分隔，"WORLD" → 5 字符（句号丢弃）
    assert len(targets) == 11
    assert [FAKE_VOCAB[c] for c in "HELLO|WORLD"] == targets
    assert word_of[:5] == [0] * 5
    assert word_of[5] == 0  # 词间停顿归入前一词
    assert word_of[6:] == [1] * 5


def test_build_targets_normalizes_case_digits_and_punctuation():
    targets, word_of = build_targets("It's 6 ok!", FakeTokenizer())
    # "IT'S" (4) + | + "SIX"(3) + | + "OK"(2)；感叹号丢弃
    ids = [FAKE_VOCAB[c] for c in "IT'S|SIX|OK"]
    assert targets == ids
    # 词间停顿归入前一词：IT'S×4 + 停顿×1 → 词0 共 5 个位置
    assert word_of == [0, 0, 0, 0, 0, 1, 1, 1, 1, 2, 2]


def test_build_targets_drops_unsupported_chars():
    targets, _ = build_targets("héllo", FakeTokenizer())
    # é 不在词表 → 丢弃，"HLLO" 保留
    assert [FAKE_VOCAB[c] for c in "HLLO"] == targets


# ---------- _token_ids_to_positions ----------


def test_token_ids_to_positions_consumes_in_order():
    targets = [7, 7, 9]  # 例如 "LL" 连续重复
    # token id 序列：7 占 2 帧，7 再次出现（需 blank 分隔但对齐输出仍按序），9 占 1 帧
    path = [7, 7, 0, 7, 9]
    assert _token_ids_to_positions(path, targets) == [1, 1, 0, 2, 3]


def test_token_ids_to_positions_treats_unknown_as_blank():
    targets = [5, 6]
    assert _token_ids_to_positions([5, 9, 6], targets) == [1, 0, 2]


# ---------- spans_from_path / words_from_spans ----------


def test_spans_from_path_groups_contiguous_runs():
    # 目标 3 个：位置 0 占帧 0-1，位置 1 占帧 2-4，位置 2 占帧 5
    path = [1, 1, 2, 2, 2, 3]
    assert spans_from_path(path, 3) == [(0, 2), (2, 5), (5, 6)]


def test_spans_from_path_ignores_blanks_and_overflow():
    path = [0, 1, 0, 2, 9]
    assert spans_from_path(path, 2) == [(1, 2), (3, 4)]


def test_words_from_spans_aggregates_char_spans():
    text = "Hello world."
    # 词 0：帧 0-10；词间停顿（归入词 0）：帧 10-11；词 1：帧 11-21
    spans = [(0, 4), (4, 7), (7, 10), (10, 11), (11, 15), (15, 18), (18, 21)]
    word_of = [0, 0, 0, 0, 1, 1, 1]  # "WORLD" 只贡献了 3 个字符区间（示意）
    words = words_from_spans(text, spans, word_of)
    assert words[0] == {"w": "Hello", "start": 0.0, "end": 0.22}
    assert words[1] == {"w": "world.", "start": 0.22, "end": 0.42}


def test_words_from_spans_marks_punctuation_only_words_unaligned():
    text = "wow … really"
    # 第二个词 "…" 不产生任何目标字符
    spans = [(0, 5), (5, 6), (6, 10)]
    word_of = [0, 0, 2]
    words = words_from_spans(text, spans, word_of)
    assert words[1] == {"w": "…", "start": None, "end": None}
    assert words[2]["start"] == 0.12


# ---------- group_words_to_sentences ----------


def _sentence(text: str) -> Sentence:
    return Sentence(materialId="m", turnId="t", blockId="b", index=0, text=text, aligned=False)


def test_group_words_to_sentences_assigns_by_word_count():
    sents = [_sentence("Hello world."), _sentence("Bye now.")]
    words = [
        {"w": "Hello", "start": 0.0, "end": 0.5},
        {"w": "world.", "start": 0.5, "end": 1.0},
        {"w": "Bye", "start": 2.0, "end": 2.5},
        {"w": "now.", "start": None, "end": None},
    ]
    group_words_to_sentences(sents, words)
    assert [w.w for w in sents[0].words] == ["Hello", "world."]
    assert sents[0].aligned is True
    assert sents[0].startSec == 0.0
    assert sents[0].endSec == 1.0
    assert sents[1].aligned is True  # 任一词带时间戳即对齐
    assert sents[1].startSec == 2.0
    assert sents[1].endSec == 2.5
    assert sents[1].words[1].start is None


def test_group_words_to_sentences_tolerates_count_mismatch():
    sents = [_sentence("Hello brave world.")]
    group_words_to_sentences(sents, [{"w": "Hello", "start": 0.0, "end": 0.5}])
    assert [w.w for w in sents[0].words] == ["Hello", "brave", "world."]
    assert sents[0].aligned is True
    assert sents[0].words[1].start is None  # 补齐的词无时间戳

    # 词序列过长：按句内词数顺序消费，多余词截断丢弃，不越界
    sents2 = [_sentence("Hi."), _sentence("Yo.")]
    words = [
        {"w": "Hi.", "start": 0.0, "end": 0.2},
        {"w": "Yo.", "start": 0.6, "end": 0.8},
        {"w": "stray", "start": 9.0, "end": 9.9},
    ]
    group_words_to_sentences(sents2, words)
    assert [w.w for w in sents2[0].words] == ["Hi."]
    assert [w.w for w in sents2[1].words] == ["Yo."]
    assert sents2[1].startSec == 0.6  # stray 被丢弃，不影响已分配句子


def test_group_words_to_sentences_all_none_marks_unaligned():
    sents = [_sentence("Hello world.")]
    group_words_to_sentences(sents, [{"w": "Hello", "start": None, "end": None}])
    assert sents[0].aligned is False
    assert sents[0].startSec is None


# ---------- 端到端（合成 emission + 真实 torchaudio forced_align，无模型下载） ----------


def _peaked_emission(target_ids, frames_per_target=8, n_blank=2):
    """构造对齐目标极易命中的 emission：[1, T, C] log_softmax。"""
    import torch

    vocab_size = max(FAKE_VOCAB.values()) + 1
    path: list[int] = []
    for pos, _tid in enumerate(target_ids):
        path.extend([pos + 1] * frames_per_target)
        path.extend([0] * n_blank)
    n_frames = len(path)
    logits = torch.zeros(1, n_frames, vocab_size)
    for frame, pos in enumerate(path):
        tid = 0 if pos == 0 else target_ids[pos - 1]
        logits[0, frame, tid] = 10.0
    return torch.log_softmax(logits, dim=-1), path


def _fake_aligner() -> forced_aligner.ForcedAligner:
    aligner = forced_aligner.ForcedAligner("base")
    aligner._processor = SimpleNamespace(tokenizer=FakeTokenizer())
    return aligner


def test_align_end_to_end_with_synthetic_emission(monkeypatch):
    """probe/解码/模型加载全部打桩，emission 合成：走真实 forced_align 产出词时间戳。"""
    import numpy as np

    text = "Hi all"
    targets, _word_of = build_targets(text, FakeTokenizer())
    emission, _path = _peaked_emission(targets, frames_per_target=8)

    monkeypatch.setattr(forced_aligner, "probe_duration_sec", lambda p: 3.0)
    monkeypatch.setattr(
        forced_aligner, "load_audio_mono16k", lambda p: np.zeros(16000, dtype=np.float32)
    )
    aligner = _fake_aligner()
    monkeypatch.setattr(aligner, "_load", lambda: None)
    monkeypatch.setattr(aligner, "_emissions", lambda *a, **k: emission)

    result = aligner.align("fake.wav", text)
    assert result["durationSec"] == 3.0
    words = result["words"]
    assert [w["w"] for w in words] == ["Hi", "all"]
    assert words[0]["start"] == 0.0
    # 每目标 8 帧 + 2 blank：词 0 含 H、I 及词间停顿 ≈ (8+8+8+6)/50 ≈ 0.6s，
    # forced_align 可能在边界补 blank，放宽容差；词 1 紧接词 0 结束。
    assert words[0]["end"] == pytest.approx(0.56, abs=0.08)
    # 词间通常有 blank 间隙：下一词开始 ≥ 前词结束，且不会远于一个 blank 窗
    assert words[1]["start"] >= words[0]["end"] - 1e-9
    assert words[1]["start"] == pytest.approx(words[0]["end"] + 0.04, abs=0.08)
    assert words[1]["end"] == pytest.approx(words[0]["end"] + 26 / 50, abs=0.1)


def test_align_rejects_text_longer_than_audio(monkeypatch):
    import numpy as np

    text = "Hello world this is a very long transcript"
    monkeypatch.setattr(forced_aligner, "probe_duration_sec", lambda p: 3.0)
    monkeypatch.setattr(
        forced_aligner, "load_audio_mono16k", lambda p: np.zeros(16000, dtype=np.float32)
    )
    aligner = _fake_aligner()
    monkeypatch.setattr(aligner, "_load", lambda: None)
    # 只有 5 帧，装不下 40+ 字符
    import torch

    monkeypatch.setattr(
        aligner, "_emissions", lambda *a, **k: torch.log_softmax(torch.zeros(1, 5, 40), dim=-1)
    )
    with pytest.raises(TranscribeError, match="超出音频可承载范围"):
        aligner.align("fake.wav", text)


def test_align_rejects_mismatched_transcript(monkeypatch):
    """emission 与文稿无关（均匀分布）→ 平均后验过低 → 对齐失败。"""
    import numpy as np
    import torch

    text = "Hello there friend"
    monkeypatch.setattr(forced_aligner, "probe_duration_sec", lambda p: 3.0)
    monkeypatch.setattr(
        forced_aligner, "load_audio_mono16k", lambda p: np.zeros(16000, dtype=np.float32)
    )
    aligner = _fake_aligner()
    monkeypatch.setattr(aligner, "_load", lambda: None)
    monkeypatch.setattr(
        aligner,
        "_emissions",
        lambda *a, **k: torch.log_softmax(torch.zeros(1, 200, 40), dim=-1),
    )
    with pytest.raises(TranscribeError, match="不匹配"):
        aligner.align("fake.wav", text)


def test_align_propagates_cancel(monkeypatch):
    import numpy as np

    monkeypatch.setattr(forced_aligner, "probe_duration_sec", lambda p: 3.0)
    monkeypatch.setattr(
        forced_aligner, "load_audio_mono16k", lambda p: np.zeros(16000, dtype=np.float32)
    )
    aligner = _fake_aligner()
    monkeypatch.setattr(aligner, "_load", lambda: None)

    def _boom(*a, **k):
        raise JobCancelled()

    monkeypatch.setattr(aligner, "_emissions", _boom)
    with pytest.raises(JobCancelled):
        aligner.align("fake.wav", "Hi", should_cancel=lambda: True)
