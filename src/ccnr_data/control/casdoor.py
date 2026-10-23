# Copyright (c) 2026 CCNR
# SPDX-License-Identifier: MIT
"""Casdoor 同步 HTTP 客户端。

只走 REST，不读 Casdoor 数据库。gRPC handler 是同步的，所以这里用 httpx.Client，
而不是 ccnr_adm 里的 AsyncClient。

失败策略：用户缓存 + 熔断。Casdoor 挂了时，已缓存的用户继续用；
冷用户由调用方按 AUTH_FAIL_MODE 决定放行还是拒绝。
"""

from __future__ import annotations

import base64
import json
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import httpx

from ccnr_data.control.settings import ControlSettings

__all__ = [
    "CasdoorClient",
    "CasdoorError",
    "CasdoorUser",
    "DeviceAuthDenied",
    "DeviceAuthError",
    "DeviceAuthExpired",
    "DeviceAuthPending",
    "DeviceAuthSlowDown",
    "DeviceAuthorization",
    "DeviceIdentity",
]

#: 连续失败多少次后熔断；熔断期内直接抛错，不再打 Casdoor。
FAILURE_THRESHOLD = 3
#: 熔断持续时间（秒）。
CIRCUIT_OPEN_SECONDS = 30.0


class CasdoorError(RuntimeError):
    """Casdoor 不可达、鉴权失败或返回不符合预期。"""


class DeviceAuthError(CasdoorError):
    """Device Code 轮询返回的非成功状态。"""


class DeviceAuthPending(DeviceAuthError):
    pass


class DeviceAuthSlowDown(DeviceAuthError):
    pass


class DeviceAuthDenied(DeviceAuthError):
    pass


class DeviceAuthExpired(DeviceAuthError):
    pass


@dataclass(frozen=True, slots=True)
class DeviceAuthorization:
    device_code: str
    user_code: str
    verification_uri: str
    expires_in: int
    interval: int


@dataclass(frozen=True, slots=True)
class DeviceIdentity:
    casdoor_user_id: str
    access_token: str


@dataclass(frozen=True, slots=True)
class CasdoorUser:
    id: str
    name: str
    display_name: str
    email: str
    email_verified: bool
    organization: str
    roles: list[str] = field(default_factory=list)

    @classmethod
    def from_payload(cls, data: dict[str, Any]) -> CasdoorUser:
        roles = [str(item.get("name", "")) for item in data.get("roles") or [] if item.get("name")]
        return cls(
            id=str(data.get("id") or data.get("name") or ""),
            name=str(data.get("name") or ""),
            display_name=str(data.get("displayName") or data.get("name") or ""),
            email=str(data.get("email") or ""),
            email_verified=bool(data.get("emailVerified")),
            organization=str(data.get("owner") or ""),
            roles=roles,
        )


def _jwt_claims(token: str) -> dict[str, Any]:
    """只用于取身份声明；签名已由 TLS 通道与 Casdoor 直连保证，不做本地验签。"""
    parts = token.split(".")
    if len(parts) < 2:
        return {}
    payload = parts[1] + "=" * (-len(parts[1]) % 4)
    try:
        decoded = base64.urlsafe_b64decode(payload.encode("ascii"))
        claims = json.loads(decoded)
    except (ValueError, TypeError):
        return {}
    return claims if isinstance(claims, dict) else {}


class CasdoorClient:
    """线程安全的同步客户端：token 缓存、用户缓存、熔断都在这里。"""

    def __init__(self, settings: ControlSettings) -> None:
        self._settings = settings
        self._lock = threading.Lock()
        self._token: str | None = None
        self._token_deadline = 0.0
        self._users: dict[str, tuple[float, CasdoorUser]] = {}
        self._users_by_id: dict[str, tuple[float, CasdoorUser]] = {}
        self._failures = 0
        self._open_until = 0.0
        self._client = httpx.Client(
            timeout=settings.casdoor_timeout_ms / 1000.0,
            base_url=settings.casdoor_endpoint,
        )

    @property
    def enabled(self) -> bool:
        return self._settings.casdoor_enabled

    def close(self) -> None:
        self._client.close()

    # ------------------------------------------------------------ 公共查询

    def get_user(self, name: str) -> CasdoorUser:
        """按 Casdoor 登录名取用户（带缓存）。"""
        return self._cached(self._users, name, lambda: self._fetch_user(self._user_key(name)))

    def get_user_by_id(self, user_id: str) -> CasdoorUser:
        """按 Casdoor 用户标识取用户。

        规范形态是 `owner/name`（Casdoor `get-user` 的 id）；只给 UUID 时
        回退到用户列表匹配一次，避免历史绑定直接失效。
        """
        return self._cached(self._users_by_id, user_id, lambda: self._resolve_user(user_id))

    def find_user(self, identifier: str) -> CasdoorUser:
        """按用户名或邮箱找用户；邮箱回退到用户列表做不区分大小写匹配。"""
        if "@" not in identifier:
            return self.get_user(identifier)
        target = identifier.lower()
        for user in self._list_users():
            if user.email.lower() == target:
                return user
        raise CasdoorError("没有找到该邮箱对应的 Casdoor 用户")

    # ------------------------------------------------------------ Device Code

    def start_device_authorization(self) -> DeviceAuthorization:
        """向 Casdoor 申请 device code；返回给玩家的是 user_code + 验证地址。"""
        payload = self._request(
            "POST",
            "/api/device-auth",
            data={
                "client_id": self._settings.casdoor_client_id,
                "scope": "openid profile email",
            },
            authenticated=False,
        )
        try:
            return DeviceAuthorization(
                device_code=str(payload["device_code"]),
                user_code=str(payload["user_code"]),
                verification_uri=str(payload["verification_uri"]),
                expires_in=int(payload["expires_in"]),
                interval=max(1, int(payload["interval"])),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise CasdoorError("Casdoor 返回的 device code 不完整") from exc

    def poll_device_token(self, device_code: str) -> DeviceIdentity:
        """轮询一次；pending/slow_down 用异常表达，成功返回身份。"""
        payload = self._request(
            "POST",
            "/api/login/oauth/access_token",
            data={
                "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
                "device_code": device_code,
                "client_id": self._settings.casdoor_client_id,
            },
            authenticated=False,
            allow_error_body=True,
        )
        error = str(payload.get("error") or "")
        if error == "authorization_pending":
            raise DeviceAuthPending("等待玩家在 CCNR Pass 完成登录")
        if error == "slow_down":
            raise DeviceAuthSlowDown("轮询过快")
        if error in ("access_denied", "authorization_denied"):
            raise DeviceAuthDenied("玩家拒绝了本次登录")
        if error == "expired_token":
            raise DeviceAuthExpired("device code 已过期")
        if error:
            raise DeviceAuthError(f"Casdoor device 错误：{error}")
        token = str(payload.get("access_token") or "")
        if not token:
            raise CasdoorError("Casdoor 未返回 access_token")
        claims = _jwt_claims(token)
        owner = str(claims.get("owner") or self._settings.casdoor_organization)
        name = str(claims.get("preferred_username") or claims.get("name") or "")
        casdoor_user_id = f"{owner}/{name}" if name else str(claims.get("sub") or "")
        if not casdoor_user_id:
            raise CasdoorError("device token 里没有可用的用户标识")
        return DeviceIdentity(casdoor_user_id=casdoor_user_id, access_token=token)

    # ------------------------------------------------------------ 内部

    def _cached(
        self,
        cache: dict[str, tuple[float, CasdoorUser]],
        key: str,
        loader: Callable[[], CasdoorUser],
    ) -> CasdoorUser:
        now = time.monotonic()
        with self._lock:
            hit = cache.get(key)
            if hit is not None and hit[0] > now:
                return hit[1]
        user = loader()
        ttl = self._settings.casdoor_cache_ttl_s
        if ttl > 0:
            with self._lock:
                cache[key] = (now + ttl, user)
        return user

    def _ensure_circuit(self) -> None:
        now = time.monotonic()
        with self._lock:
            if self._open_until > now:
                raise CasdoorError("Casdoor 熔断中")

    def _record(self, ok: bool) -> None:
        with self._lock:
            if ok:
                self._failures = 0
                self._open_until = 0.0
                return
            self._failures += 1
            if self._failures >= FAILURE_THRESHOLD:
                self._open_until = time.monotonic() + CIRCUIT_OPEN_SECONDS
                self._failures = 0

    def _access_token(self) -> str:
        now = time.monotonic()
        with self._lock:
            if self._token is not None and now < self._token_deadline:
                return self._token
        payload = self._request(
            "POST",
            "/api/login/oauth/access_token",
            json={
                "grant_type": "client_credentials",
                "client_id": self._settings.casdoor_client_id,
                "client_secret": self._settings.casdoor_client_secret,
            },
            authenticated=False,
        )
        token = str(payload.get("access_token") or "")
        if not token:
            raise CasdoorError("Casdoor 未返回 access_token")
        expires_in = int(payload.get("expires_in") or 3600)
        with self._lock:
            self._token = token
            self._token_deadline = time.monotonic() + max(30, expires_in - 60)
        return token

    def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json: dict[str, Any] | None = None,
        data: dict[str, str] | None = None,
        authenticated: bool = True,
        allow_error_body: bool = False,
    ) -> dict[str, Any]:
        self._ensure_circuit()
        headers: dict[str, str] = {}
        if authenticated:
            headers["Authorization"] = f"Bearer {self._access_token()}"
        try:
            response = self._client.request(
                method, path, params=params, json=json, data=data, headers=headers
            )
        except httpx.HTTPError as exc:
            self._record(False)
            raise CasdoorError(f"Casdoor 请求失败：{exc.__class__.__name__}") from exc
        if response.status_code >= 400:
            # Device Code 的 authorization_pending / slow_down 用 4xx 表达，
            # 它们是正常轮询状态，不能计入熔断。
            if allow_error_body:
                try:
                    body = response.json()
                except ValueError:
                    body = None
                if isinstance(body, dict) and body.get("error"):
                    self._record(True)
                    return body
            self._record(False)
            raise CasdoorError(f"Casdoor 返回 {response.status_code}")
        try:
            payload = response.json()
        except ValueError as exc:
            self._record(False)
            raise CasdoorError("Casdoor 返回的不是 JSON") from exc
        if isinstance(payload, dict) and payload.get("status") == "error":
            self._record(False)
            raise CasdoorError(str(payload.get("msg") or "Casdoor 返回错误"))
        self._record(True)
        return payload if isinstance(payload, dict) else {}

    def _user_key(self, value: str) -> str:
        return value if "/" in value else f"{self._settings.casdoor_organization}/{value}"

    def _resolve_user(self, user_id: str) -> CasdoorUser:
        if "/" in user_id:
            return self._fetch_user(user_id)
        try:
            return self._fetch_user(self._user_key(user_id))
        except CasdoorError:
            for user in self._list_users():
                if user.id == user_id:
                    return user
            raise

    def _fetch_user(self, user_id: str) -> CasdoorUser:
        params: dict[str, Any] = {"id": user_id}
        payload = self._request("GET", "/api/get-user", params=params)
        data = payload.get("data")
        if not isinstance(data, dict):
            raise CasdoorError("Casdoor 没有返回用户")
        return CasdoorUser.from_payload(data)

    def _list_users(self) -> list[CasdoorUser]:
        payload = self._request(
            "GET",
            "/api/get-users",
            params={
                "owner": self._settings.casdoor_organization,
                "pageSize": 1000,
                "p": 1,
            },
        )
        data = payload.get("data")
        if not isinstance(data, list):
            raise CasdoorError("Casdoor 用户列表格式不对")
        return [CasdoorUser.from_payload(item) for item in data if isinstance(item, dict)]
