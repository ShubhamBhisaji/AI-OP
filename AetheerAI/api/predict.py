"""
predict.py — AI prediction, file upload, history, and model-comparison endpoints.

Endpoints
---------
POST /api/predict          run a prediction (text or file reference)
POST /api/upload           upload a file (image / text / csv / pdf)
GET  /api/history          paginated prediction history (auth optional)
GET  /api/history/{id}     single prediction record
DELETE /api/history/{id}   delete a prediction record (owner or admin)
GET  /api/models           list available models + comparison metadata
POST /api/compare          run the same prompt across multiple models and score results
"""

from __future__ import annotations

import io
import mimetypes
import os
import time
import uuid
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from api.auth import get_current_user, get_optional_user
from api.database import ActivityLog, Prediction, UploadedFile, User, get_db

router = APIRouter(tags=["AI Features"])

# ── Storage directory ──────────────────────────────────────────────────────
_UPLOAD_DIR = Path(__file__).resolve().parents[1] / "data" / "uploads"
_UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

# Allowed upload MIME types (security: explicit allowlist)
_ALLOWED_TYPES = {
    "text/plain", "text/csv", "application/json",
    "application/pdf",
    "image/png", "image/jpeg", "image/gif", "image/webp",
}
_MAX_BYTES = 50 * 1024 * 1024  # 50 MB


# ── Request / response schemas ─────────────────────────────────────────────

class PredictRequest(BaseModel):
    prompt:       str  = Field(..., min_length=1, max_length=32_000)
    model:        str  = Field(default="", description="Override model (blank = use server default)")
    provider:     str  = Field(default="", description="Override provider")
    file_id:      int | None = None
    system_prompt: str | None = Field(None, max_length=8_000)
    temperature:  float = Field(default=0.7, ge=0.0, le=2.0)
    max_tokens:   int   = Field(default=1024, ge=1, le=32_000)


class CompareRequest(BaseModel):
    prompt:   str              = Field(..., min_length=1, max_length=32_000)
    models:   list[dict]       = Field(
        ...,
        description='[{"provider":"openai","model":"gpt-4o"}, ...]',
        min_length=2,
        max_length=6,
    )
    system_prompt: str | None  = Field(None, max_length=8_000)
    temperature:   float       = Field(default=0.7, ge=0.0, le=2.0)
    max_tokens:    int         = Field(default=512,  ge=1, le=8_000)


# ── Helpers ────────────────────────────────────────────────────────────────

def _get_kernel():
    """Import lazily to avoid circular imports at module load."""
    from core.aetheerai_kernel import AetheerAiKernel  # type: ignore
    _k = getattr(_get_kernel, "_instance", None)
    if _k is None:
        provider = os.getenv("AI_PROVIDER", "openai")
        model    = os.getenv("AI_MODEL",    "gpt-4o")
        _k = AetheerAiKernel(ai_provider=provider, model=model)
        _get_kernel._instance = _k  # type: ignore[attr-defined]
    return _k


def _confidence_from_logprobs(logprobs: list[float] | None) -> float | None:
    """Convert a list of token log-probabilities to an aggregate confidence score."""
    if not logprobs:
        return None
    import math
    avg_lp = sum(logprobs) / len(logprobs)
    # Map log-prob to [0, 1]: e^avg_lp is the geometric mean token probability
    return round(min(max(math.exp(avg_lp), 0.0), 1.0), 4)


def _run_single(kernel, prompt: str, system_prompt: str | None, provider: str, model: str,
                temperature: float, max_tokens: int) -> tuple[str, float | None, int, float | None, int]:
    """Return (result, confidence, latency_ms, cost_usd, tokens)."""
    messages = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": prompt})

    t0 = time.monotonic()

    # Switch provider/model if requested
    original = (kernel.ai_adapter.provider, kernel.ai_adapter.model)
    switched = False
    if provider and model and (provider, model) != original:
        try:
            kernel.ai_adapter.switch(provider, model)
            switched = True
        except Exception:
            pass

    try:
        result = kernel.ai_adapter.chat(messages)
        # Attempt to extract usage metadata if available
        tokens: int = 0
        cost_usd: float | None = None
        confidence: float | None = None
        if hasattr(kernel.ai_adapter, "last_usage"):
            usage = kernel.ai_adapter.last_usage or {}
            tokens = usage.get("total_tokens", 0)
            cost_usd = usage.get("cost_usd")
            confidence = usage.get("confidence") or _confidence_from_logprobs(usage.get("logprobs"))
    finally:
        if switched:
            kernel.ai_adapter.switch(original[0], original[1])

    latency_ms = int((time.monotonic() - t0) * 1000)
    return result, confidence, latency_ms, cost_usd, tokens


def _log_activity(db: Session, user_id: int | None, action: str, detail: dict, request: Request):
    forwarded = request.headers.get("X-Forwarded-For")
    ip = forwarded.split(",")[0].strip() if forwarded else (
        request.client.host if request.client else None
    )
    db.add(ActivityLog(user_id=user_id, action=action, detail=detail, ip_address=ip))
    db.commit()


# ── Routes ─────────────────────────────────────────────────────────────────

@router.post("/api/predict")
def predict(
    req:          PredictRequest,
    request:      Request,
    db:           Session      = Depends(get_db),
    current_user: User | None  = Depends(get_optional_user),
):
    kernel   = _get_kernel()
    provider = req.provider or os.getenv("AI_PROVIDER", "openai")
    model    = req.model    or os.getenv("AI_MODEL",    "gpt-4o")

    # Resolve uploaded file context
    extra_context = ""
    file_id = req.file_id
    if file_id:
        uf = db.query(UploadedFile).filter(UploadedFile.id == file_id).first()
        if not uf:
            raise HTTPException(status_code=404, detail=f"File {file_id} not found")
        if uf.content_type and uf.content_type.startswith("text"):
            try:
                extra_context = Path(uf.storage_path).read_text(encoding="utf-8", errors="ignore")[:8_000]
            except OSError:
                extra_context = ""

    full_prompt = (extra_context + "\n\n" + req.prompt).strip() if extra_context else req.prompt

    try:
        result, confidence, latency_ms, cost_usd, tokens = _run_single(
            kernel, full_prompt, req.system_prompt, provider, model,
            req.temperature, req.max_tokens,
        )
    except Exception as exc:
        pred = Prediction(
            user_id=current_user.id if current_user else None,
            input_text=req.prompt[:4000], input_file_id=file_id,
            model_used=model, provider=provider, status="failed", error=str(exc),
        )
        db.add(pred); db.commit(); db.refresh(pred)
        raise HTTPException(status_code=502, detail=f"AI provider error: {exc}") from exc

    pred = Prediction(
        user_id       = current_user.id if current_user else None,
        input_text    = req.prompt[:4000],
        input_file_id = file_id,
        model_used    = model,
        provider      = provider,
        result        = result,
        confidence    = confidence,
        tokens_used   = tokens,
        cost_usd      = cost_usd,
        latency_ms    = latency_ms,
        status        = "completed",
    )
    db.add(pred); db.commit(); db.refresh(pred)
    _log_activity(db, pred.user_id, "predict", {"pred_id": pred.id, "model": model}, request)

    return {"success": True, "data": pred.to_dict()}


@router.post("/api/compare")
def compare_models(
    req:          CompareRequest,
    request:      Request,
    db:           Session      = Depends(get_db),
    current_user: User | None  = Depends(get_optional_user),
):
    kernel = _get_kernel()
    alternatives = []
    best_result: str | None = None
    best_conf: float | None = None

    for spec in req.models:
        p = spec.get("provider", os.getenv("AI_PROVIDER", "openai"))
        m = spec.get("model",    os.getenv("AI_MODEL", "gpt-4o"))
        try:
            res, conf, lat, cost, tok = _run_single(
                kernel, req.prompt, req.system_prompt, p, m,
                req.temperature, req.max_tokens,
            )
            entry = {
                "provider": p, "model": m, "result": res,
                "confidence": conf, "latency_ms": lat,
                "cost_usd": cost, "tokens": tok, "status": "ok",
            }
        except Exception as exc:
            entry = {"provider": p, "model": m, "status": "error", "error": str(exc)}

        alternatives.append(entry)

        # Track the highest-confidence result
        c = entry.get("confidence") or 0.0
        if best_conf is None or c > best_conf:
            best_conf   = c
            best_result = entry.get("result")

    # Persist as a single prediction record with alternatives
    pred = Prediction(
        user_id      = current_user.id if current_user else None,
        input_text   = req.prompt[:4000],
        model_used   = "multi-compare",
        provider     = "multi",
        result       = best_result,
        confidence   = best_conf,
        alternatives = alternatives,
        status       = "completed",
    )
    db.add(pred); db.commit(); db.refresh(pred)
    _log_activity(db, pred.user_id, "compare", {"pred_id": pred.id, "models": len(req.models)}, request)

    return {"success": True, "data": pred.to_dict()}


@router.post("/api/upload")
async def upload_file(
    request:      Request,
    file:         UploadFile    = File(...),
    db:           Session       = Depends(get_db),
    current_user: User | None   = Depends(get_optional_user),
):
    # Validate MIME type
    content_type = file.content_type or mimetypes.guess_type(file.filename or "")[0] or ""
    if content_type not in _ALLOWED_TYPES:
        raise HTTPException(
            status_code=415,
            detail=f"Unsupported file type '{content_type}'. "
                   f"Allowed: {sorted(_ALLOWED_TYPES)}",
        )

    # Read with size guard
    data = await file.read(_MAX_BYTES + 1)
    if len(data) > _MAX_BYTES:
        raise HTTPException(status_code=413, detail="File exceeds 50 MB limit")

    # Sanitize filename — strip path components, force safe extension
    safe_name = Path(file.filename or "upload").name
    suffix    = Path(safe_name).suffix.lower()
    uid       = uuid.uuid4().hex
    stored    = _UPLOAD_DIR / f"{uid}{suffix}"
    stored.write_bytes(data)

    uf = UploadedFile(
        user_id      = current_user.id if current_user else None,
        filename     = safe_name,
        content_type = content_type,
        size_bytes   = len(data),
        storage_path = str(stored),
    )
    db.add(uf); db.commit(); db.refresh(uf)
    _log_activity(db, uf.user_id, "upload", {"file_id": uf.id, "name": safe_name}, request)

    return {"success": True, "data": uf.to_dict()}


@router.get("/api/history")
def history(
    db:           Session      = Depends(get_db),
    current_user: User | None  = Depends(get_optional_user),
    page:  int = Query(default=1, ge=1),
    limit: int = Query(default=20, ge=1, le=200),
    model: str | None = Query(default=None),
):
    q = db.query(Prediction).order_by(Prediction.created_at.desc())
    # Non-admins only see their own predictions
    if current_user:
        if not current_user.is_admin:
            q = q.filter(Prediction.user_id == current_user.id)
    else:
        q = q.filter(Prediction.user_id == None)  # noqa: E711  anonymous only
    if model:
        q = q.filter(Prediction.model_used == model)

    total  = q.count()
    offset = (page - 1) * limit
    items  = q.offset(offset).limit(limit).all()

    return {
        "success": True,
        "data": {
            "items":       [p.to_dict() for p in items],
            "total":       total,
            "page":        page,
            "limit":       limit,
            "total_pages": (total + limit - 1) // limit,
        },
    }


@router.get("/api/history/{prediction_id}")
def get_prediction(
    prediction_id: int,
    db:            Session     = Depends(get_db),
    current_user:  User | None = Depends(get_optional_user),
):
    pred = db.query(Prediction).filter(Prediction.id == prediction_id).first()
    if not pred:
        raise HTTPException(status_code=404, detail="Prediction not found")
    if current_user and not current_user.is_admin and pred.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Access denied")
    return {"success": True, "data": pred.to_dict()}


@router.delete("/api/history/{prediction_id}")
def delete_prediction(
    prediction_id: int,
    db:            Session     = Depends(get_db),
    current_user:  User | None = Depends(get_optional_user),
):
    pred = db.query(Prediction).filter(Prediction.id == prediction_id).first()
    if not pred:
        raise HTTPException(status_code=404, detail="Prediction not found")
    if current_user and not current_user.is_admin and pred.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Access denied")
    db.delete(pred); db.commit()
    return {"success": True, "message": f"Prediction {prediction_id} deleted"}


@router.get("/api/models")
def list_models():
    """Return available models and providers known to the system."""
    models = [
        {"provider": "openai",     "model": "gpt-4o",              "tier": "flagship",   "context_k": 128},
        {"provider": "openai",     "model": "gpt-4o-mini",         "tier": "fast",       "context_k": 128},
        {"provider": "openai",     "model": "gpt-4-turbo",         "tier": "powerful",   "context_k": 128},
        {"provider": "anthropic",  "model": "claude-3-5-sonnet-20241022", "tier": "flagship", "context_k": 200},
        {"provider": "anthropic",  "model": "claude-3-haiku-20240307",   "tier": "fast",     "context_k": 200},
        {"provider": "google",     "model": "gemini-1.5-pro",      "tier": "flagship",   "context_k": 1000},
        {"provider": "google",     "model": "gemini-1.5-flash",    "tier": "fast",       "context_k": 1000},
        {"provider": "ollama",     "model": "llama3.2:1b",         "tier": "local",      "context_k": 128},
        {"provider": "ollama",     "model": "llama3.2:3b",         "tier": "local",      "context_k": 128},
        {"provider": "ollama",     "model": "mistral:7b",          "tier": "local",      "context_k": 32},
    ]
    return {"success": True, "data": models}


@router.get("/api/insights")
def insights(
    db:           Session      = Depends(get_db),
    current_user: User | None  = Depends(get_optional_user),
):
    """Aggregate statistics for the dashboard graphs."""
    q = db.query(Prediction)
    if current_user and not current_user.is_admin:
        q = q.filter(Prediction.user_id == current_user.id)

    preds = q.all()
    total = len(preds)
    if total == 0:
        return {"success": True, "data": {
            "total": 0, "by_model": {}, "by_status": {},
            "avg_confidence": None, "avg_latency_ms": None,
            "daily_counts": [], "confidence_distribution": [],
        }}

    # By-model breakdown
    by_model: dict[str, int] = {}
    by_status: dict[str, int] = {}
    confidences: list[float]  = []
    latencies:   list[int]    = []
    daily: dict[str, int]     = {}

    for p in preds:
        key = f"{p.provider}/{p.model_used}"
        by_model[key]   = by_model.get(key, 0) + 1
        by_status[p.status] = by_status.get(p.status, 0) + 1
        if p.confidence is not None:
            confidences.append(p.confidence)
        if p.latency_ms is not None:
            latencies.append(p.latency_ms)
        if p.created_at:
            day = p.created_at.strftime("%Y-%m-%d")
            daily[day] = daily.get(day, 0) + 1

    daily_sorted = [{"date": k, "count": v} for k, v in sorted(daily.items())]

    # Confidence histogram buckets 0-10%, 10-20%, … 90-100%
    conf_buckets = [0] * 10
    for c in confidences:
        idx = min(int(c * 10), 9)
        conf_buckets[idx] += 1
    conf_dist = [
        {"bucket": f"{i*10}-{(i+1)*10}%", "count": conf_buckets[i]}
        for i in range(10)
    ]

    return {"success": True, "data": {
        "total":                total,
        "by_model":             by_model,
        "by_status":            by_status,
        "avg_confidence":       round(sum(confidences) / len(confidences), 4) if confidences else None,
        "avg_latency_ms":       round(sum(latencies)   / len(latencies))      if latencies   else None,
        "daily_counts":         daily_sorted,
        "confidence_distribution": conf_dist,
    }}
