import re
from datetime import date, datetime
from typing import Literal, Optional
from uuid import uuid4

from pydantic import BaseModel, Field, field_validator


def new_id() -> str:
    return uuid4().hex


def now_iso() -> str:
    return datetime.now().isoformat()


Stage = Literal["learning", "reviewing", "mastered"]
ReviewType = Literal["word", "phrase", "sentence"]
ShadowingSource = Literal["manual", "llm"]
ShadowingStatus = Literal["active", "ignored", "removed"]
QuizStatus = Literal["in_progress", "completed"]
AlignModel = Literal["base", "large"]
LlmProvider = Literal["openai", "deepseek", "kimi"]
DefaultSpeed = Literal[0.5, 0.75, 1.0, 1.25, 1.5]
AUDIO_EXTS = {"mp3", "wav", "m4a", "flac", "ogg"}
INTERVALS = (1, 3, 7, 15, 30)


class Material(BaseModel):
    id: str = Field(default_factory=new_id)
    title: str = Field(min_length=1, max_length=200)
    audioFileName: str
    durationSec: float = Field(gt=0)
    stage: Stage = "learning"
    audioOnly: bool = False
    # 对齐状态：旧材料可能为 refining/refined（转写时代 LLM 精修），新导入恒为 baseline
    alignment: str = "baseline"
    # LLM 检测选题缓存（主旨覆盖；再测复用，生词/没听懂句经规则补缺）
    quizFocusIds: list[str] = []
    bestScore: Optional[float] = Field(default=None, ge=0, le=100)
    # 对齐引擎标识（wav2vec2）；旧材料可能保留 faster-whisper/paraformer 值
    engineUsed: Optional[str] = None
    playheadSec: float = 0.0
    createdAt: str = Field(default_factory=now_iso)
    updatedAt: str = Field(default_factory=now_iso)

    @field_validator("audioFileName")
    @classmethod
    def _audio_ext(cls, v: str) -> str:
        ext = v.rsplit(".", 1)[-1].lower() if "." in v else ""
        if ext not in AUDIO_EXTS:
            raise ValueError(f"audioFileName ext must be one of {sorted(AUDIO_EXTS)}")
        return v


class Turn(BaseModel):
    id: str = Field(default_factory=new_id)
    materialId: str
    index: int = Field(ge=0)
    speakerName: Optional[str] = None
    speakerNameZh: Optional[str] = None


class Block(BaseModel):
    id: str = Field(default_factory=new_id)
    turnId: str
    index: int = Field(ge=0)
    translationLines: list[str] = Field(default_factory=list)


class Word(BaseModel):
    w: str
    # AI 对齐后官方词粒度：未映射到转写词时为 None（不可点击/不高亮）
    start: Optional[float] = Field(default=None, ge=0)
    end: Optional[float] = Field(default=None, ge=0)


class Sentence(BaseModel):
    id: str = Field(default_factory=new_id)
    materialId: str
    turnId: str
    blockId: str
    index: int = Field(ge=0)
    text: str
    aligned: bool
    startSec: Optional[float] = Field(default=None, ge=0)
    endSec: Optional[float] = Field(default=None, ge=0)
    words: list[Word] = Field(default_factory=list)
    notUnderstood: bool = False


class ReviewItem(BaseModel):
    id: str = Field(default_factory=new_id)
    type: ReviewType
    text: str
    meaning: Optional[str] = None
    materialId: str
    sentenceId: str
    contextText: str
    knownCount: int = Field(default=0, ge=0)
    reviewCount: int = Field(default=0, ge=0)
    intervalDays: int = 1
    dueAt: date
    lastReviewAt: Optional[str] = None
    createdAt: str = Field(default_factory=now_iso)

    @field_validator("intervalDays")
    @classmethod
    def _interval(cls, v: int) -> int:
        if v not in INTERVALS:
            raise ValueError(f"intervalDays must be one of {list(INTERVALS)}")
        return v


class Anchor(BaseModel):
    sentenceId: str
    wordIndex: int = Field(ge=0)


class ShadowingItem(BaseModel):
    id: str = Field(default_factory=new_id)
    materialId: str
    text: str
    anchorStart: Anchor
    anchorEnd: Anchor
    audioStartSec: float = Field(ge=0)
    audioEndSec: float = Field(ge=0)
    source: ShadowingSource = "manual"
    status: ShadowingStatus = "active"


class QuizItem(BaseModel):
    sentenceId: str
    userInput: Optional[str] = None
    correct: Optional[bool] = None


class Quiz(BaseModel):
    id: str = Field(default_factory=new_id)
    materialId: str
    status: QuizStatus = "in_progress"
    createdAt: str = Field(default_factory=now_iso)
    completedAt: Optional[str] = None
    items: list[QuizItem] = Field(default_factory=list)
    correctCount: int = 0
    totalCount: int = 0
    score: float = Field(default=0.0, ge=0, le=100)


class LlmSettings(BaseModel):
    provider: LlmProvider = "openai"
    apiKey: str = ""
    model: str = ""
    enabled: bool = False
    # 思考模式（仅 Kimi 服务商生效；K2 思考型模型关闭后速度接近 turbo）
    thinking: bool = False


class Settings(BaseModel):
    alignModel: AlignModel = "base"
    llm: LlmSettings = Field(default_factory=LlmSettings)
    defaultSpeed: DefaultSpeed = 1.0
    showTranslationDefault: bool = True


MASK_PATTERN = re.compile(r"^\*+")


def mask_secret(value: Optional[str]) -> Optional[str]:
    if not value:
        return value
    if MASK_PATTERN.match(value):
        return value
    return "****" + value[-4:]
