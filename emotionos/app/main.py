from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from emotionos.app.api import admin, transcriptions, worlds
from emotionos.app.audio.storage import StorageManager
from emotionos.app.core.config import get_settings
from emotionos.app.core.exceptions import EmotionOSError
from emotionos.app.core.logging import configure_logging
from emotionos.app.db.session import SessionLocal
from emotionos.app.providers.huggingface_space_provider import HuggingFaceSpaceVoiceProvider
from emotionos.app.providers.mock_provider import MockProvider
from emotionos.app.providers.openai_provider import OpenAIVoiceProvider
from emotionos.app.providers.router import VoiceProviderRouter
from emotionos.app.providers.sarvam_provider import SarvamVoiceProvider
from emotionos.app.services.job_queue import PriorityJobQueue
from emotionos.app.services.openai_transcription_service import OpenAITranscriptionService
from emotionos.app.services.scene_compiler import build_scene_compiler
from emotionos.app.services.scene_research import build_scene_research_provider
from emotionos.app.services.scene_retrieval import build_scene_retriever
from emotionos.app.services.scene_world_service import SceneWorldService
from emotionos.app.services.telemetry import SceneTelemetry

settings = get_settings()
configure_logging(settings.debug)
templates = Jinja2Templates(directory="emotionos/app/templates")


@asynccontextmanager
async def lifespan(app: FastAPI):
    storage = StorageManager(settings.audio_root, volume_root=settings.audio_volume_path)
    if settings.test_mode and settings.use_mock_tts:
        provider = MockProvider()
    else:
        provider = VoiceProviderRouter(
            openai=OpenAIVoiceProvider(settings),
            sarvam=SarvamVoiceProvider(settings),
            space=(
                HuggingFaceSpaceVoiceProvider(settings)
                if settings.hf_space_id.strip()
                else None
            ),
            preferred=settings.voice_provider,
            settings=settings,
        )
    initial_status = provider.load()

    app.state.storage = storage
    app.state.voice_provider = provider
    app.state.provider_notice = initial_status.message
    app.state.transcription_service = OpenAITranscriptionService(settings)

    scene_world = SceneWorldService(
        settings=settings,
        compiler=build_scene_compiler(settings),
        research=build_scene_research_provider(settings),
        retriever=build_scene_retriever(settings),
        telemetry=SceneTelemetry(settings),
        voice_provider=provider,
        storage=storage,
        session_factory=SessionLocal,
    )
    scene_queue = PriorityJobQueue(scene_world.run_job, worker_count=settings.scene_worker_count)
    scene_world.attach_queue(scene_queue)
    app.state.scene_world_service = scene_world
    app.state.scene_queue = scene_queue

    await scene_queue.start()
    await scene_world.recover_pending_jobs()
    try:
        yield
    finally:
        await scene_queue.close()


app = FastAPI(title=settings.app_name, lifespan=lifespan)
app.mount("/static", StaticFiles(directory="emotionos/app/static"), name="static")
app.include_router(worlds.router, prefix="/api", tags=["living scenes"])
app.include_router(transcriptions.router, prefix="/api", tags=["voice input"])
app.include_router(admin.router, prefix="/api", tags=["admin observability"])


@app.exception_handler(EmotionOSError)
async def app_error_handler(request: Request, exc: EmotionOSError):
    if request.url.path.startswith("/api"):
        return JSONResponse(
            status_code=exc.status_code,
            content={"error": exc.message, "details": jsonable_encoder(exc.details)},
        )
    return templates.TemplateResponse(
        request,
        "error.html",
        {"message": exc.message, "details": exc.details},
        status_code=exc.status_code,
    )


@app.exception_handler(RequestValidationError)
async def validation_error_handler(request: Request, exc: RequestValidationError):
    if request.url.path.startswith("/api"):
        return JSONResponse(status_code=422, content={"error": "Invalid request", "details": exc.errors()})
    return templates.TemplateResponse(
        request,
        "error.html",
        {"message": "Invalid request", "details": exc.errors()},
        status_code=422,
    )


@app.get("/health")
def health():
    return {"status": "ok", "app": settings.app_name}


@app.get("/ready")
def ready(request: Request):
    provider = request.app.state.voice_provider
    status = provider.status()
    status_for = getattr(provider, "status_for", None)
    openai_status = status_for("openai") if callable(status_for) else None
    sarvam_status = status_for("sarvam") if callable(status_for) else None
    space_status = status_for("space") if callable(status_for) else None
    return {
        "ready": status.ready,
        "provider": status.provider,
        "engine_version": status.engine_version,
        "message": "Voice routing is operational." if status.ready else "Voice routing needs setup.",
        "openai_configured": settings.openai_configured,
        "sarvam_configured": settings.sarvam_configured,
        "space_configured": bool(settings.hf_space_id.strip() and settings.hf_token.strip()),
        "openai_voice_ready": bool(openai_status and openai_status.ready),
        "sarvam_voice_ready": bool(sarvam_status and sarvam_status.ready),
        "space_voice_ready": bool(space_status and space_status.ready),
        "voice_provider": settings.voice_provider,
        "scene_compiler_provider": settings.scene_compiler_provider,
        "scene_compiler_ready": settings.scene_compiler_provider == "rules" or settings.databricks_configured,
        "scene_research_provider": settings.scene_research_provider,
        "scene_research_ready": settings.scene_research_configured,
        "scene_retrieval_provider": settings.scene_retrieval_provider,
        "scene_retrieval_ready": settings.scene_retrieval_configured,
        "scene_indexing_ready": (
            settings.scene_retrieval_provider == "database"
            or settings.databricks_lakehouse_configured
        ),
        "scene_telemetry_ready": (
            settings.scene_compiler_provider == "rules"
            or bool(settings.mlflow_experiment_id.strip())
        ),
        "database_backend": settings.database_backend,
        "lakebase_ready": settings.database_backend == "local" or settings.lakebase_configured,
        "scene_max_agents": settings.scene_max_agents,
    }


@app.get("/", response_class=HTMLResponse)
def worlds_dashboard(request: Request):
    return templates.TemplateResponse(request, "worlds.html", {"settings": settings})


@app.get("/admin", response_class=HTMLResponse)
def admin_dashboard(
    request: Request,
    viewer: str = Depends(admin.require_admin),
):
    return templates.TemplateResponse(
        request,
        "admin.html",
        {"settings": settings, "viewer": viewer},
    )
