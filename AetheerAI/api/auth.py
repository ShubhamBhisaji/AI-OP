"""
auth.py — JWT authentication router.

Endpoints
---------
POST /api/auth/register   create a new account
POST /api/auth/login      obtain a bearer token
GET  /api/auth/me         current user profile (auth required)
PUT  /api/auth/me         update own password / email
GET  /api/auth/users      list all users (admin only)
DELETE /api/auth/users/{id}  deactivate a user (admin only)
"""

from __future__ import annotations

import base64
import datetime
import hashlib
import hmac
import json
import logging
import os
import secrets
import threading
import time
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy.orm import Session

from api.customer_supabase import (
    get_customer_ai_api_settings,
    get_customer_setup_status,
    get_customer_supabase_config,
    get_customer_supabase_setup_sql,
    get_platform_supabase_setup_sql,
    redact_customer_supabase_config,
    save_customer_ai_api_settings,
    save_customer_supabase_config,
)
from api.database import ActivityLog, User, get_db
from integrations.errors import APIRequestError
from integrations.supabase_client import SupabaseClient

logger = logging.getLogger("aetheer.api.auth")

# ── JWT backend: python-jose (preferred) → stdlib HMAC fallback ────────────
try:
    from jose import JWTError, jwt as _jwt
    _HAS_JOSE = True
except ImportError:  # pragma: no cover
    _HAS_JOSE = False


# ── Password hashing: bcrypt (direct) → PBKDF2 fallback ───────────────────
# Use bcrypt directly to avoid passlib/bcrypt 4.x version-detection bugs.
class _pwd_ctx:
    @staticmethod
    def hash(pw: str) -> str:
        try:
            import bcrypt  # type: ignore
            return bcrypt.hashpw(pw.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")
        except Exception:
            iterations = 210_000
            salt = os.urandom(16)
            digest = hashlib.pbkdf2_hmac("sha256", pw.encode("utf-8"), salt, iterations)
            return f"pbkdf2_sha256${iterations}${salt.hex()}${digest.hex()}"

    @staticmethod
    def verify(pw: str, hashed: str) -> bool:
        try:
            import bcrypt  # type: ignore
            return bcrypt.checkpw(pw.encode("utf-8"), hashed.encode("utf-8"))
        except Exception:
            if hashed.startswith("pbkdf2_sha256$"):
                try:
                    _, iters, salt_hex, digest_hex = hashed.split("$", 3)
                    salt = bytes.fromhex(salt_hex)
                    expected = bytes.fromhex(digest_hex)
                    derived = hashlib.pbkdf2_hmac("sha256", pw.encode("utf-8"), salt, int(iters))
                    return hmac.compare_digest(derived, expected)
                except Exception:
                    return False

            # Legacy fallback compatibility for previously stored hashes.
            legacy = hashlib.sha256(pw.encode()).hexdigest()
            return hmac.compare_digest(legacy, hashed)


# ── Config ─────────────────────────────────────────────────────────────────
_SECRET = (os.getenv("JWT_SECRET") or "").strip()
if not _SECRET:
    # Avoid a static default secret; generate a process-local key if unset.
    _SECRET = secrets.token_urlsafe(48)
    logger.warning("JWT_SECRET not set; generated ephemeral signing key for this process.")

_ALG      = "HS256"
try:
    _EXPIRE_H = max(1, int((os.getenv("JWT_EXPIRE_HOURS") or "24").strip()))
except ValueError:
    _EXPIRE_H = 24

try:
    _LOGIN_WINDOW_SECONDS = max(60, int((os.getenv("AUTH_LOGIN_WINDOW_SECONDS") or "900").strip()))
except ValueError:
    _LOGIN_WINDOW_SECONDS = 900
try:
    _LOGIN_MAX_ATTEMPTS = max(1, int((os.getenv("AUTH_LOGIN_MAX_ATTEMPTS") or "8").strip()))
except ValueError:
    _LOGIN_MAX_ATTEMPTS = 8
_login_attempts_lock = threading.Lock()
_login_attempts: dict[str, tuple[int, float]] = {}

router = APIRouter(prefix="/api/auth", tags=["Auth"])
_bearer = HTTPBearer(auto_error=False)


# ── Request / response schemas ─────────────────────────────────────────────

class RegisterRequest(BaseModel):
    username: str  = Field(..., min_length=3, max_length=64, pattern=r"^[a-zA-Z0-9_\-]+$")
    email:    EmailStr
    password: str  = Field(..., min_length=8, max_length=128)


class LoginRequest(BaseModel):
    username: str = Field(..., min_length=1)
    password: str = Field(..., min_length=1)


class UpdateMeRequest(BaseModel):
    email:        EmailStr | None = None
    new_password: str | None = Field(None, min_length=8, max_length=128)
    old_password: str | None = None


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: dict
    requires_supabase_setup: bool = False
    customer_supabase_configured: bool = False


class CustomerSupabaseSetupRequest(BaseModel):
    supabase_url: str = Field(..., min_length=1, max_length=1024)
    supabase_anon_key: str = Field(..., min_length=8, max_length=4096)
    supabase_service_role_key: str | None = Field(default=None, min_length=8, max_length=4096)
    schema: str = Field(default="public", min_length=1, max_length=120)


class AIAPISettingsRequest(BaseModel):
    provider: str = Field(..., min_length=1, max_length=64)
    model: str | None = Field(default=None, max_length=256)
    api_key: str | None = Field(default=None, max_length=4096)
    base_url: str | None = Field(default=None, max_length=1024)
    extra: dict = Field(default_factory=dict)


# ── Helpers ────────────────────────────────────────────────────────────────

def _make_token(user_id: int, username: str, is_admin: bool) -> str:
    exp = datetime.datetime.utcnow() + datetime.timedelta(hours=_EXPIRE_H)
    if not _HAS_JOSE:
        payload = {
            "sub": str(user_id),
            "un": username,
            "adm": is_admin,
            "exp": int(exp.timestamp()),
        }
        payload_part = base64.urlsafe_b64encode(
            json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
        ).decode("utf-8").rstrip("=")
        signature = hmac.new(_SECRET.encode("utf-8"), payload_part.encode("utf-8"), hashlib.sha256).digest()
        sig_part = base64.urlsafe_b64encode(signature).decode("utf-8").rstrip("=")
        return f"{payload_part}.{sig_part}"

    return _jwt.encode(
        {"sub": str(user_id), "un": username, "adm": is_admin, "exp": exp},
        _SECRET,
        algorithm=_ALG,
    )


def _decode_token(token: str) -> dict:
    if not _HAS_JOSE:
        try:
            payload_part, sig_part = token.split(".", 1)
        except ValueError as exc:
            raise HTTPException(status_code=401, detail="Invalid token") from exc

        expected_sig = hmac.new(
            _SECRET.encode("utf-8"), payload_part.encode("utf-8"), hashlib.sha256
        ).digest()
        expected_sig_part = base64.urlsafe_b64encode(expected_sig).decode("utf-8").rstrip("=")
        if not hmac.compare_digest(sig_part, expected_sig_part):
            raise HTTPException(status_code=401, detail="Invalid token")

        try:
            padded = payload_part + "=" * (-len(payload_part) % 4)
            payload = json.loads(base64.urlsafe_b64decode(padded.encode("utf-8")).decode("utf-8"))
        except Exception:
            raise HTTPException(status_code=401, detail="Invalid token")

        try:
            exp = float(payload.get("exp", 0))
        except Exception as exc:
            raise HTTPException(status_code=401, detail="Invalid token") from exc
        if exp <= time.time():
            raise HTTPException(status_code=401, detail="Invalid or expired token")

        return payload

    try:
        return _jwt.decode(token, _SECRET, algorithms=[_ALG])
    except JWTError as exc:
        raise HTTPException(status_code=401, detail="Invalid or expired token") from exc


def _log(db: Session, user_id: int | None, action: str, detail: dict | None, ip: str | None):
    db.add(ActivityLog(user_id=user_id, action=action, detail=detail, ip_address=ip))
    db.commit()


def _ip(request: Request) -> str | None:
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else None


def _login_attempt_key(username: str, ip_addr: str | None) -> str:
    return f"{(username or '').strip().lower()}|{ip_addr or 'unknown'}"


def _consume_login_attempt(username: str, ip_addr: str | None) -> tuple[bool, int]:
    now = time.time()
    key = _login_attempt_key(username, ip_addr)

    with _login_attempts_lock:
        attempts, started = _login_attempts.get(key, (0, now))
        if now - started >= _LOGIN_WINDOW_SECONDS:
            attempts, started = 0, now

        if attempts >= _LOGIN_MAX_ATTEMPTS:
            retry_after = int(max(1, _LOGIN_WINDOW_SECONDS - (now - started)))
            return False, retry_after

        _login_attempts[key] = (attempts + 1, started)
        return True, 0


def _reset_login_attempts(username: str, ip_addr: str | None) -> None:
    key = _login_attempt_key(username, ip_addr)
    with _login_attempts_lock:
        _login_attempts.pop(key, None)


# ── Auth dependency ────────────────────────────────────────────────────────

def get_current_user(
    creds: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
    db:    Annotated[Session, Depends(get_db)],
) -> User:
    """Dependency: decode bearer token and return the User row."""
    if creds is None:
        raise HTTPException(status_code=401, detail="Authentication required")
    payload = _decode_token(creds.credentials)
    user_id = int(payload.get("sub", 0))
    user = db.query(User).filter(User.id == user_id, User.is_active == True).first()
    if user is None:
        raise HTTPException(status_code=401, detail="User not found or inactive")
    return user


def authenticate_bearer_token(token: str, db: Session) -> User:
    """Resolve an active user from a raw bearer token string."""
    payload = _decode_token(str(token or "").strip())
    user_id = int(payload.get("sub", 0))
    user = db.query(User).filter(User.id == user_id, User.is_active == True).first()
    if user is None:
        raise HTTPException(status_code=401, detail="User not found or inactive")
    return user


def resolve_bearer_user_from_request(request: Request, db: Session) -> User:
    """Resolve a bearer user from Authorization header in an HTTP request."""
    auth_header = (request.headers.get("Authorization") or "").strip()
    if not auth_header:
        raise HTTPException(status_code=401, detail="Login required")

    if not auth_header.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Bearer token required")

    token = auth_header[7:].strip()
    if not token:
        raise HTTPException(status_code=401, detail="Bearer token required")
    return authenticate_bearer_token(token, db)


def get_optional_user(
    creds: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
    db:    Annotated[Session, Depends(get_db)],
) -> User | None:
    """Dependency: return User or None (for optional auth endpoints)."""
    if creds is None:
        return None
    try:
        return get_current_user(creds, db)
    except HTTPException:
        return None


def require_admin(current_user: Annotated[User, Depends(get_current_user)]) -> User:
    if not current_user.is_admin:
        raise HTTPException(status_code=403, detail="Admin access required")
    return current_user


# ── Routes ─────────────────────────────────────────────────────────────────

@router.post("/register", response_model=TokenResponse, status_code=201)
def register(req: RegisterRequest, request: Request, db: Session = Depends(get_db)):
    try:
        # Check if user already exists
        if db.query(User).filter(
            (User.username == req.username) | (User.email == req.email)
        ).first():
            raise HTTPException(status_code=409, detail="Username or email already in use")

        # Use Supabase Auth for registration
        supabase = SupabaseClient()
        
        # Check if first user (for admin role)
        is_first = db.query(User).count() == 0
        role = "admin" if is_first else "user"
        
        # Register with Supabase
        supabase_user = supabase.sign_up(
            email=req.email,
            password=req.password,
            metadata={"username": req.username, "role": role}
        )
        
        # Create local user record
        user = User(
            supabase_user_id=supabase_user["user"]["id"],  # Store Supabase UUID
            username=req.username,
            email=req.email,
            hashed_pw="",  # Not used with Supabase Auth
            is_admin=is_first,
        )
        db.add(user)
        db.commit()
        db.refresh(user)

        _log(db, user.id, "register", {"username": user.username, "supabase_id": supabase_user["user"]["id"]}, _ip(request))
        
        # Generate local JWT token
        token = _make_token(user.id, user.username, user.is_admin)
        
        return TokenResponse(access_token=token, user=user.to_dict())
        
    except APIRequestError as e:
        logger.error(f"Supabase registration error: {e}")
        if e.status_code == 429:
            raise HTTPException(status_code=429, detail="Sign-up rate limit exceeded (Supabase). Please try again later.")
        # Pass through the error detail from supabase (e.g. password too weak)
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Registration failed: {e}")
        raise HTTPException(status_code=400, detail="Registration failed")


@router.post("/login", response_model=TokenResponse)
def login(req: LoginRequest, request: Request, db: Session = Depends(get_db)):
    try:
        # Find user by username or email
        user = db.query(User).filter(
            (User.username == req.username) | (User.email == req.username),
            User.is_active == True
        ).first()
        
        if not user:
            raise HTTPException(status_code=401, detail="Invalid credentials")
        
        # Handle legacy users without Supabase ID
        if not user.supabase_user_id:
            # For legacy users, use local password verification
            if not _pwd_ctx.verify(req.password, user.hashed_pw):
                raise HTTPException(status_code=401, detail="Invalid credentials")
            
            _log(db, user.id, "login", {"username": user.username, "legacy_auth": True}, _ip(request))
            
            # Generate local JWT token
            token = _make_token(user.id, user.username, user.is_admin)
            
            setup_status = get_customer_setup_status(user.id)
            return TokenResponse(
                access_token=token,
                user=user.to_dict(),
                requires_supabase_setup=bool(setup_status.get("requires_setup", False)),
                customer_supabase_configured=bool(setup_status.get("configured", False)),
            )
        
        # Use Supabase Auth for users with Supabase ID
        supabase = SupabaseClient()
        session = supabase.sign_in_with_password(email=user.email, password=req.password)
        
        # Verify the Supabase user matches
        if session["user"]["id"] != user.supabase_user_id:
            raise HTTPException(status_code=401, detail="Invalid credentials")
        
        _log(db, user.id, "login", {"username": user.username, "supabase_id": user.supabase_user_id}, _ip(request))
        
        # Generate local JWT token
        token = _make_token(user.id, user.username, user.is_admin)
        
        setup_status = get_customer_setup_status(user.id)
        return TokenResponse(
            access_token=token,
            user=user.to_dict(),
            requires_supabase_setup=bool(setup_status.get("requires_setup", False)),
            customer_supabase_configured=bool(setup_status.get("configured", False)),
        )
        
    except Exception as e:
        logger.error(f"Login failed: {e}")
        raise HTTPException(status_code=401, detail="Invalid credentials")


@router.get("/me")
def me(current_user: User = Depends(get_current_user)):
    return {"success": True, "data": current_user.to_dict()}


@router.put("/me")
def update_me(
    req:          UpdateMeRequest,
    request:      Request,
    current_user: User    = Depends(get_current_user),
    db:           Session = Depends(get_db),
):
    # Note: Password changes should be handled through Supabase Auth directly
    # This endpoint only handles email changes for now
    
    if req.new_password:
        raise HTTPException(status_code=400, detail="Password changes must be done through Supabase Auth")

    if req.email:
        exists = db.query(User).filter(User.email == req.email, User.id != current_user.id).first()
        if exists:
            raise HTTPException(status_code=409, detail="Email already in use")
        current_user.email = req.email

    db.commit()
    db.refresh(current_user)
    _log(db, current_user.id, "update_profile", {}, _ip(request))
    return {"success": True, "data": current_user.to_dict()}


@router.get("/users")
def list_users(
    admin: User    = Depends(require_admin),
    db:    Session = Depends(get_db),
    skip:  int = 0,
    limit: int = 100,
):
    users = db.query(User).offset(skip).limit(limit).all()
    total = db.query(User).count()
    return {"success": True, "data": {"users": [u.to_dict() for u in users], "total": total}}


@router.delete("/users/{user_id}")
def deactivate_user(
    user_id: int,
    request: Request,
    admin:   User    = Depends(require_admin),
    db:      Session = Depends(get_db),
):
    if user_id == admin.id:
        raise HTTPException(status_code=400, detail="Cannot deactivate your own account")
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    user.is_active = False
    db.commit()
    _log(db, admin.id, "deactivate_user", {"target_id": user_id}, _ip(request))
    return {"success": True, "message": f"User {user_id} deactivated"}


@router.get("/activity")
def activity_logs(
    admin: User    = Depends(require_admin),
    db:    Session = Depends(get_db),
    limit: int = 200,
):
    logs = (
        db.query(ActivityLog)
        .order_by(ActivityLog.created_at.desc())
        .limit(limit)
        .all()
    )
    return {"success": True, "data": [lg.to_dict() for lg in logs]}


@router.get("/setup/status")
def customer_supabase_setup_status(current_user: User = Depends(get_current_user)):
    status_payload = get_customer_setup_status(current_user.id)
    return {
        "success": True,
        "data": {
            **status_payload,
            "customer_sql_required": True,
            "next_step": "Run SQL in customer Supabase, then call PUT /api/auth/setup/supabase.",
        },
    }


@router.get("/setup/sql")
def customer_supabase_sql(current_user: User = Depends(get_current_user)):
    return {
        "success": True,
        "data": {
            "customer_supabase_sql": get_customer_supabase_setup_sql(),
            "platform_supabase_sql": get_platform_supabase_setup_sql(),
            "note": "Run customer_supabase_sql in each customer's Supabase project. Run platform_supabase_sql once in AetheerAI Supabase.",
        },
    }


@router.get("/setup/supabase")
def get_my_customer_supabase_config(current_user: User = Depends(get_current_user)):
    row = get_customer_supabase_config(current_user.id)
    return {"success": True, "data": redact_customer_supabase_config(row)}


@router.put("/setup/supabase")
def upsert_my_customer_supabase_config(
    req: CustomerSupabaseSetupRequest,
    current_user: User = Depends(get_current_user),
):
    try:
        row = save_customer_supabase_config(
            user_id=current_user.id,
            username=current_user.username,
            supabase_url=req.supabase_url,
            supabase_anon_key=req.supabase_anon_key,
            supabase_service_role_key=req.supabase_service_role_key,
            schema=req.schema,
        )
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Failed to save customer Supabase config in AetheerAI Supabase: {exc}",
        ) from exc

    return {
        "success": True,
        "message": "Customer Supabase details saved. Execute the SQL script in the customer project if not already done.",
        "data": redact_customer_supabase_config(row),
    }


@router.get("/settings/ai-api")
def get_my_ai_api_settings(current_user: User = Depends(get_current_user)):
    try:
        row = get_customer_ai_api_settings(user_id=current_user.id, include_secret=False)
    except Exception as exc:
        raise HTTPException(
            status_code=400,
            detail=f"Unable to read AI API settings from customer Supabase: {exc}",
        ) from exc

    return {
        "success": True,
        "data": row,
    }


@router.put("/settings/ai-api")
def update_my_ai_api_settings(
    req: AIAPISettingsRequest,
    current_user: User = Depends(get_current_user),
):
    try:
        row = save_customer_ai_api_settings(
            user_id=current_user.id,
            username=current_user.username,
            provider=req.provider,
            model=req.model,
            api_key=req.api_key,
            base_url=req.base_url,
            extra=req.extra,
        )
    except Exception as exc:
        raise HTTPException(
            status_code=400,
            detail=(
                "Failed to save AI API settings in customer Supabase. "
                f"Ensure the bootstrap SQL was executed. Details: {exc}"
            ),
        ) from exc

    if isinstance(row, dict):
        row = dict(row)
        if "api_key" in row:
            row["api_key"] = "***"

    return {
        "success": True,
        "message": "AI API settings saved in customer Supabase.",
        "data": row,
    }
