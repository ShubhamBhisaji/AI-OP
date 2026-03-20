"""Regression tests for register/login/logout auth flow."""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from api import auth as auth_mod
from api import database as db_mod
from api.database import Base


class _FakeSupabaseClient:
    def __init__(self):
        self.config = SimpleNamespace(auth_url="https://supabase.test/auth/v1")

    def sign_up(self, *, email: str, password: str, metadata=None):
        return {"user": {"id": f"sb-{email}"}}

    def admin_get_user_by_email(self, email: str):
        return {"user": {"id": f"sb-{email}"}}

    def sign_in_with_password(self, *, email: str, password: str):
        return {
            "user": {"id": f"sb-{email}"},
            "access_token": f"supabase-access-{email}",
            "refresh_token": f"supabase-refresh-{email}",
        }

    def _service_headers(self, use_service_role: bool = False):
        return {}

    def _request(self, *args, **kwargs):
        return {"success": True}


@pytest.fixture()
def auth_client(tmp_path, monkeypatch):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'auth.db'}",
        connect_args={"check_same_thread": False},
    )
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    Base.metadata.create_all(bind=engine)

    monkeypatch.setattr(db_mod, "engine", engine)
    monkeypatch.setattr(db_mod, "SessionLocal", SessionLocal)
    monkeypatch.setattr(auth_mod, "SupabaseClient", _FakeSupabaseClient)
    monkeypatch.setattr(auth_mod, "_HAS_JOSE", False)
    monkeypatch.setattr(auth_mod, "_SECRET", "unit-test-secret")
    monkeypatch.setattr(auth_mod, "_sb_count_users", lambda: 0)
    monkeypatch.setattr(auth_mod, "_sb_create_user", lambda **kwargs: {"user": kwargs})
    monkeypatch.setattr(auth_mod, "get_customer_setup_status", lambda user_id: {"requires_setup": False, "configured": True})
    auth_mod._login_attempts.clear()

    app = FastAPI()
    app.include_router(auth_mod.router)
    client = TestClient(app)

    yield client


def test_register_login_logout_revokes_token(auth_client):
    register = auth_client.post(
        "/api/auth/register",
        json={"email": "alice@example.com", "password": "password123"},
    )
    assert register.status_code == 201
    token = register.json()["access_token"]

    me = auth_client.get(
        "/api/auth/me",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert me.status_code == 200
    assert me.json()["data"]["email"] == "alice@example.com"

    logout = auth_client.post(
        "/api/auth/logout",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert logout.status_code == 200

    revoked = auth_client.get(
        "/api/auth/me",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert revoked.status_code == 401
    assert revoked.json()["detail"] == "Token revoked"


def test_login_logout_revokes_token(auth_client):
    register = auth_client.post(
        "/api/auth/register",
        json={"email": "bob@example.com", "password": "password123"},
    )
    assert register.status_code == 201

    login = auth_client.post(
        "/api/auth/login",
        json={"email": "bob@example.com", "password": "password123"},
    )
    assert login.status_code == 200
    payload = login.json()
    token = payload["access_token"]
    assert payload["token_type"] == "bearer"
    assert payload["user"]["email"] == "bob@example.com"

    me = auth_client.get(
        "/api/auth/me",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert me.status_code == 200
    assert me.json()["data"]["email"] == "bob@example.com"

    logout = auth_client.post(
        "/api/auth/logout",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert logout.status_code == 200

    revoked = auth_client.get(
        "/api/auth/me",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert revoked.status_code == 401
    assert revoked.json()["detail"] == "Token revoked"


def test_setup_supabase_missing_platform_tables_returns_clear_hint(auth_client, monkeypatch):
    register = auth_client.post(
        "/api/auth/register",
        json={"email": "carol@example.com", "password": "password123"},
    )
    assert register.status_code == 201
    token = register.json()["access_token"]

    def _raise_missing_table(**kwargs):
        raise auth_mod.APIRequestError(
            "supabase",
            "insert failed for table 'aetheer_customer_supabase_configs'",
            status_code=404,
        )

    monkeypatch.setattr(auth_mod, "save_customer_supabase_config", _raise_missing_table)

    response = auth_client.put(
        "/api/auth/setup/supabase",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "supabase_url": "https://example.supabase.co",
            "supabase_anon_key": "anon-key-value",
            "supabase_service_role_key": "service-role-key-value",
        },
    )

    assert response.status_code == 503
    assert "platform bootstrap tables" in response.json()["detail"]


def test_me_recovers_local_user_when_cache_is_wiped(auth_client, monkeypatch):
    register = auth_client.post(
        "/api/auth/register",
        json={"email": "dave@example.com", "password": "password123"},
    )
    assert register.status_code == 201
    token = register.json()["access_token"]

    # Simulate serverless cold-start cache loss.
    db = db_mod.SessionLocal()
    try:
        db.query(db_mod.User).delete()
        db.commit()
    finally:
        db.close()

    # Simulate Supabase profile-table lookup failure so token-claim fallback is exercised.
    monkeypatch.setattr(auth_mod, "_sb_get_user", lambda **kwargs: None)

    me = auth_client.get(
        "/api/auth/me",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert me.status_code == 200
    assert me.json()["data"]["email"] == "dave@example.com"
