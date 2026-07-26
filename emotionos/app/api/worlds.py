from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query, Request, status
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from emotionos.app.db.session import get_db
from emotionos.app.domain.scene_manifest import (
    SceneBlueprintPatch,
    SceneBuildQueued,
    SceneConfirmRequest,
    SceneDraftCreate,
    SceneRevertRequest,
    SceneTurnCreate,
    WorldSceneRead,
)
from emotionos.app.services.scene_world_service import SceneWorldService

router = APIRouter()


def world_service(request: Request) -> SceneWorldService:
    return request.app.state.scene_world_service


@router.post("/worlds/draft", response_model=WorldSceneRead, status_code=status.HTTP_201_CREATED)
async def create_scene_draft(
    payload: SceneDraftCreate,
    db: Session = Depends(get_db),
    service: SceneWorldService = Depends(world_service),
):
    return await service.create_draft(db, payload)


@router.get("/worlds", response_model=list[WorldSceneRead])
def list_worlds(
    limit: int = Query(default=20, ge=1, le=50),
    db: Session = Depends(get_db),
    service: SceneWorldService = Depends(world_service),
):
    return service.list_scenes(db, limit=limit)


@router.get("/worlds/{scene_id}", response_model=WorldSceneRead)
def get_world(
    scene_id: uuid.UUID,
    db: Session = Depends(get_db),
    service: SceneWorldService = Depends(world_service),
):
    return service.read_scene(db, scene_id)


@router.patch("/worlds/{scene_id}/blueprint", response_model=WorldSceneRead)
def update_blueprint(
    scene_id: uuid.UUID,
    payload: SceneBlueprintPatch,
    db: Session = Depends(get_db),
    service: SceneWorldService = Depends(world_service),
):
    return service.patch_blueprint(db, scene_id, payload)


@router.post("/worlds/{scene_id}/revert", response_model=WorldSceneRead)
def revert_blueprint(
    scene_id: uuid.UUID,
    payload: SceneRevertRequest,
    db: Session = Depends(get_db),
    service: SceneWorldService = Depends(world_service),
):
    return service.revert_blueprint(db, scene_id, payload)


@router.post(
    "/worlds/{scene_id}/confirm",
    response_model=SceneBuildQueued,
    status_code=status.HTTP_202_ACCEPTED,
)
async def confirm_blueprint(
    scene_id: uuid.UUID,
    payload: SceneConfirmRequest,
    db: Session = Depends(get_db),
    service: SceneWorldService = Depends(world_service),
):
    queued = service.confirm(db, scene_id, expected_version=payload.expected_version)
    await service.enqueue(queued.job_id)
    return queued


@router.post("/worlds/{scene_id}/enter", response_model=WorldSceneRead)
def enter_scene(
    scene_id: uuid.UUID,
    db: Session = Depends(get_db),
    service: SceneWorldService = Depends(world_service),
):
    return service.enter(db, scene_id)


@router.post("/worlds/{scene_id}/pause", response_model=WorldSceneRead)
def pause_scene(
    scene_id: uuid.UUID,
    db: Session = Depends(get_db),
    service: SceneWorldService = Depends(world_service),
):
    return service.pause(db, scene_id)


@router.post("/worlds/{scene_id}/resume", response_model=WorldSceneRead)
def resume_scene(
    scene_id: uuid.UUID,
    db: Session = Depends(get_db),
    service: SceneWorldService = Depends(world_service),
):
    return service.resume(db, scene_id)


@router.post("/worlds/{scene_id}/complete", response_model=WorldSceneRead)
async def complete_scene(
    scene_id: uuid.UUID,
    db: Session = Depends(get_db),
    service: SceneWorldService = Depends(world_service),
):
    return await service.complete(db, scene_id)


@router.post("/worlds/{scene_id}/turns", response_model=WorldSceneRead)
async def add_scene_turn(
    scene_id: uuid.UUID,
    payload: SceneTurnCreate,
    db: Session = Depends(get_db),
    service: SceneWorldService = Depends(world_service),
):
    return await service.add_turn(db, scene_id, payload)


@router.get("/worlds/{scene_id}/turns/{turn_id}/audio")
def get_turn_audio(
    scene_id: uuid.UUID,
    turn_id: uuid.UUID,
    db: Session = Depends(get_db),
    service: SceneWorldService = Depends(world_service),
):
    return FileResponse(
        service.audio_path_for_turn(db, scene_id, turn_id),
        media_type="audio/wav",
        filename="emotionos-turn.wav",
    )


@router.get("/worlds/{scene_id}/agents/{agent_id}/sample")
def get_agent_sample(
    scene_id: uuid.UUID,
    agent_id: uuid.UUID,
    db: Session = Depends(get_db),
    service: SceneWorldService = Depends(world_service),
):
    return FileResponse(
        service.sample_path_for_agent(db, scene_id, agent_id),
        media_type="audio/wav",
        filename="emotionos-character-sample.wav",
    )

