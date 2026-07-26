from __future__ import annotations

from collections import Counter
from datetime import timedelta
from statistics import median
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from emotionos.app.core.config import Settings
from emotionos.app.db.base import utc_now
from emotionos.app.db.models import (
    Scene,
    SceneAgent,
    SceneMemoryRecord,
    ScenePreparationJob,
    SceneTurn,
)
from emotionos.app.providers.base import ProviderStatus, VoiceProvider
from emotionos.app.services.job_queue import PriorityJobQueue


class AdminObservabilityService:
    """Aggregate operational metadata without returning prompts, dialogue, or credentials."""

    def __init__(
        self,
        *,
        settings: Settings,
        voice_provider: VoiceProvider,
        queue: PriorityJobQueue,
    ) -> None:
        self.settings = settings
        self.voice_provider = voice_provider
        self.queue = queue

    def overview(self, db: Session) -> dict[str, Any]:
        now = utc_now()
        since = now - timedelta(hours=24)
        scenes = list(
            db.scalars(
                select(Scene)
                .where(Scene.raw_prompt != "")
                .order_by(Scene.created_at.desc())
                .limit(2000)
            ).all()
        )
        jobs = list(
            db.scalars(
                select(ScenePreparationJob)
                .order_by(ScenePreparationJob.created_at.desc())
                .limit(2000)
            ).all()
        )
        turns = list(
            db.scalars(
                select(SceneTurn)
                .where(SceneTurn.created_at >= since)
                .order_by(SceneTurn.created_at.desc())
                .limit(5000)
            ).all()
        )
        providers = self._provider_rows()
        required_ready = all(
            row["ready"]
            for row in providers
            if row["required"]
        )
        prep_latencies = [
            self._elapsed_seconds(job.started_at, job.completed_at)
            for job in jobs
            if job.status == "completed" and job.started_at and job.completed_at
        ]
        turn_latencies = [
            float((turn.turn_data or {}).get("latency_ms") or 0) / 1000
            for turn in turns
            if turn.speaker_type == "agent" and (turn.turn_data or {}).get("latency_ms")
        ]
        token_usage = Counter()
        for scene in scenes:
            self._add_usage(token_usage, (scene.preparation or {}).get("compiler_usage"))
        for job in jobs:
            data = dict(job.job_data or {})
            self._add_usage(token_usage, data.get("research_usage"))
            self._add_usage(token_usage, data.get("prepare_usage"))
        for turn in turns:
            data = dict(turn.turn_data or {})
            self._add_usage(token_usage, data.get("usage"))
            self._add_usage(token_usage, data.get("live_research_usage"))

        voice_calls: Counter[str] = Counter()
        voice_seconds: Counter[str] = Counter()
        audio_failures = 0
        for turn in turns:
            if turn.speaker_type != "agent":
                continue
            audio = dict(turn.audio_data or {})
            engine = str(audio.get("engine_name") or audio.get("route_provider") or "unknown")
            if audio.get("status") == "ready":
                voice_calls[engine] += 1
                voice_seconds[engine] += float(audio.get("duration_seconds") or 0)
            elif audio.get("status") == "failed":
                audio_failures += 1

        job_states = Counter(job.status for job in jobs)
        cache_hits = sum(bool((job.job_data or {}).get("cache_hit")) for job in jobs)
        recent_failures = [
            {
                "time": job.completed_at or job.created_at,
                "stage": job.stage,
                "reason": self._safe_failure_reason(job.error_message),
            }
            for job in jobs
            if job.status == "failed"
        ][:6]
        return {
            "generated_at": now,
            "overall": "healthy" if required_ready else "degraded",
            "providers": providers,
            "usage": {
                "scenes_total": len(scenes),
                "scenes_24h": sum(self._is_recent(scene.created_at, since) for scene in scenes),
                "scenes_live": sum(scene.status in {"live", "paused"} for scene in scenes),
                "scenes_ready": sum(scene.status == "ready" for scene in scenes),
                "agents_total": self._count(db, SceneAgent),
                "memories_total": self._count(db, SceneMemoryRecord),
                "turns_24h": len(turns),
                "agent_turns_24h": sum(turn.speaker_type == "agent" for turn in turns),
                "tokens_recorded": dict(token_usage),
            },
            "latency": {
                "scene_prepare_median_seconds": self._median(prep_latencies),
                "scene_prepare_p95_seconds": self._percentile(prep_latencies, 0.95),
                "turn_median_seconds": self._median(turn_latencies),
                "turn_p95_seconds": self._percentile(turn_latencies, 0.95),
            },
            "queue": {
                "depth": self.queue.depth,
                "workers": self.queue.active_workers,
                "queued_jobs": job_states.get("queued", 0),
                "running_jobs": job_states.get("running", 0),
                "failed_jobs": job_states.get("failed", 0),
            },
            "voice_balance": [
                {
                    "engine": engine,
                    "calls_24h": calls,
                    "audio_seconds_24h": round(voice_seconds[engine], 1),
                }
                for engine, calls in sorted(voice_calls.items())
            ],
            "cache": {
                "hits_total": cache_hits,
                "eligible_jobs": len(jobs),
                "hit_rate_percent": round((cache_hits / len(jobs)) * 100, 1) if jobs else 0.0,
            },
            "failures": {
                "audio_24h": audio_failures,
                "recent_builds": recent_failures,
            },
        }

    @staticmethod
    def _is_recent(value: Any, since: Any) -> bool:
        if value is None:
            return False
        if getattr(value, "tzinfo", None) is None and getattr(since, "tzinfo", None) is not None:
            since = since.replace(tzinfo=None)
        return bool(value >= since)

    @staticmethod
    def _elapsed_seconds(started: Any, completed: Any) -> float:
        return max(0.0, float((completed - started).total_seconds()))

    def _provider_rows(self) -> list[dict[str, Any]]:
        status_for = getattr(self.voice_provider, "status_for", None)
        openai = status_for("openai") if callable(status_for) else None
        sarvam = status_for("sarvam") if callable(status_for) else None
        space = status_for("space") if callable(status_for) else None
        rows = [
            self._row("databricks", "Databricks agent reasoning", self.settings.databricks_configured, self.settings.databricks_configured, True),
            self._row("openai-research", "OpenAI live research", self.settings.openai_configured, self.settings.scene_research_configured, True),
            self._status_row("openai-voice", "OpenAI expressive voice", openai, self.settings.openai_configured, False),
            self._status_row("sarvam-voice", "Sarvam Indian voice", sarvam, self.settings.sarvam_configured, False),
            self._status_row("hf-space", "Hugging Face voice space", space, bool(self.settings.hf_space_id.strip() and self.settings.hf_token.strip()), False),
            self._row("lakebase", "Lakebase scene state", self.settings.lakebase_configured or self.settings.database_backend == "local", self.settings.lakebase_configured or self.settings.database_backend == "local", True),
            self._row("vector-memory", "Databricks memory search", self.settings.scene_retrieval_configured, self.settings.scene_retrieval_configured and (self.settings.databricks_lakehouse_configured or self.settings.scene_retrieval_provider == "database"), True),
            self._row("mlflow", "MLflow traces", bool(self.settings.mlflow_experiment_id.strip()) or self.settings.test_mode, bool(self.settings.mlflow_experiment_id.strip()) or self.settings.test_mode, False),
        ]
        voice_ready = any(row["ready"] for row in rows if row["key"] in {"openai-voice", "sarvam-voice", "hf-space"})
        rows.append(self._row("voice-router", "Adaptive voice router", voice_ready, voice_ready, True))
        return rows

    @staticmethod
    def _row(key: str, label: str, configured: bool, ready: bool, required: bool) -> dict[str, Any]:
        return {
            "key": key,
            "label": label,
            "configured": bool(configured),
            "ready": bool(ready),
            "required": required,
            "state": "active" if ready else "needs_setup" if not configured else "unavailable",
        }

    def _status_row(
        self,
        key: str,
        label: str,
        status: ProviderStatus | None,
        configured: bool,
        required: bool,
    ) -> dict[str, Any]:
        return self._row(key, label, configured, bool(status and status.ready), required)

    @staticmethod
    def _add_usage(counter: Counter[str], usage: Any) -> None:
        if not isinstance(usage, dict):
            return
        for key in ("prompt_tokens", "completion_tokens", "total_tokens"):
            try:
                counter[key] += max(0, int(usage.get(key) or 0))
            except (TypeError, ValueError):
                continue

    @staticmethod
    def _safe_failure_reason(message: str | None) -> str:
        value = (message or "").casefold()
        if "rate limit" in value or "429" in value:
            return "Provider rate limit"
        if "timeout" in value or "timed out" in value:
            return "Provider timeout"
        if "key" in value or "auth" in value or "401" in value or "403" in value:
            return "Provider authentication"
        if "memory" in value or "index" in value:
            return "Memory indexing"
        if "voice" in value or "audio" in value or "tts" in value:
            return "Voice generation"
        return "Scene preparation"

    @staticmethod
    def _count(db: Session, model) -> int:
        return int(db.scalar(select(func.count()).select_from(model)) or 0)

    @staticmethod
    def _median(values: list[float]) -> float | None:
        return round(float(median(values)), 2) if values else None

    @staticmethod
    def _percentile(values: list[float], percentile: float) -> float | None:
        if not values:
            return None
        ordered = sorted(values)
        index = min(len(ordered) - 1, max(0, int(round((len(ordered) - 1) * percentile))))
        return round(float(ordered[index]), 2)
