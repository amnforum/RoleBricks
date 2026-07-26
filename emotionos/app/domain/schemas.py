from __future__ import annotations

import uuid
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator


SpeechLanguage = Literal["auto", "en-IN", "hi-IN", "hinglish-IN"]
SpeechAccent = Literal["indian", "british", "neutral"]
SpeechStyle = Literal["conversational", "story_narrator", "news_reporter"]


class SpeechProfile(BaseModel):
    region: Literal["IN", "GB", "US"] = "IN"
    language: SpeechLanguage = "auto"
    accent: SpeechAccent = "indian"
    style: SpeechStyle = "conversational"


class PerformancePlan(BaseModel):
    primary_emotion: str
    visible_emotion: str
    hidden_emotion: str
    memory_score: float = Field(ge=0, le=1)
    pace: float = Field(ge=0.85, le=1.15)
    pitch_semitones: float = Field(ge=-1.5, le=1.5)
    volume_db: float = Field(ge=-4.0, le=3.0)
    energy: float = Field(ge=0, le=1)
    pause_duration_ms: int = Field(ge=0, le=900)
    pause_before_phrase: str | None = None
    emphasis_words: list[str] = Field(default_factory=list)
    breath_before_final_phrase: bool = False
    performance_note: str
    explanation: str
    relevant_memory_ids: list[uuid.UUID] = Field(default_factory=list)

    @field_validator("primary_emotion", "visible_emotion", "hidden_emotion")
    @classmethod
    def normalize_emotion_labels(cls, value: str) -> str:
        return value.strip().lower().replace(" ", "_")

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "pace": self.pace,
            "pitch_semitones": self.pitch_semitones,
            "volume_db": self.volume_db,
            "energy": self.energy,
            "pause_duration_ms": self.pause_duration_ms,
            "pause_before_phrase": self.pause_before_phrase,
            "emphasis_words": self.emphasis_words,
            "breath_before_final_phrase": self.breath_before_final_phrase,
            "performance_note": self.performance_note,
        }
