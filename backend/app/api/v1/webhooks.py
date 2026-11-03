"""POST /api/v1/webhooks/github — verify raw-body HMAC first, validate, persist, enqueue, return fast."""
import json

from fastapi import APIRouter, Depends, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.api.deps import settings_dep
from app.core.config import Settings
from app.core.exceptions import AppError, BadRequest, NotConfigured
from app.core.security import verify_github_signature
from app.db.session import get_db
from app.services.webhook_events import EventValidationError
from app.services.webhook_service import handle_delivery

router = APIRouter(prefix="/webhooks", tags=["webhooks"])


class InvalidSignature(AppError):
    status_code, code = 401, "invalid_signature"


@router.post("/github")
async def github_webhook(request: Request, db: Session = Depends(get_db), s: Settings = Depends(settings_dep)):
    if not s.github_webhook_secret:
        raise NotConfigured("GITHUB_WEBHOOK_SECRET is not configured", code="webhook_not_configured")
    raw = await request.body()                       # exact bytes, before any parsing
    if len(raw) > s.max_request_bytes:
        return JSONResponse({"error": {"code": "payload_too_large", "message": "Payload too large"}}, status_code=413)
    if not verify_github_signature(s.github_webhook_secret, raw, request.headers.get("x-hub-signature-256")):
        raise InvalidSignature("Invalid or missing signature")
    event, delivery = request.headers.get("x-github-event"), request.headers.get("x-github-delivery")
    if not event or not delivery or len(delivery) > 64 or len(event) > 60:
        raise BadRequest("Missing or invalid X-GitHub-Event / X-GitHub-Delivery header")
    try:
        payload = json.loads(raw)
    except (ValueError, UnicodeDecodeError):
        raise BadRequest("Body is not valid JSON")
    if not isinstance(payload, dict):
        raise BadRequest("Payload must be a JSON object")
    if event == "ping":
        return {"status": "pong"}
    try:
        outcome, detail = await run_in_threadpool(handle_delivery, db, s, delivery, event, payload)
    except EventValidationError as e:
        raise BadRequest(f"Invalid payload: {e}")
    code = 200 if outcome in ("duplicate", "ignored", "updated") else 202
    return JSONResponse({"status": outcome, "detail": detail}, status_code=code)
