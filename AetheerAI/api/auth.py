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

import datetime
import os
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy.orm import Session

from api.database import ActivityLog, User, get_db

# ── JWT backend: python-jose (preferred) → fallback unsigned token ─────────
try:
    from jose import JWTError, jwt as _jwt
    _HAS_JOSE = True
except ImportError:  # pragma: no cover
    _HAS_JOSE = False


# ── Password hashing: bcrypt (direct) → sha-256 fallback ──────────────────
# Use bcrypt directly to avoid passlib/bcrypt 4.x version-detection bugs.
class _pwd_ctx:
    @staticmethod
    def hash(pw: str) -> str:
        try:
            import bcrypt  # type: ignore
            return bcrypt.hashpw(pw.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")
        except Exception:
            import hashlib
            return hashlib.sha256(pw.encode()).hexdigest()

    @staticmethod
    def verify(pw: str, hashed: str) -> bool:
        try:
            import bcrypt  # type: ignore
            return bcrypt.checkpw(pw.encode("utf-8"), hashed.encode("utf-8"))
        except Exception:
            import hashlib
            return hashlib.sha256(pw.encode()).hexdigest() == hashed


# ── Config ─────────────────────────────────────────────────────────────────
_SECRET   = os.getenv("JWT_SECRET", "change-me-in-production-aetheer-secret-key")
_ALG      = "HS256"
_EXPIRE_H = int(os.getenv("JWT_EXPIRE_HOURS", "24"))

router = APIRouter(prefix="/api/auth", tags=["Auth"])
_bearer = HTTPBearer(auto_error=False)


# ── Request / response schemas ─────────────────────────────────────────────

class RegisterRequest(BaseModel):
    username: str  = Field(..., min_length=3, max_length=64, pattern=r"^[a-zA-Z0-9_\-]+$")
    email:    str  = Field(..., min_length=5, max_length=200)
    password: str  = Field(..., min_length=8, max_length=128)


class LoginRequest(BaseModel):
    username: str = Field(..., min_length=1)
    password: str = Field(..., min_length=1)


class UpdateMeRequest(BaseModel):
    email:        str | None = Field(None, min_length=5, max_length=200)
    new_password: str | None = Field(None, min_length=8, max_length=128)
    old_password: str | None = None


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: dict


# ── Helpers ────────────────────────────────────────────────────────────────

def _make_token(user_id: int, username: str, is_admin: bool) -> str:
    if not _HAS_JOSE:
        # Minimal unsigned token for environments without python-jose
        import base64, json as _json
        payload = {"sub": str(user_id), "un": username, "adm": is_admin}
        return base64.urlsafe_b64encode(_json.dumps(payload).encode()).decode()
    exp = datetime.datetime.utcnow() + datetime.timedelta(hours=_EXPIRE_H)
    return _jwt.encode(
        {"sub": str(user_id), "un": username, "adm": is_admin, "exp": exp},
        _SECRET,
        algorithm=_ALG,
    )


def _decode_token(token: str) -> dict:
    if not _HAS_JOSE:
        import base64, json as _json
        try:
            return _json.loads(base64.urlsafe_b64decode(token + "=="))
        except Exception:
            raise HTTPException(status_code=401, detail="Invalid token")
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
    if db.query(User).filter(
        (User.username == req.username) | (User.email == req.email)
    ).first():
        raise HTTPException(status_code=409, detail="Username or email already in use")

    # First user ever becomes admin
    is_first = db.query(User).count() == 0
    user = User(
        username  = req.username,
        email     = req.email,
        hashed_pw = _pwd_ctx.hash(req.password),
        is_admin  = is_first,
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    _log(db, user.id, "register", {"username": user.username}, _ip(request))
    token = _make_token(user.id, user.username, user.is_admin)
    return TokenResponse(access_token=token, user=user.to_dict())


@router.post("/login", response_model=TokenResponse)
def login(req: LoginRequest, request: Request, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.username == req.username, User.is_active == True).first()
    if not user or not _pwd_ctx.verify(req.password, user.hashed_pw):
        _log(db, None, "login_failed", {"username": req.username}, _ip(request))
        raise HTTPException(status_code=401, detail="Invalid credentials")

    _log(db, user.id, "login", {"username": user.username}, _ip(request))
    token = _make_token(user.id, user.username, user.is_admin)
    return TokenResponse(access_token=token, user=user.to_dict())


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
    if req.new_password:
        if not req.old_password or not _pwd_ctx.verify(req.old_password, current_user.hashed_pw):
            raise HTTPException(status_code=400, detail="Current password is incorrect")
        current_user.hashed_pw = _pwd_ctx.hash(req.new_password)

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
