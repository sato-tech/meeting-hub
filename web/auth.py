"""AuthProvider — 認証抽象（Phase 3）。

提供実装:
  - NoAuthProvider: 誰でも admin（local 開発用）
  - BasicAuthProvider: AUTH_USERS env に定義された username:password:role で認証
  - GoogleSSOProvider: スケルトン（Phase 3.5 / Phase 4 以降で本実装）
"""
from __future__ import annotations

import hashlib
import hmac
import logging
import os
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Literal

logger = logging.getLogger(__name__)


Role = Literal["admin", "user"]


@dataclass(frozen=True)
class User:
    id: str
    name: str
    role: Role = "user"

    @property
    def is_admin(self) -> bool:
        return self.role == "admin"


class AuthProvider(ABC):
    @abstractmethod
    def authenticate(self, credentials: dict) -> User | None:
        """credentials dict から User を返す。失敗時は None。"""

    def require(self, credentials: dict) -> User:
        u = self.authenticate(credentials)
        if u is None:
            raise PermissionError("authentication failed")
        return u


class NoAuthProvider(AuthProvider):
    """全員 admin として扱う（localhost 開発用）。"""

    def authenticate(self, credentials: dict) -> User | None:
        name = credentials.get("name") or "local"
        return User(id=f"local:{name}", name=name, role="admin")


def _parse_users_env(raw: str) -> dict[str, tuple[str, Role]]:
    """`alice:pw:admin,bob:pw:user` → {alice: (pw, admin), bob: (pw, user)}"""
    out: dict[str, tuple[str, Role]] = {}
    for part in (raw or "").split(","):
        part = part.strip()
        if not part:
            continue
        fields = part.split(":")
        if len(fields) < 2:
            logger.warning("invalid AUTH_USERS entry: %r", part)
            continue
        name = fields[0].strip()
        pw = fields[1].strip()
        role = (fields[2].strip() if len(fields) >= 3 else "user")
        if role not in ("admin", "user"):
            role = "user"
        out[name] = (pw, role)  # type: ignore[assignment]
    return out


class BasicAuthProvider(AuthProvider):
    """env `AUTH_USERS` のユーザー定義で認証する。

    パスワードは平文比較だが hmac.compare_digest で timing-safe。
    本格運用では bcrypt/scrypt 化を推奨（Phase 3.5）。
    """

    def __init__(self, users_env: str | None = None):
        raw = users_env if users_env is not None else os.environ.get("AUTH_USERS", "")
        self._users = _parse_users_env(raw)

    @property
    def registered_users(self) -> list[str]:
        return list(self._users.keys())

    def authenticate(self, credentials: dict) -> User | None:
        name = credentials.get("name")
        password = credentials.get("password")
        if not name or not password:
            return None
        record = self._users.get(name)
        if not record:
            return None
        stored_pw, role = record
        if not hmac.compare_digest(str(stored_pw), str(password)):
            return None
        return User(id=f"basic:{name}", name=name, role=role)


class GoogleSSOProvider(AuthProvider):
    """Google SSO 用のスケルトン（Phase 3.5 で本実装）。

    期待する credentials:
      {"id_token": "<google id token>"}
    `google-auth` ライブラリで検証し、`hd`（host domain）が期待値なら認証成功。
    """

    def __init__(self, allowed_domains: list[str] | None = None):
        self.allowed_domains = allowed_domains or []

    def authenticate(self, credentials: dict) -> User | None:
        id_token = credentials.get("id_token")
        if not id_token:
            return None
        try:
            from google.oauth2 import id_token as gtok  # type: ignore[import-not-found]
            from google.auth.transport import requests as greq  # type: ignore[import-not-found]
        except ImportError:
            logger.warning("google-auth not installed — GoogleSSOProvider is skeleton")
            return None
        try:
            info = gtok.verify_oauth2_token(id_token, greq.Request())
        except Exception as e:
            logger.warning("google id_token verify failed: %s", e)
            return None
        domain = info.get("hd")
        if self.allowed_domains and domain not in self.allowed_domains:
            return None
        email = info.get("email", "")
        name = info.get("name", email)
        return User(id=f"google:{email}", name=name, role="user")


def create_default_provider() -> AuthProvider:
    """env `AUTH_MODE` に従い AuthProvider を生成する。

    AUTH_MODE = noauth | basic | google
    既定は noauth。
    """
    mode = (os.environ.get("AUTH_MODE") or "noauth").lower()
    if mode == "basic":
        return BasicAuthProvider()
    if mode == "google":
        domains = [d.strip() for d in os.environ.get("AUTH_GOOGLE_DOMAINS", "").split(",") if d.strip()]
        return GoogleSSOProvider(allowed_domains=domains)
    return NoAuthProvider()
