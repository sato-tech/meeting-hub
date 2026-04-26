"""AuthProvider のテスト。"""
from __future__ import annotations

import pytest

from web.auth import (
    BasicAuthProvider,
    GoogleSSOProvider,
    NoAuthProvider,
    _parse_users_env,
    create_default_provider,
)


def test_no_auth_always_admin() -> None:
    p = NoAuthProvider()
    u = p.authenticate({"name": "anyone"})
    assert u is not None
    assert u.is_admin


def test_no_auth_default_name() -> None:
    u = NoAuthProvider().authenticate({})
    assert u is not None
    assert u.name == "local"


def test_parse_users_env() -> None:
    parsed = _parse_users_env("alice:pw1:admin,bob:pw2:user,carol:pw3")
    assert parsed["alice"] == ("pw1", "admin")
    assert parsed["bob"] == ("pw2", "user")
    assert parsed["carol"] == ("pw3", "user")  # role 省略 → user


def test_basic_auth_success_and_failure() -> None:
    p = BasicAuthProvider(users_env="alice:secret:admin,bob:guest:user")
    u = p.authenticate({"name": "alice", "password": "secret"})
    assert u is not None
    assert u.is_admin
    u2 = p.authenticate({"name": "alice", "password": "wrong"})
    assert u2 is None
    u3 = p.authenticate({"name": "nobody", "password": "secret"})
    assert u3 is None


def test_basic_auth_require_raises() -> None:
    p = BasicAuthProvider(users_env="x:y:user")
    with pytest.raises(PermissionError):
        p.require({"name": "x", "password": "bad"})


def test_basic_auth_registered_users() -> None:
    p = BasicAuthProvider(users_env="alice:pw1:admin,bob:pw2")
    assert set(p.registered_users) == {"alice", "bob"}


def test_google_sso_without_id_token_returns_none() -> None:
    p = GoogleSSOProvider(allowed_domains=["example.com"])
    assert p.authenticate({}) is None


def test_create_default_provider_noauth(monkeypatch) -> None:
    monkeypatch.delenv("AUTH_MODE", raising=False)
    assert isinstance(create_default_provider(), NoAuthProvider)


def test_create_default_provider_basic(monkeypatch) -> None:
    monkeypatch.setenv("AUTH_MODE", "basic")
    monkeypatch.setenv("AUTH_USERS", "alice:pw:admin")
    assert isinstance(create_default_provider(), BasicAuthProvider)


def test_create_default_provider_google(monkeypatch) -> None:
    monkeypatch.setenv("AUTH_MODE", "google")
    monkeypatch.setenv("AUTH_GOOGLE_DOMAINS", "example.com,sample.org")
    p = create_default_provider()
    assert isinstance(p, GoogleSSOProvider)
    assert p.allowed_domains == ["example.com", "sample.org"]
