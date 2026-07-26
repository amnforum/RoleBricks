from __future__ import annotations

import re
import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator


SceneStatus = Literal[
    "draft",
    "blueprint",
    "confirmed",
    "preparing",
    "ready",
    "live",
    "paused",
    "completed",
]
ScenePressure = Literal["supportive", "realistic", "high_pressure"]
MemoryLayer = Literal["canon", "scene", "episode", "reflection"]
IdentityKind = Literal["original", "fictional", "public_figure", "private_person"]


class SceneSpeechProfile(BaseModel):
    language: str = Field(default="English", min_length=2, max_length=80)
    region: str = Field(default="India", min_length=2, max_length=80)
    accent: str = Field(default="Indian", min_length=2, max_length=80)
    dialect: str = Field(default="", max_length=120)
    code_mixing: str = Field(default="natural", max_length=160)
    pace: str = Field(default="natural", max_length=80)


class SceneVoiceProfile(BaseModel):
    identity_mode: Literal["distinct_synthetic", "authorized_match"] = "distinct_synthetic"
    presentation: Literal["feminine", "masculine", "androgynous"] = "androgynous"
    requested_identity: str = Field(default="", max_length=160)
    performance: str = Field(default="natural and emotionally responsive", max_length=500)
    consent_required: bool = False
    consent_confirmed: bool = False

    @model_validator(mode="after")
    def authorized_matching_requires_consent(self) -> "SceneVoiceProfile":
        if self.identity_mode == "authorized_match":
            self.consent_required = True
        if self.consent_confirmed and not self.consent_required:
            self.consent_confirmed = False
        return self


class SceneUserRole(BaseModel):
    name: str = Field(default="You", min_length=1, max_length=120)
    role: str = Field(min_length=2, max_length=240)
    objective: str = Field(min_length=2, max_length=500)
    starting_context: str = Field(default="", max_length=1000)


class SceneCharacterDraft(BaseModel):
    key: str = Field(min_length=2, max_length=80)
    name: str = Field(min_length=1, max_length=120)
    role: str = Field(min_length=2, max_length=240)
    identity: str = Field(default="", max_length=240)
    identity_kind: IdentityKind = "original"
    portrayal_notice: str = Field(default="", max_length=500)
    summary: str = Field(min_length=2, max_length=1000)
    objective: str = Field(min_length=2, max_length=500)
    public_knowledge: list[str] = Field(default_factory=list, max_length=20)
    private_knowledge: list[str] = Field(default_factory=list, max_length=20)
    goals: list[str] = Field(default_factory=list, max_length=12)
    fears: list[str] = Field(default_factory=list, max_length=12)
    strategies: list[str] = Field(default_factory=list, max_length=12)
    authority: int = Field(default=50, ge=0, le=100)
    patience: int = Field(default=55, ge=0, le=100)
    interruption_tendency: int = Field(default=35, ge=0, le=100)
    selected: bool = True
    selection_reason: str = Field(default="", max_length=500)
    speech: SceneSpeechProfile = Field(default_factory=SceneSpeechProfile)
    voice: SceneVoiceProfile = Field(default_factory=SceneVoiceProfile)

    @field_validator("key")
    @classmethod
    def normalize_key(cls, value: str) -> str:
        normalized = re.sub(r"[^a-z0-9]+", "-", value.strip().lower()).strip("-")
        if len(normalized) < 2:
            raise ValueError("character key must contain at least two letters or numbers")
        return normalized[:80]

    @model_validator(mode="after")
    def protect_public_figure_identity(self) -> "SceneCharacterDraft":
        if self.identity_kind != "public_figure":
            return self
        self.voice.identity_mode = "distinct_synthetic"
        self.voice.requested_identity = ""
        self.voice.consent_required = False
        self.voice.consent_confirmed = False
        self.voice.performance = (
            "Use an original expressive voice for a clearly labelled public-information "
            "simulation. Do not imitate or claim to be the real person."
        )
        if not self.portrayal_notice:
            self.portrayal_notice = (
                "Public-information simulation with a distinct synthetic voice. "
                "Not affiliated with or endorsed by the real person."
            )
        return self


class SceneRelationshipDraft(BaseModel):
    from_key: str = Field(min_length=1, max_length=80)
    to_key: str = Field(min_length=1, max_length=80)
    description: str = Field(min_length=2, max_length=500)
    trust: int = Field(default=50, ge=0, le=100)
    tension: int = Field(default=30, ge=0, le=100)
    respect: int = Field(default=50, ge=0, le=100)


class SceneManifest(BaseModel):
    version: int = Field(default=1, ge=1)
    title: str = Field(min_length=2, max_length=180)
    scenario_summary: str = Field(min_length=10, max_length=2000)
    setting: str = Field(min_length=2, max_length=1000)
    stakes: str = Field(min_length=2, max_length=1000)
    tone: str = Field(min_length=2, max_length=300)
    objective: str = Field(min_length=2, max_length=1000)
    end_conditions: list[str] = Field(default_factory=list, max_length=12)
    user_role: SceneUserRole
    ai_characters: list[SceneCharacterDraft] = Field(min_length=1, max_length=8)
    relationships: list[SceneRelationshipDraft] = Field(default_factory=list, max_length=24)
    pressure: ScenePressure = "realistic"
    interruption_behavior: str = Field(default="phrase_boundary", max_length=240)
    required_fresh_searches: list[str] = Field(default_factory=list, max_length=20)
    clarifying_questions: list[str] = Field(default_factory=list, max_length=5)
    assumptions: list[str] = Field(default_factory=list, max_length=12)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_cast(self) -> "SceneManifest":
        keys = [character.key for character in self.ai_characters]
        if len(keys) != len(set(keys)):
            raise ValueError("AI character keys must be unique")
        if len(self.selected_characters) > 3:
            raise ValueError("A scene can contain at most three selected AI characters")
        return self

    @property
    def selected_characters(self) -> list[SceneCharacterDraft]:
        return [character for character in self.ai_characters if character.selected]


class SceneDraftCreate(BaseModel):
    prompt: str = Field(min_length=20, max_length=5000)
    locale: str = Field(default="en-IN", max_length=40)

    @field_validator("prompt")
    @classmethod
    def normalize_prompt(cls, value: str) -> str:
        return " ".join(value.split())


class SceneBlueprintPatch(BaseModel):
    expected_version: int = Field(ge=1)
    title: str | None = Field(default=None, min_length=2, max_length=180)
    scenario_summary: str | None = Field(default=None, min_length=10, max_length=2000)
    setting: str | None = Field(default=None, min_length=2, max_length=1000)
    stakes: str | None = Field(default=None, min_length=2, max_length=1000)
    objective: str | None = Field(default=None, min_length=2, max_length=1000)
    user_role: SceneUserRole | None = None
    ai_characters: list[SceneCharacterDraft] | None = Field(default=None, min_length=1, max_length=8)
    pressure: ScenePressure | None = None
    change_reason: str = Field(default="Blueprint edited", min_length=2, max_length=240)


class SceneConfirmRequest(BaseModel):
    expected_version: int = Field(ge=1)


class SceneTurnCreate(BaseModel):
    text: str = Field(min_length=1, max_length=4000)

    @field_validator("text")
    @classmethod
    def normalize_text(cls, value: str) -> str:
        return " ".join(value.split())


class CharacterAction(BaseModel):
    character_key: str
    action: Literal[
        "answer",
        "challenge",
        "interrupt",
        "evade",
        "probe",
        "joke",
        "correct",
        "accuse",
        "concede",
        "refuse",
        "redirect",
        "end",
    ]
    spoken_response: str = Field(min_length=1, max_length=4000)
    private_reason: str = Field(default="", max_length=1000)
    mood: str = Field(default="focused", max_length=120)
    relationship_delta: dict[str, int] = Field(default_factory=dict)
    cited_source_ids: list[str] = Field(default_factory=list)


class PreparedCharacter(BaseModel):
    key: str
    persona_summary: str
    stable_facts: list[str] = Field(default_factory=list)
    current_facts: list[str] = Field(default_factory=list)
    mannerisms: list[str] = Field(default_factory=list)
    pronunciation_notes: list[str] = Field(default_factory=list)
    opening_line: str


class PreparedScene(BaseModel):
    characters: list[PreparedCharacter]
    opening_character_key: str
    opening_action: str = "probe"
    evidence_summary: list[str] = Field(default_factory=list)



class SceneManifestVersionRead(BaseModel):
    version_number: int
    change_reason: str
    invalidated_components: list[str] = Field(default_factory=list)
    created_at: datetime


class ScenePreparationJobRead(BaseModel):
    id: uuid.UUID
    manifest_version: int
    status: str
    stage: str
    progress: int
    job_data: dict[str, Any] = Field(default_factory=dict)
    error_message: str | None = None
    created_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None


class SceneAgentRead(BaseModel):
    id: uuid.UUID
    character_id: uuid.UUID | None = None
    key: str
    name: str
    role: str
    profile: dict[str, Any] = Field(default_factory=dict)
    runtime_state: dict[str, Any] = Field(default_factory=dict)
    voice_profile: dict[str, Any] = Field(default_factory=dict)


class SceneSourceRead(BaseModel):
    id: uuid.UUID
    agent_key: str | None = None
    title: str
    url: str
    snippet: str
    freshness: str
    retrieved_at: datetime


class SceneTurnRead(BaseModel):
    id: uuid.UUID
    speaker_type: str
    speaker_key: str | None = None
    speaker_name: str
    action: str
    text: str
    audio_url: str | None = None
    audio_data: dict[str, Any] = Field(default_factory=dict)
    citations: list[str] = Field(default_factory=list)
    turn_data: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime


class WorldSceneRead(BaseModel):
    id: uuid.UUID
    project_id: uuid.UUID
    status: SceneStatus
    raw_prompt: str
    active_manifest_version: int
    manifest: SceneManifest
    preparation: dict[str, Any] = Field(default_factory=dict)
    versions: list[SceneManifestVersionRead] = Field(default_factory=list)
    preparation_job: ScenePreparationJobRead | None = None
    agents: list[SceneAgentRead] = Field(default_factory=list)
    sources: list[SceneSourceRead] = Field(default_factory=list)
    turns: list[SceneTurnRead] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime


class SceneBuildQueued(BaseModel):
    scene_id: uuid.UUID
    job_id: uuid.UUID
    status: str
    stage: str


class SceneRevertRequest(BaseModel):
    expected_version: int = Field(ge=1)
    target_version: int = Field(ge=1)
