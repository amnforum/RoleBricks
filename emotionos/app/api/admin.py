from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from emotionos.app.core.config import get_settings
from emotionos.app.db.session import get_db
from emotionos.app.services.admin_observability import AdminObservabilityService

router = APIRouter()


def require_admin(request: Request) -> str:
    settings = get_settings()
    forwarded_email = request.headers.get("x-forwarded-email", "").strip().casefold()
    local_request = request.client is not None and request.client.host in {
        "127.0.0.1",
        "::1",
        "testclient",
    }
    if not settings.admin_emails and settings.app_env.casefold() in {"development", "test"} and local_request:
        return "local-admin"
    if not settings.admin_emails:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Admin access is not configured.",
        )
    if not forwarded_email or forwarded_email not in settings.admin_emails:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required.")
    return forwarded_email


@router.get("/admin/overview")
def admin_overview(
    request: Request,
    db: Session = Depends(get_db),
    viewer: str = Depends(require_admin),
):
    service = AdminObservabilityService(
        settings=get_settings(),
        voice_provider=request.app.state.voice_provider,
        queue=request.app.state.scene_queue,
    )
    overview = service.overview(db)
    overview["viewer"] = viewer
    return overview
