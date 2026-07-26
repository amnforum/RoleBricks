from __future__ import annotations

import asyncio
import re
import uuid
from pathlib import Path
from typing import Any

from pydantic import ValidationError as PydanticValidationError
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session, selectinload, sessionmaker

from emotionos.app.audio.storage import StorageManager
from emotionos.app.core.config import Settings
from emotionos.app.core.exceptions import NotFoundError, ValidationError
from emotionos.app.db.base import utc_now
from emotionos.app.db.models import (
    Character,
    CharacterProfileVersion,
    Project,
    Scene,
    SceneAgent,
    SceneManifestVersion,
    SceneMemoryRecord,
    ScenePreparationJob,
    SceneSource,
    SceneTurn,
)
from emotionos.app.domain.scene_manifest import (
    SceneAgentRead,
    SceneBlueprintPatch,
    SceneBuildQueued,
    SceneDraftCreate,
    SceneManifest,
    SceneManifestVersionRead,
    ScenePreparationJobRead,
    SceneRevertRequest,
    SceneSourceRead,
    SceneTurnCreate,
    SceneTurnRead,
    WorldSceneRead,
)
from emotionos.app.domain.schemas import SpeechProfile
from emotionos.app.providers.base import VoiceGenerationContext, VoiceProvider
from emotionos.app.services.floor_manager import FloorManager
from emotionos.app.services.job_queue import PriorityJobQueue
from emotionos.app.services.scene_compiler import SceneCompiler
from emotionos.app.services.scene_research import SceneResearchProvider
from emotionos.app.services.scene_retrieval import SceneRetriever
from emotionos.app.services.telemetry import SceneTelemetry


class SceneWorldService:
    terminal_job_statuses = {"completed", "failed", "cancelled", "stale"}

    def __init__(
        self,
        *,
        settings: Settings,
        compiler: SceneCompiler,
        research: SceneResearchProvider,
        retriever: SceneRetriever,
        telemetry: SceneTelemetry,
        voice_provider: VoiceProvider,
        storage: StorageManager,
        session_factory: sessionmaker,
    ) -> None:
        self.settings = settings
        self.compiler = compiler
        self.research = research
        self.retriever = retriever
        self.telemetry = telemetry
        self.voice_provider = voice_provider
        self.storage = storage
        self.session_factory = session_factory
        self.floor_manager = FloorManager()
        self.queue: PriorityJobQueue | None = None

    def attach_queue(self, queue: PriorityJobQueue) -> None:
        self.queue = queue

    async def create_draft(self, db: Session, payload: SceneDraftCreate) -> WorldSceneRead:
        with self.telemetry.span(
            "scene.compile",
            span_type="CHAIN",
            inputs={"locale": payload.locale, "prompt_characters": len(payload.prompt)},
        ) as span:
            manifest, usage = await self.compiler.compile(payload.prompt, locale=payload.locale)
            span.set_outputs({"cast_candidates": len(manifest.ai_characters), "usage": usage})
        if len(manifest.selected_characters) > self.settings.scene_max_agents:
            raise ValidationError("The compiled scene selected more than three AI characters")

        project = db.scalar(select(Project).where(Project.name == "EmotionOS Worlds").order_by(Project.created_at))
        if project is None:
            project = Project(name="EmotionOS Worlds")
            db.add(project)
            db.flush()

        scene = Scene(
            project_id=project.id,
            title=manifest.title,
            description=manifest.scenario_summary,
            episode_number=0,
            raw_prompt=payload.prompt,
            status="blueprint",
            active_manifest_version=1,
            manifest=manifest.model_dump(mode="json"),
            preparation={
                "compiler": self.compiler.provider_name,
                "compiler_usage": usage,
                "research_started": False,
                "message": "Review your role and cast before any research or voice work begins.",
            },
        )
        db.add(scene)
        db.flush()
        db.add(
            SceneManifestVersion(
                scene_id=scene.id,
                version_number=1,
                manifest=scene.manifest,
                change_reason="Initial scene blueprint",
                invalidated_components=[],
            )
        )
        db.commit()
        return self.read_scene(db, scene.id)

    def list_scenes(self, db: Session, *, limit: int = 20) -> list[WorldSceneRead]:
        ids = list(
            db.scalars(
                select(Scene.id)
                .where(Scene.raw_prompt != "")
                .order_by(Scene.updated_at.desc())
                .limit(max(1, min(limit, 50)))
            ).all()
        )
        return [self.read_scene(db, scene_id) for scene_id in ids]

    def read_scene(self, db: Session, scene_id: uuid.UUID) -> WorldSceneRead:
        scene = db.scalar(self._scene_query().where(Scene.id == scene_id))
        if scene is None or not scene.raw_prompt:
            raise NotFoundError("Scene was not found")

        job = max(scene.preparation_jobs, key=lambda item: item.created_at, default=None)
        return WorldSceneRead(
            id=scene.id,
            project_id=scene.project_id,
            status=scene.status,
            raw_prompt=scene.raw_prompt,
            active_manifest_version=scene.active_manifest_version,
            manifest=SceneManifest.model_validate(scene.manifest),
            preparation=dict(scene.preparation or {}),
            versions=[
                SceneManifestVersionRead(
                    version_number=version.version_number,
                    change_reason=version.change_reason,
                    invalidated_components=list(version.invalidated_components or []),
                    created_at=version.created_at,
                )
                for version in scene.manifest_versions
            ],
            preparation_job=self._job_read(job) if job else None,
            agents=[
                SceneAgentRead(
                    id=agent.id,
                    character_id=agent.character_id,
                    key=agent.agent_key,
                    name=agent.name,
                    role=agent.role,
                    profile=dict(agent.profile or {}),
                    runtime_state=dict(agent.runtime_state or {}),
                    voice_profile=self._voice_profile_read(scene.id, agent),
                )
                for agent in scene.agents
            ],
            sources=[
                SceneSourceRead(
                    id=source.id,
                    agent_key=source.agent_key,
                    title=source.title,
                    url=source.url,
                    snippet=source.snippet,
                    freshness=source.freshness,
                    retrieved_at=source.retrieved_at,
                )
                for source in sorted(scene.sources, key=lambda item: item.retrieved_at, reverse=True)
            ],
            turns=[self._turn_read(scene.id, turn) for turn in scene.turns],
            created_at=scene.created_at,
            updated_at=scene.updated_at,
        )

    def patch_blueprint(
        self,
        db: Session,
        scene_id: uuid.UUID,
        payload: SceneBlueprintPatch,
    ) -> WorldSceneRead:
        scene = self._get_scene(db, scene_id)
        if scene.status in {"confirmed", "preparing", "live", "paused", "completed"}:
            raise ValidationError(
                "Pause or finish active work before editing this blueprint.",
                details={"status": scene.status},
            )
        self._check_version(scene, payload.expected_version)

        manifest = SceneManifest.model_validate(scene.manifest)
        changes = payload.model_dump(
            exclude_unset=True,
            exclude={"expected_version", "change_reason"},
            mode="json",
        )
        manifest_data = manifest.model_dump(mode="json")
        changed_fields: set[str] = set()
        for key, value in changes.items():
            if manifest_data.get(key) != value:
                manifest_data[key] = value
                changed_fields.add(key)
        if not changed_fields:
            return self.read_scene(db, scene_id)

        next_version = scene.active_manifest_version + 1
        manifest_data["version"] = next_version
        try:
            updated = SceneManifest.model_validate(manifest_data)
        except PydanticValidationError as exc:
            raise ValidationError(
                "The blueprint is invalid.",
                details={"reason": str(exc)},
            ) from exc
        invalidated = self._invalidated_components(changed_fields)
        scene.title = updated.title
        scene.description = updated.scenario_summary
        scene.manifest = updated.model_dump(mode="json")
        scene.active_manifest_version = next_version
        scene.status = "blueprint"
        scene.preparation = {
            **dict(scene.preparation or {}),
            "invalidated_components": invalidated,
            "message": "Blueprint changed. Confirm it again before preparation.",
        }
        db.add(
            SceneManifestVersion(
                scene_id=scene.id,
                version_number=next_version,
                manifest=scene.manifest,
                change_reason=payload.change_reason,
                invalidated_components=invalidated,
            )
        )
        db.commit()
        return self.read_scene(db, scene_id)

    def revert_blueprint(
        self,
        db: Session,
        scene_id: uuid.UUID,
        payload: SceneRevertRequest,
    ) -> WorldSceneRead:
        scene = self._get_scene(db, scene_id)
        if scene.status not in {"draft", "blueprint", "ready"}:
            raise ValidationError("Only an inactive scene can revert to an earlier blueprint")
        self._check_version(scene, payload.expected_version)
        target = db.scalar(
            select(SceneManifestVersion).where(
                SceneManifestVersion.scene_id == scene.id,
                SceneManifestVersion.version_number == payload.target_version,
            )
        )
        if target is None:
            raise NotFoundError("Scene blueprint version was not found")

        next_version = scene.active_manifest_version + 1
        data = dict(target.manifest)
        data["version"] = next_version
        manifest = SceneManifest.model_validate(data)
        invalidated = ["scene_state", "research", "personas", "voices", "behavior", "runtime"]
        scene.title = manifest.title
        scene.description = manifest.scenario_summary
        scene.manifest = manifest.model_dump(mode="json")
        scene.active_manifest_version = next_version
        scene.status = "blueprint"
        scene.preparation = {
            **dict(scene.preparation or {}),
            "invalidated_components": invalidated,
            "message": f"Reverted to blueprint {payload.target_version}. Confirm it before preparation.",
        }
        db.add(
            SceneManifestVersion(
                scene_id=scene.id,
                version_number=next_version,
                manifest=scene.manifest,
                change_reason=f"Reverted to blueprint {payload.target_version}",
                invalidated_components=invalidated,
            )
        )
        db.commit()
        return self.read_scene(db, scene_id)

    def confirm(self, db: Session, scene_id: uuid.UUID, *, expected_version: int) -> SceneBuildQueued:
        scene = self._get_scene(db, scene_id)
        if scene.status not in {"draft", "blueprint"}:
            raise ValidationError("This scene is not waiting for blueprint confirmation")
        self._check_version(scene, expected_version)
        manifest = SceneManifest.model_validate(scene.manifest)
        selected = manifest.selected_characters
        if not selected:
            raise ValidationError("Select at least one AI character")
        if len(selected) > self.settings.scene_max_agents:
            raise ValidationError("Select no more than three AI characters")
        unauthorized = [
            character.name
            for character in selected
            if character.voice.identity_mode == "authorized_match"
            and not character.voice.consent_confirmed
        ]
        if unauthorized:
            raise ValidationError(
                "Authorized speaker matching needs an owned or permitted reference before preparation.",
                details={"characters": unauthorized},
            )

        scene.status = "confirmed"
        scene.confirmed_at = utc_now()
        scene.preparation = {
            **dict(scene.preparation or {}),
            "message": "Blueprint confirmed. Preparation is queued.",
            "research_started": False,
        }
        job = ScenePreparationJob(
            scene_id=scene.id,
            manifest_version=scene.active_manifest_version,
            status="queued",
            stage="queued",
            progress=0,
            job_data={
                "compiler": self.compiler.provider_name,
                "research_provider": self.research.provider_name,
            },
        )
        db.add(job)
        db.commit()
        db.refresh(job)
        return SceneBuildQueued(scene_id=scene.id, job_id=job.id, status=job.status, stage=job.stage)

    async def enqueue(self, job_id: uuid.UUID) -> None:
        if self.queue is None:
            raise RuntimeError("Scene preparation queue has not started")
        await self.queue.enqueue(job_id, priority=30)

    async def recover_pending_jobs(self) -> None:
        with self.session_factory() as db:
            jobs = list(
                db.scalars(
                    select(ScenePreparationJob).where(ScenePreparationJob.status.in_(["queued", "running"]))
                ).all()
            )
            for job in jobs:
                job.status = "queued"
                job.stage = "queued"
                job.progress = min(job.progress, 5)
                job.started_at = None
            db.commit()
            ids = [job.id for job in jobs]
        for job_id in ids:
            await self.enqueue(job_id)

    async def run_job(self, job_id: uuid.UUID, force: bool = False) -> None:
        del force
        with self.session_factory() as db:
            job = db.get(ScenePreparationJob, job_id)
            if job is None or job.status in self.terminal_job_statuses:
                return
            scene = db.get(Scene, job.scene_id)
            if scene is None or job.manifest_version != scene.active_manifest_version:
                job.status = "stale"
                job.stage = "stale"
                job.error_message = "The blueprint changed before this job started."
                job.completed_at = utc_now()
                db.commit()
                return
            manifest = SceneManifest.model_validate(scene.manifest)
            scene.status = "preparing"
            scene.preparation = {
                **dict(scene.preparation or {}),
                "research_started": True,
                "message": "Resolving people, facts, and scene requirements.",
            }
            job.status = "running"
            job.stage = "resolving_scene"
            job.progress = 8
            job.started_at = utc_now()
            db.commit()

        try:
            with self.telemetry.span(
                "scene.research",
                span_type="RETRIEVER",
                inputs={
                    "scene_id": str(job.scene_id),
                    "query_count": len(manifest.required_fresh_searches),
                },
            ) as span:
                research_packet, research_usage = await self.research.research(
                    manifest.required_fresh_searches
                )
                span.set_outputs({
                    "source_count": len(research_packet.get("sources") or []),
                    "usage": research_usage,
                })
            self._set_job_progress(
                job_id,
                stage="compiling_personas",
                progress=42,
                data={"research_usage": research_usage},
            )
            with self.telemetry.span(
                "scene.prepare_personas",
                span_type="CHAIN",
                inputs={"scene_id": str(job.scene_id), "cast_size": len(manifest.selected_characters)},
            ) as span:
                prepared, compile_usage = await self.compiler.prepare(
                    manifest,
                    research_packet=research_packet,
                )
                span.set_outputs({"prepared_characters": len(prepared.characters), "usage": compile_usage})
            self._set_job_progress(
                job_id,
                stage="preparing_voices",
                progress=68,
                data={"prepare_usage": compile_usage},
            )

            prepared_by_key = {item.key: item for item in prepared.characters}
            samples = await asyncio.gather(
                *[
                    self._generate_agent_audio(
                        scene_id=job.scene_id,
                        character=character,
                        text=prepared_by_key[character.key].opening_line,
                        category="samples",
                    )
                    for character in manifest.selected_characters
                ]
            )
            sample_by_key = {
                character.key: sample
                for character, sample in zip(manifest.selected_characters, samples, strict=True)
            }
            self._set_job_progress(job_id, stage="initializing_memory", progress=86)
            index_records = self._persist_prepared_scene(
                job_id=job_id,
                manifest=manifest,
                prepared=prepared,
                research_packet=research_packet,
                sample_by_key=sample_by_key,
            )
            with self.telemetry.span(
                "scene.index_memory",
                span_type="RETRIEVER",
                inputs={"scene_id": str(job.scene_id), "record_count": len(index_records)},
            ) as span:
                await self.retriever.index(index_records)
                span.set_outputs({"indexed_records": len(index_records)})
        except Exception as exc:
            with self.session_factory() as db:
                job = db.get(ScenePreparationJob, job_id)
                if job is not None:
                    job.status = "failed"
                    job.stage = "failed"
                    job.error_message = str(exc)
                    job.completed_at = utc_now()
                    scene = db.get(Scene, job.scene_id)
                    if scene is not None:
                        scene.status = "blueprint"
                        scene.preparation = {
                            **dict(scene.preparation or {}),
                            "message": "Preparation stopped. The blueprint is still safe to edit and retry.",
                            "error": str(exc),
                        }
                    db.commit()

    def enter(self, db: Session, scene_id: uuid.UUID) -> WorldSceneRead:
        scene = self._get_scene(db, scene_id)
        if scene.status not in {"ready", "paused"}:
            raise ValidationError("This scene is not ready to enter", details={"status": scene.status})
        scene.status = "live"
        db.commit()
        return self.read_scene(db, scene.id)

    def pause(self, db: Session, scene_id: uuid.UUID) -> WorldSceneRead:
        scene = self._get_scene(db, scene_id)
        if scene.status != "live":
            raise ValidationError("Only a live scene can be paused")
        scene.status = "paused"
        db.commit()
        return self.read_scene(db, scene.id)

    def resume(self, db: Session, scene_id: uuid.UUID) -> WorldSceneRead:
        scene = self._get_scene(db, scene_id)
        if scene.status not in {"paused", "completed"}:
            raise ValidationError("Only a paused or completed scene can be resumed")
        scene.status = "ready"
        db.commit()
        return self.read_scene(db, scene.id)

    async def complete(self, db: Session, scene_id: uuid.UUID) -> WorldSceneRead:
        scene = db.scalar(self._scene_query().where(Scene.id == scene_id))
        if scene is None:
            raise NotFoundError("Scene was not found")
        if scene.status not in {"live", "paused"}:
            raise ValidationError("Only a live or paused scene can be completed")
        last_user_turn = next(
            (turn for turn in reversed(scene.turns) if turn.speaker_type == "user"),
            None,
        )
        index_records: list[dict[str, Any]] = []
        for agent in scene.agents:
            content = (
                f"The scene ended after {len(scene.turns)} turns. "
                f"The user's latest position was: {last_user_turn.text}"
                if last_user_turn
                else f"The scene ended after {len(scene.turns)} turns."
            )
            memory = SceneMemoryRecord(
                scene_id=scene.id,
                agent_id=agent.id,
                layer="reflection",
                visibility="private",
                content=content,
                importance=75,
                memory_data={"relationship": dict(agent.runtime_state or {}).get("relationship") or {}},
            )
            db.add(memory)
            db.flush()
            index_records.append({
                "record_id": f"memory:{memory.id}",
                "scene_id": str(scene.id),
                "character_key": agent.agent_key,
                "record_type": "reflection",
                "content": content,
                "title": "",
                "url": "",
                "freshness": "stable",
                "importance": 75,
                "visibility": "private",
            })
        with self.telemetry.span(
            "scene.complete_memory",
            span_type="MEMORY",
            inputs={"scene_id": str(scene.id), "record_count": len(index_records)},
        ) as span:
            await self.retriever.index(index_records)
            span.set_outputs({"indexed_records": len(index_records)})
        scene.status = "completed"
        db.commit()
        return self.read_scene(db, scene.id)

    async def add_turn(
        self,
        db: Session,
        scene_id: uuid.UUID,
        payload: SceneTurnCreate,
    ) -> WorldSceneRead:
        scene = db.scalar(self._scene_query().where(Scene.id == scene_id))
        if scene is None:
            raise NotFoundError("Scene was not found")
        if scene.status == "ready":
            scene.status = "live"
        if scene.status != "live":
            raise ValidationError("Enter or resume the scene before speaking")

        manifest = SceneManifest.model_validate(scene.manifest)
        user_turn = SceneTurn(
            scene_id=scene.id,
            speaker_type="user",
            speaker_key=None,
            speaker_name=manifest.user_role.name,
            action="say",
            text=payload.text,
        )
        db.add(user_turn)
        db.flush()

        previous_ai_turns = [turn for turn in scene.turns if turn.speaker_type == "agent"]
        last_key = previous_ai_turns[-1].speaker_key if previous_ai_turns else None
        runtime_states = {agent.agent_key: dict(agent.runtime_state or {}) for agent in scene.agents}
        floor = self.floor_manager.choose(
            manifest=manifest,
            user_text=payload.text,
            turn_count=len(previous_ai_turns),
            last_character_key=last_key,
            runtime_states=runtime_states,
        )
        character = next(
            item for item in manifest.selected_characters if item.key == floor.character_key
        )
        agent = next((item for item in scene.agents if item.agent_key == character.key), None)
        if agent is None:
            raise ValidationError("The prepared character is missing from this scene")

        recent_turns = [
            {
                "speaker_type": turn.speaker_type,
                "speaker_key": turn.speaker_key,
                "speaker_name": turn.speaker_name,
                "action": turn.action,
                "text": turn.text,
            }
            for turn in [*scene.turns, user_turn][-12:]
        ]
        memories = list(
            db.scalars(
                select(SceneMemoryRecord)
                .where(
                    SceneMemoryRecord.scene_id == scene.id,
                    SceneMemoryRecord.agent_id == agent.id,
                    SceneMemoryRecord.active.is_(True),
                )
                .order_by(SceneMemoryRecord.importance.desc(), SceneMemoryRecord.created_at.desc())
                .limit(8)
            ).all()
        )
        memory_payload = [
            {
                "layer": memory.layer,
                "visibility": memory.visibility,
                "content": memory.content,
                "importance": memory.importance,
            }
            for memory in memories
        ]
        source_payload = [
            {
                "id": str(source.id),
                "title": source.title,
                "url": source.url,
                "snippet": source.snippet,
                "freshness": source.freshness,
            }
            for source in scene.sources[:10]
        ]
        live_research_usage: dict[str, int] = {}
        if self._needs_fresh_research(payload.text):
            query = (
                f"{character.identity or character.name}: verify current public facts needed to answer "
                f"the user's question in this scene"
            )
            with self.telemetry.span(
                "scene.live_research",
                span_type="RETRIEVER",
                inputs={"scene_id": str(scene.id), "character_key": character.key, "query_count": 1},
            ) as span:
                live_packet, live_research_usage = await self.research.research([query])
                span.set_outputs({
                    "source_count": len(live_packet.get("sources") or []),
                    "usage": live_research_usage,
                })
            existing_urls = {item["url"] for item in source_payload if item.get("url")}
            for source_data in live_packet.get("sources") or []:
                url = str(source_data.get("url") or "").strip()
                if not url or url in existing_urls:
                    continue
                source = SceneSource(
                    scene_id=scene.id,
                    agent_key=character.key,
                    title=str(source_data.get("title") or "Current source")[:500],
                    url=url,
                    snippet=str(source_data.get("snippet") or ""),
                    freshness=str(source_data.get("freshness") or "current")[:40],
                    source_data={
                        "published_at": source_data.get("published_at"),
                        "supports": source_data.get("supports") or [],
                        "retrieval": "live_turn",
                    },
                )
                db.add(source)
                db.flush()
                source_payload.insert(0, {
                    "id": str(source.id),
                    "title": source.title,
                    "url": source.url,
                    "snippet": source.snippet,
                    "freshness": source.freshness,
                })
                existing_urls.add(url)

        memory_payload, source_payload = await self.retriever.retrieve(
            scene_id=scene.id,
            character_key=character.key,
            query=payload.text,
            current_memories=memory_payload,
            current_sources=source_payload,
        )
        with self.telemetry.span(
            "scene.character_turn",
            span_type="AGENT",
            inputs={
                "scene_id": str(scene.id),
                "character_key": character.key,
                "memory_count": len(memory_payload),
                "source_count": len(source_payload),
                "turn_count": len(recent_turns),
            },
        ) as span:
            action, usage = await self.compiler.decide(
                manifest=manifest,
                character=character,
                runtime_state=dict(agent.runtime_state or {}),
                recent_turns=recent_turns,
                memories=memory_payload,
                sources=source_payload,
            )
            span.set_outputs({
                "action": action.action,
                "citation_count": len(action.cited_source_ids),
                "usage": usage,
            })

        audio_path: str | None = None
        audio_data: dict[str, Any]
        try:
            audio_path, audio_data = await self._generate_agent_audio(
                scene_id=scene.id,
                character=character,
                text=action.spoken_response,
                category="turns",
            )
        except Exception as exc:
            audio_data = {
                "status": "failed",
                "error": str(exc),
                "fallback_used": False,
            }

        ai_turn = SceneTurn(
            scene_id=scene.id,
            speaker_type="agent",
            speaker_key=character.key,
            speaker_name=character.name,
            action=action.action,
            text=action.spoken_response,
            audio_path=audio_path,
            audio_data=audio_data,
            citations=action.cited_source_ids,
            turn_data={
                "private_reason": action.private_reason,
                "mood": action.mood,
                "relationship_delta": action.relationship_delta,
                "floor_score": floor.score,
                "floor_reason": floor.reason,
                "usage": usage,
                "live_research_usage": live_research_usage,
            },
        )
        db.add(ai_turn)
        db.flush()
        state = dict(agent.runtime_state or {})
        state["mood"] = action.mood
        state["turn_count"] = int(state.get("turn_count", 0)) + 1
        state["patience"] = max(0, min(100, int(state.get("patience", character.patience)) - 1))
        relationship = dict(state.get("relationship") or {})
        for dimension, delta in action.relationship_delta.items():
            current = int(relationship.get(dimension, 50))
            relationship[dimension] = max(0, min(100, current + int(delta)))
        state["relationship"] = relationship
        agent.runtime_state = state
        db.add(
            SceneMemoryRecord(
                scene_id=scene.id,
                agent_id=agent.id,
                layer="episode",
                visibility="private",
                content=f"{manifest.user_role.name} said: {payload.text}",
                importance=45,
                source_turn_id=user_turn.id,
                memory_data={"response_action": action.action},
            )
        )
        if state["turn_count"] % 6 == 0:
            db.add(
                SceneMemoryRecord(
                    scene_id=scene.id,
                    agent_id=agent.id,
                    layer="reflection",
                    visibility="private",
                    content=(
                        f"After {state['turn_count']} responses, the current relationship is "
                        f"{relationship or {'baseline': 50}}. The latest unresolved user position is: "
                        f"{payload.text}"
                    ),
                    importance=70,
                    source_turn_id=user_turn.id,
                    memory_data={"relationship": relationship, "consolidated_at_turn": state["turn_count"]},
                )
            )
        db.commit()
        return self.read_scene(db, scene.id)

    @staticmethod
    def _needs_fresh_research(text: str) -> bool:
        return bool(
            re.search(
                r"\b(latest|today|currently|current|recent|newest|this week|this month|release date|right now)\b",
                text,
                re.IGNORECASE,
            )
        )

    def audio_path_for_turn(self, db: Session, scene_id: uuid.UUID, turn_id: uuid.UUID) -> Path:
        turn = db.scalar(
            select(SceneTurn).where(SceneTurn.id == turn_id, SceneTurn.scene_id == scene_id)
        )
        if turn is None or not turn.audio_path:
            raise NotFoundError("Turn audio was not found")
        path = self.storage.resolve(turn.audio_path)
        if not path.exists():
            raise NotFoundError("Turn audio file was not found")
        return path

    def sample_path_for_agent(self, db: Session, scene_id: uuid.UUID, agent_id: uuid.UUID) -> Path:
        agent = db.scalar(
            select(SceneAgent).where(SceneAgent.id == agent_id, SceneAgent.scene_id == scene_id)
        )
        sample_path = (agent.voice_profile or {}).get("sample_audio_path") if agent else None
        if not sample_path:
            raise NotFoundError("Character voice sample was not found")
        path = self.storage.resolve(sample_path)
        if not path.exists():
            raise NotFoundError("Character voice sample file was not found")
        return path

    def _persist_prepared_scene(
        self,
        *,
        job_id: uuid.UUID,
        manifest: SceneManifest,
        prepared,
        research_packet: dict[str, Any],
        sample_by_key: dict[str, tuple[str, dict[str, Any]]],
    ) -> list[dict[str, Any]]:
        prepared_by_key = {item.key: item for item in prepared.characters}
        with self.session_factory() as db:
            job = db.get(ScenePreparationJob, job_id)
            if job is None:
                return []
            scene = db.get(Scene, job.scene_id)
            if scene is None or scene.active_manifest_version != job.manifest_version:
                job.status = "stale"
                job.stage = "stale"
                job.completed_at = utc_now()
                db.commit()
                return []

            old_agents = {
                agent.agent_key: agent
                for agent in db.scalars(
                    select(SceneAgent).where(SceneAgent.scene_id == scene.id)
                ).all()
            }
            db.execute(delete(SceneMemoryRecord).where(SceneMemoryRecord.scene_id == scene.id))
            db.execute(delete(SceneTurn).where(SceneTurn.scene_id == scene.id))
            db.execute(delete(SceneAgent).where(SceneAgent.scene_id == scene.id))
            db.execute(delete(SceneSource).where(SceneSource.scene_id == scene.id))
            db.flush()

            created_agents: dict[str, SceneAgent] = {}
            for index, draft in enumerate(manifest.selected_characters):
                compiled = prepared_by_key[draft.key]
                previous = old_agents.get(draft.key)
                character = db.get(Character, previous.character_id) if previous and previous.character_id else None
                if character is None:
                    character = Character(
                        project_id=scene.project_id,
                        name=draft.name,
                        description=draft.role,
                        personality_summary=compiled.persona_summary,
                        active_profile_version=1,
                    )
                    db.add(character)
                    db.flush()
                    profile_version = 1
                else:
                    character.name = draft.name
                    character.description = draft.role
                    character.personality_summary = compiled.persona_summary
                    profile_version = int(
                        db.scalar(
                            select(func.max(CharacterProfileVersion.version_number)).where(
                                CharacterProfileVersion.character_id == character.id
                            )
                        )
                        or 0
                    ) + 1
                    character.active_profile_version = profile_version

                voice_id = self._adaptive_voice_id(draft)
                db.add(
                    CharacterProfileVersion(
                        character_id=character.id,
                        version_number=profile_version,
                        personality={
                            "warmth": 50,
                            "confidence": draft.authority,
                            "expressiveness": 60,
                            "emotional_control": 72 if manifest.pressure != "high_pressure" else 58,
                            "impulsiveness": draft.interruption_tendency,
                            "default_pace": 1.0,
                        },
                        voice_settings={
                            "openai_voice": "cedar" if draft.voice.presentation == "masculine" else "marin",
                            "voice_mode": "adaptive_stock",
                            "adaptive_voice_id": voice_id,
                        },
                    )
                )
                sample_path, sample_data = sample_by_key[draft.key]
                agent = SceneAgent(
                    scene_id=scene.id,
                    character_id=character.id,
                    agent_key=draft.key,
                    name=draft.name,
                    role=draft.role,
                    selected=True,
                    sort_order=index,
                    profile={
                        **draft.model_dump(mode="json"),
                        "compiled_persona": compiled.model_dump(mode="json"),
                    },
                    runtime_state={
                        "mood": "focused",
                        "patience": draft.patience,
                        "authority": draft.authority,
                        "turn_count": 0,
                    },
                    voice_profile={
                        **draft.voice.model_dump(mode="json"),
                        "speech": draft.speech.model_dump(mode="json"),
                        "voice_id": voice_id,
                        "sample_audio_path": sample_path,
                        "sample_data": sample_data,
                    },
                )
                db.add(agent)
                db.flush()
                created_agents[draft.key] = agent
                for fact in compiled.stable_facts:
                    db.add(
                        SceneMemoryRecord(
                            scene_id=scene.id,
                            agent_id=agent.id,
                            layer="canon",
                            visibility="public",
                            content=fact,
                            importance=80,
                        )
                    )
                for fact in draft.private_knowledge:
                    db.add(
                        SceneMemoryRecord(
                            scene_id=scene.id,
                            agent_id=agent.id,
                            layer="canon",
                            visibility="private",
                            content=fact,
                            importance=85,
                        )
                    )

            source_ids: dict[str, uuid.UUID] = {}
            for source in research_packet.get("sources") or []:
                if not isinstance(source, dict):
                    continue
                row = SceneSource(
                    scene_id=scene.id,
                    agent_key=None,
                    title=str(source.get("title") or "Research source")[:500],
                    url=str(source.get("url") or ""),
                    snippet=str(source.get("snippet") or ""),
                    freshness=str(source.get("freshness") or "stable")[:40],
                    source_data=source,
                )
                db.add(row)
                db.flush()
                source_ids[str(source.get("id") or row.id)] = row.id

            opening = prepared_by_key[prepared.opening_character_key]
            opening_agent = created_agents[prepared.opening_character_key]
            opening_sample_path = opening_agent.voice_profile["sample_audio_path"]
            db.add(
                SceneTurn(
                    scene_id=scene.id,
                    speaker_type="agent",
                    speaker_key=opening_agent.agent_key,
                    speaker_name=opening_agent.name,
                    action=prepared.opening_action,
                    text=opening.opening_line,
                    audio_path=opening_sample_path,
                    audio_data=opening_agent.voice_profile.get("sample_data") or {},
                    citations=[],
                    turn_data={"opening": True},
                )
            )
            job.status = "completed"
            job.stage = "ready"
            job.progress = 100
            job.completed_at = utc_now()
            job.job_data = {
                **dict(job.job_data or {}),
                "source_count": len(source_ids),
                "character_count": len(created_agents),
            }
            scene.status = "ready"
            scene.ready_at = utc_now()
            scene.preparation = {
                **dict(scene.preparation or {}),
                "research_started": True,
                "source_count": len(source_ids),
                "character_count": len(created_agents),
                "evidence_summary": prepared.evidence_summary,
                "message": "Scene ready. Enter when you are ready.",
                "error": None,
            }
            db.flush()
            agent_keys = {agent.id: agent.agent_key for agent in created_agents.values()}
            index_records = [
                {
                    "record_id": f"memory:{memory.id}",
                    "scene_id": str(scene.id),
                    "character_key": agent_keys.get(memory.agent_id, ""),
                    "record_type": memory.layer,
                    "content": memory.content,
                    "title": "",
                    "url": "",
                    "freshness": "stable",
                    "importance": memory.importance,
                    "visibility": memory.visibility,
                }
                for memory in db.scalars(
                    select(SceneMemoryRecord).where(SceneMemoryRecord.scene_id == scene.id)
                ).all()
            ]
            index_records.extend(
                {
                    "record_id": f"source:{source.id}",
                    "scene_id": str(scene.id),
                    "character_key": source.agent_key or "",
                    "record_type": "source",
                    "content": source.snippet,
                    "title": source.title,
                    "url": source.url,
                    "freshness": source.freshness,
                    "importance": 65,
                    "visibility": "public",
                }
                for source in db.scalars(
                    select(SceneSource).where(SceneSource.scene_id == scene.id)
                ).all()
            )
            db.commit()
            return index_records

    async def _generate_agent_audio(
        self,
        *,
        scene_id: uuid.UUID,
        character,
        text: str,
        category: str,
    ) -> tuple[str, dict[str, Any]]:
        profile = self._speech_profile(character)
        context = VoiceGenerationContext(
            voice_mode="adaptive_stock",
            speech_profile=profile,
            consent_confirmed=character.voice.consent_confirmed,
            take_strength=0.72,
        )
        instructions = (
            f"Perform as {character.name}, {character.role}. {character.voice.performance}. "
            f"Use {character.speech.dialect or character.speech.accent} delivery with "
            f"{character.speech.code_mixing} code-mixing. Keep sentence flow natural and emotionally responsive."
        )
        generated = await asyncio.to_thread(
            self.voice_provider.generate,
            text,
            self._adaptive_voice_id(character),
            None,
            instructions=instructions,
            context=context,
        )
        stored = await asyncio.to_thread(
            self.storage.store_audio,
            generated.path,
            "worlds",
            str(scene_id),
            "agents",
            character.key,
            category,
        )
        generated.path.unlink(missing_ok=True)
        return stored, {
            "status": "ready",
            "engine_name": generated.engine_name,
            "engine_version": generated.engine_version,
            "duration_seconds": generated.duration_seconds,
            "sample_rate": generated.sample_rate,
            "format": generated.format,
            "fallback_used": False,
        }

    def _set_job_progress(
        self,
        job_id: uuid.UUID,
        *,
        stage: str,
        progress: int,
        data: dict[str, Any] | None = None,
    ) -> None:
        with self.session_factory() as db:
            job = db.get(ScenePreparationJob, job_id)
            if job is None:
                return
            job.stage = stage
            job.progress = progress
            if data:
                job.job_data = {**dict(job.job_data or {}), **data}
            scene = db.get(Scene, job.scene_id)
            if scene is not None:
                scene.preparation = {
                    **dict(scene.preparation or {}),
                    "message": stage.replace("_", " ").capitalize(),
                }
            db.commit()

    def _get_scene(self, db: Session, scene_id: uuid.UUID) -> Scene:
        scene = db.get(Scene, scene_id)
        if scene is None or not scene.raw_prompt:
            raise NotFoundError("Scene was not found")
        return scene

    @staticmethod
    def _check_version(scene: Scene, expected_version: int) -> None:
        if scene.active_manifest_version != expected_version:
            raise ValidationError(
                "This blueprint changed in another request. Reload before continuing.",
                details={"current_version": scene.active_manifest_version},
            )

    @staticmethod
    def _invalidated_components(changed_fields: set[str]) -> list[str]:
        components: set[str] = {"scene_state"}
        if changed_fields & {"scenario_summary", "setting", "stakes", "objective", "ai_characters"}:
            components.update({"research", "personas", "voices", "runtime"})
        if "user_role" in changed_fields:
            components.update({"personas", "runtime"})
        if "pressure" in changed_fields:
            components.update({"behavior", "runtime"})
        return sorted(components)

    @staticmethod
    def _scene_query():
        return select(Scene).options(
            selectinload(Scene.manifest_versions),
            selectinload(Scene.preparation_jobs),
            selectinload(Scene.agents),
            selectinload(Scene.sources),
            selectinload(Scene.turns),
        )

    @staticmethod
    def _job_read(job: ScenePreparationJob) -> ScenePreparationJobRead:
        return ScenePreparationJobRead(
            id=job.id,
            manifest_version=job.manifest_version,
            status=job.status,
            stage=job.stage,
            progress=job.progress,
            job_data=dict(job.job_data or {}),
            error_message=job.error_message,
            created_at=job.created_at,
            started_at=job.started_at,
            completed_at=job.completed_at,
        )

    @staticmethod
    def _turn_read(scene_id: uuid.UUID, turn: SceneTurn) -> SceneTurnRead:
        return SceneTurnRead(
            id=turn.id,
            speaker_type=turn.speaker_type,
            speaker_key=turn.speaker_key,
            speaker_name=turn.speaker_name,
            action=turn.action,
            text=turn.text,
            audio_url=f"/api/worlds/{scene_id}/turns/{turn.id}/audio" if turn.audio_path else None,
            audio_data=dict(turn.audio_data or {}),
            citations=[str(value) for value in (turn.citations or [])],
            turn_data=dict(turn.turn_data or {}),
            created_at=turn.created_at,
        )

    @staticmethod
    def _voice_profile_read(scene_id: uuid.UUID, agent: SceneAgent) -> dict[str, Any]:
        profile = dict(agent.voice_profile or {})
        if profile.get("sample_audio_path"):
            profile["sample_audio_url"] = f"/api/worlds/{scene_id}/agents/{agent.id}/sample"
        profile.pop("sample_audio_path", None)
        return profile

    @staticmethod
    def _adaptive_voice_id(character) -> str:
        presentation = character.voice.presentation
        if presentation == "androgynous":
            presentation = "masculine" if sum(map(ord, character.key)) % 2 else "feminine"
        return f"emotionos:auto:{presentation}"

    @staticmethod
    def _speech_profile(character) -> SpeechProfile:
        language_name = character.speech.language.casefold()
        language = (
            "hinglish-IN"
            if "hinglish" in language_name or "code" in language_name
            else "hi-IN"
            if "hindi" in language_name
            else "en-IN"
        )
        accent_name = character.speech.accent.casefold()
        accent = "british" if "brit" in accent_name else "indian" if "india" in accent_name else "neutral"
        return SpeechProfile(
            region="GB" if accent == "british" else "IN" if accent == "indian" else "US",
            language=language,
            accent=accent,
            style="conversational",
        )

