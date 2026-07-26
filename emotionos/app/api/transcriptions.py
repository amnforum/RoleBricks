from __future__ import annotations

from fastapi import APIRouter, File, Request, UploadFile

from emotionos.app.core.config import get_settings
from emotionos.app.core.exceptions import ValidationError

router = APIRouter()


@router.post("/transcribe")
async def transcribe_audio(request: Request, source_audio: UploadFile = File(...)):
    settings = get_settings()
    max_bytes = settings.max_audio_size_mb * 1024 * 1024
    contents = await source_audio.read(max_bytes + 1)
    if len(contents) > max_bytes:
        raise ValidationError(f"Audio exceeds the {settings.max_audio_size_mb} MB limit")
    transcript = await request.app.state.transcription_service.transcribe(
        filename=source_audio.filename or "voice.webm",
        content_type=source_audio.content_type or "audio/webm",
        contents=contents,
    )
    return {"text": transcript, "model": settings.openai_transcription_model}
