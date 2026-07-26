from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = Field(default="RoleBricks", alias="APP_NAME")
    app_env: str = Field(default="development", alias="APP_ENV")
    app_host: str = Field(default="127.0.0.1", alias="APP_HOST")
    app_port: int = Field(default=8000, alias="APP_PORT")
    debug: bool = Field(default=False, alias="DEBUG")
    auto_migrate: bool = Field(default=False, alias="AUTO_MIGRATE")

    database_url: str = Field(
        default="sqlite+pysqlite:///./data/emotionos.db",
        alias="DATABASE_URL",
    )
    database_backend: str = Field(default="local", alias="DATABASE_BACKEND")
    lakebase_endpoint_name: str = Field(default="", alias="LAKEBASE_ENDPOINT_NAME")

    scene_compiler_provider: str = Field(default="databricks", alias="SCENE_COMPILER_PROVIDER")
    scene_research_provider: str = Field(default="openai", alias="SCENE_RESEARCH_PROVIDER")
    scene_retrieval_provider: str = Field(default="databricks", alias="SCENE_RETRIEVAL_PROVIDER")
    scene_worker_count: int = Field(default=2, alias="SCENE_WORKER_COUNT")
    scene_max_agents: int = Field(default=5, alias="SCENE_MAX_AGENTS")
    scene_cache_ttl_minutes: int = Field(default=360, alias="SCENE_CACHE_TTL_MINUTES")
    scene_stable_cache_ttl_minutes: int = Field(
        default=10080,
        alias="SCENE_STABLE_CACHE_TTL_MINUTES",
    )
    admin_email_allowlist: str = Field(default="", alias="ADMIN_EMAIL_ALLOWLIST")

    databricks_host: str = Field(default="", alias="DATABRICKS_HOST")
    databricks_serving_endpoint: str = Field(default="", alias="DATABRICKS_SERVING_ENDPOINT")
    databricks_ai_search_index: str = Field(default="", alias="DATABRICKS_AI_SEARCH_INDEX")
    databricks_sql_warehouse_id: str = Field(default="", alias="DATABRICKS_SQL_WAREHOUSE_ID")
    databricks_catalog: str = Field(default="workspace", alias="DATABRICKS_CATALOG")
    databricks_schema: str = Field(default="emotionos_worlds", alias="DATABRICKS_SCHEMA")
    databricks_timeout_seconds: int = Field(default=90, alias="DATABRICKS_TIMEOUT_SECONDS")
    llm_temperature: float = Field(default=0.2, alias="LLM_TEMPERATURE")
    mlflow_experiment_id: str = Field(default="", alias="MLFLOW_EXPERIMENT_ID")

    audio_data_dir: str = Field(default="./data/emotionos_audio", alias="AUDIO_DATA_DIR")
    audio_volume_path: str = Field(default="", alias="AUDIO_VOLUME_PATH")
    max_audio_size_mb: int = Field(default=25, alias="MAX_AUDIO_SIZE_MB")

    openai_api_key: str = Field(default="", alias="OPENAI_API_KEY")
    openai_base_url: str = Field(default="https://api.openai.com/v1", alias="OPENAI_BASE_URL")
    openai_research_model: str = Field(default="gpt-5.6-luna", alias="OPENAI_RESEARCH_MODEL")
    openai_transcription_model: str = Field(default="gpt-4o-transcribe", alias="OPENAI_TRANSCRIPTION_MODEL")
    openai_tts_model: str = Field(default="gpt-4o-mini-tts", alias="OPENAI_TTS_MODEL")
    openai_tts_voice: str = Field(default="marin", alias="OPENAI_TTS_VOICE")
    openai_custom_voice_id: str = Field(default="", alias="OPENAI_CUSTOM_VOICE_ID")
    openai_timeout_seconds: int = Field(default=90, alias="OPENAI_TIMEOUT_SECONDS")

    voice_provider: str = Field(default="adaptive", alias="VOICE_PROVIDER")
    adaptive_openai_feminine_voice: str = Field(default="marin", alias="ADAPTIVE_OPENAI_FEMININE_VOICE")
    adaptive_openai_masculine_voice: str = Field(default="cedar", alias="ADAPTIVE_OPENAI_MASCULINE_VOICE")

    sarvam_api_key: str = Field(default="", alias="SARVAM_API_KEY")
    sarvam_base_url: str = Field(default="https://api.sarvam.ai", alias="SARVAM_BASE_URL")
    sarvam_tts_model: str = Field(default="bulbul:v3", alias="SARVAM_TTS_MODEL")
    sarvam_feminine_speaker: str = Field(default="priya", alias="SARVAM_FEMININE_SPEAKER")
    sarvam_masculine_speaker: str = Field(default="shubh", alias="SARVAM_MASCULINE_SPEAKER")
    sarvam_pronunciation_dict_id: str = Field(default="", alias="SARVAM_PRONUNCIATION_DICT_ID")
    sarvam_sample_rate: int = Field(default=24000, alias="SARVAM_SAMPLE_RATE")
    sarvam_timeout_seconds: int = Field(default=90, alias="SARVAM_TIMEOUT_SECONDS")

    hf_token: str = Field(default="", alias="HF_TOKEN")
    hf_space_id: str = Field(default="", alias="HF_SPACE_ID")
    hf_space_api_name: str = Field(default="/generate", alias="HF_SPACE_API_NAME")

    # Test-only injection. Production and development never fall back to this provider.
    use_mock_tts: bool = Field(default=False, alias="USE_MOCK_TTS")

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    @field_validator(
        "openai_timeout_seconds",
        "max_audio_size_mb",
        "sarvam_timeout_seconds",
        "scene_worker_count",
        "scene_max_agents",
        "scene_cache_ttl_minutes",
        "scene_stable_cache_ttl_minutes",
        "databricks_timeout_seconds",
    )
    @classmethod
    def positive_int(cls, value: int) -> int:
        if value <= 0:
            raise ValueError("must be positive")
        return value

    @field_validator("voice_provider")
    @classmethod
    def supported_voice_provider(cls, value: str) -> str:
        normalized = value.strip().lower()
        if normalized not in {"adaptive", "openai", "sarvam", "space"}:
            raise ValueError("voice provider must be adaptive, openai, sarvam, or space")
        return normalized

    @field_validator("database_backend")
    @classmethod
    def supported_database_backend(cls, value: str) -> str:
        normalized = value.strip().lower()
        if normalized not in {"local", "lakebase"}:
            raise ValueError("database backend must be local or lakebase")
        return normalized

    @field_validator("scene_compiler_provider")
    @classmethod
    def supported_scene_compiler_provider(cls, value: str) -> str:
        normalized = value.strip().lower()
        if normalized not in {"databricks", "rules"}:
            raise ValueError("scene compiler provider must be databricks or rules")
        return normalized

    @field_validator("scene_research_provider")
    @classmethod
    def supported_scene_research_provider(cls, value: str) -> str:
        normalized = value.strip().lower()
        if normalized not in {"openai", "none"}:
            raise ValueError("scene research provider must be openai or none")
        return normalized

    @field_validator("scene_retrieval_provider")
    @classmethod
    def supported_scene_retrieval_provider(cls, value: str) -> str:
        normalized = value.strip().lower()
        if normalized not in {"databricks", "database"}:
            raise ValueError("scene retrieval provider must be databricks or database")
        return normalized

    @field_validator("scene_max_agents")
    @classmethod
    def mvp_scene_agent_limit(cls, value: int) -> int:
        if value > 5:
            raise ValueError("SCENE_MAX_AGENTS can be at most 5 for this MVP")
        return value

    @field_validator("sarvam_sample_rate")
    @classmethod
    def supported_sarvam_sample_rate(cls, value: int) -> int:
        if value not in {8000, 16000, 22050, 24000, 32000, 44100, 48000}:
            raise ValueError("SARVAM_SAMPLE_RATE is not supported by Bulbul v3 REST")
        return value

    @property
    def audio_root(self) -> Path:
        return Path(self.audio_data_dir).resolve()

    @property
    def openai_configured(self) -> bool:
        key = self.openai_api_key.strip()
        return bool(key and key.lower() not in {"replace_me", "your_openai_api_key"})

    @property
    def sarvam_configured(self) -> bool:
        key = self.sarvam_api_key.strip()
        return bool(key and key.lower() not in {"replace_me", "your_sarvam_api_key"})

    @property
    def databricks_configured(self) -> bool:
        return bool(self.databricks_serving_endpoint.strip())

    @property
    def scene_research_configured(self) -> bool:
        return self.scene_research_provider == "none" or self.openai_configured

    @property
    def lakebase_configured(self) -> bool:
        return bool(self.lakebase_endpoint_name.strip())

    @property
    def scene_retrieval_configured(self) -> bool:
        return self.scene_retrieval_provider == "database" or bool(
            self.databricks_ai_search_index.strip()
        )

    @property
    def databricks_lakehouse_configured(self) -> bool:
        return bool(
            self.databricks_sql_warehouse_id.strip()
            and self.databricks_catalog.strip()
            and self.databricks_schema.strip()
        )

    @property
    def test_mode(self) -> bool:
        return self.app_env.strip().lower() == "test"

    @property
    def admin_emails(self) -> set[str]:
        return {
            value.strip().casefold()
            for value in self.admin_email_allowlist.split(",")
            if value.strip()
        }


@lru_cache
def get_settings() -> Settings:
    return Settings()
