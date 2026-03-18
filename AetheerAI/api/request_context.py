"""Per-request user context helpers for middleware and DB hooks."""

from __future__ import annotations

from contextvars import ContextVar, Token

_request_user_id: ContextVar[int | None] = ContextVar("aetheer_request_user_id", default=None)
_request_username: ContextVar[str | None] = ContextVar("aetheer_request_username", default=None)


def set_request_user(user_id: int | None, username: str | None) -> tuple[Token, Token]:
    token_id = _request_user_id.set(int(user_id) if user_id is not None else None)
    token_name = _request_username.set(str(username) if username is not None else None)
    return token_id, token_name


def reset_request_user(tokens: tuple[Token, Token]) -> None:
    token_id, token_name = tokens
    _request_user_id.reset(token_id)
    _request_username.reset(token_name)


def get_request_user_id() -> int | None:
    return _request_user_id.get()


def get_request_username() -> str | None:
    return _request_username.get()
