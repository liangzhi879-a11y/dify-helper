"""Dify Console API 异步客户端封装。

支持三种认证方式（按优先级自动选择）：
1. session cookie：Dify 1.x 自托管版本最常用，从浏览器复制 session_id
2. Bearer token：Dify Cloud 或支持 PAT 的版本
3. 邮箱密码自动登录：传入 email+password，自动登录获取 access_token

base_url 内部拼接 `/console/api` 前缀。超时 30 秒，网络错误与 5xx
服务端错误采用指数退避重试，最多 3 次；4xx 业务错误立即抛出 DifyApiError。
"""
from __future__ import annotations

import asyncio
import os
from typing import Any

import httpx


class DifyApiError(Exception):
    """Dify API 调用异常，携带状态码、错误信息与原始响应载荷。

    Dify 错误响应格式：``{"code": "...", "message": "...", "status": 400}``
    """

    def __init__(self, status_code: int, message: str, payload: Any = None) -> None:
        super().__init__(f"[{status_code}] {message}")
        self.status_code = status_code
        self.message = message
        self.payload = payload

    def __repr__(self) -> str:
        return (
            f"DifyApiError(status_code={self.status_code!r}, "
            f"message={self.message!r}, payload={self.payload!r})"
        )


class DifyClient:
    """Dify Console API 异步客户端。

    认证方式按传入参数自动选择：
    - 传 access_token + csrf_token：Dify 1.x 自托管最常用（从浏览器 cookie 获取）
    - 传 token：用 Authorization: Bearer 头认证（Dify Cloud PAT）
    - 传 session_id：用 Cookie 头认证（旧版 session 模式）
    - 传 email+password：启动时自动登录获取 access_token，并用 refresh_token 续期

    Dify 1.14+ 要求所有请求携带 X-CSRF-Token 头（值与 csrf_token cookie 相同）。
    """

    API_PREFIX = "/console/api"
    TIMEOUT = 30.0
    MAX_RETRIES = 3
    BACKOFF_BASE = 0.5  # 指数退避基数（秒）：0.5, 1, 2 ...

    def __init__(
        self,
        base_url: str,
        token: str | None = None,
        session_id: str | None = None,
        email: str | None = None,
        password: str | None = None,
        csrf_token: str | None = None,
        refresh_token: str | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self._api_base = f"{self.base_url}{self.API_PREFIX}"
        self.token = token
        self.session_id = session_id
        self.email = email
        self.password = password
        self.csrf_token = csrf_token
        self.refresh_token = refresh_token
        self._access_token: str | None = token  # 若传了 token 直接用作 access_token
        self._refresh_token: str | None = refresh_token

        # 构建默认 headers
        self._headers: dict[str, str] = {"Accept": "application/json"}
        # Dify 1.14+ 必须带 X-CSRF-Token 头（双提交 cookie 模式：header + cookie 值相同）
        if csrf_token:
            self._headers["X-CSRF-Token"] = csrf_token
        # 认证：access_token 优先用 Bearer，session_id 用 Cookie
        if token:
            self._headers["Authorization"] = f"Bearer {token}"
            # Dify 1.14+ 双提交 cookie：access_token 和 csrf_token 也要作为 cookie 发送
            cookie_parts = [f"access_token={token}"]
            if csrf_token:
                cookie_parts.append(f"csrf_token={csrf_token}")
            if refresh_token:
                cookie_parts.append(f"refresh_token={refresh_token}")
            self._headers["Cookie"] = "; ".join(cookie_parts)
        elif session_id:
            self._headers["Cookie"] = f"session_id={session_id}"

    async def _ensure_authenticated(self) -> None:
        """若用邮箱密码模式且尚未有 access_token，则自动登录。"""
        if self._access_token or not (self.email and self.password):
            return
        await self._login()

    async def _login(self) -> None:
        """用邮箱密码登录，从 Set-Cookie 头提取 access_token / csrf_token / refresh_token。

        Dify 1.14+ 的登录端点要求密码 base64 编码（明文会返回 "Invalid encrypted data"），
        登录成功后返回 {"result": "success"}，token 通过 Set-Cookie 头下发。
        """
        if not (self.email and self.password):
            raise DifyApiError(401, "login required but no email/password configured")

        login_url = f"{self._api_base}/login"
        # Dify 1.14+ 要求密码 base64 编码
        import base64
        encoded_pw = base64.b64encode(self.password.encode()).decode()
        payload = {
            "email": self.email,
            "password": encoded_pw,
            "language": "zh-Hans",
            "remember_me": True,
        }
        async with httpx.AsyncClient(timeout=self.TIMEOUT) as client:
            resp = await client.post(login_url, json=payload)

        if resp.status_code != 200:
            raise DifyApiError(
                resp.status_code,
                f"Login failed: {resp.text[:200]}",
                resp.json() if resp.headers.get("content-type", "").startswith("application/json") else resp.text,
            )

        # Dify 1.14+ 通过 Set-Cookie 头返回三个 token
        new_access = resp.cookies.get("access_token")
        new_csrf = resp.cookies.get("csrf_token")
        new_refresh = resp.cookies.get("refresh_token")

        if not new_access:
            # 兜底：也检查响应体（旧版 Dify 可能把 token 放 body 里）
            data = resp.json() if resp.headers.get("content-type", "").startswith("application/json") else {}
            new_access = data.get("access_token") or data.get("data", {}).get("access_token")
            new_refresh = data.get("refresh_token") or data.get("data", {}).get("refresh_token")

        if not new_access:
            raise DifyApiError(401, "Login succeeded but no access_token in cookies or body")

        # 更新全部 token 与 headers
        self._access_token = new_access
        if new_csrf:
            self.csrf_token = new_csrf
        if new_refresh:
            self._refresh_token = new_refresh
        self._update_auth_headers()

    async def _refresh_access_token(self) -> None:
        """用 refresh_token 刷新 access_token。

        Dify 1.14+ 的刷新端点为 POST /console/api/refresh-token，
        需要携带 CSRF 头和 cookie（双提交模式）。
        刷新成功后同时更新 Authorization 头和 Cookie 头。
        """
        if not self._refresh_token:
            if self.email and self.password:
                await self._login()
                return
            raise DifyApiError(401, "access_token expired and no refresh_token available")

        url = f"{self._api_base}/refresh-token"
        # 刷新请求也需要 CSRF 头和 cookie（双提交模式）
        refresh_headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
        }
        if self.csrf_token:
            refresh_headers["X-CSRF-Token"] = self.csrf_token
        # cookie 用当前的 access_token + csrf_token + refresh_token
        cookie_parts = []
        if self._access_token:
            cookie_parts.append(f"access_token={self._access_token}")
        if self.csrf_token:
            cookie_parts.append(f"csrf_token={self.csrf_token}")
        cookie_parts.append(f"refresh_token={self._refresh_token}")
        refresh_headers["Cookie"] = "; ".join(cookie_parts)

        async with httpx.AsyncClient(timeout=self.TIMEOUT) as client:
            resp = await client.post(
                url,
                json={"refresh_token": self._refresh_token},
                headers=refresh_headers,
            )
        if resp.status_code == 200:
            data = resp.json()
            new_access = data.get("access_token") or data.get("data", {}).get("access_token")
            new_refresh = data.get("refresh_token") or data.get("data", {}).get("refresh_token")
            if new_access:
                self._access_token = new_access
                if new_refresh:
                    self._refresh_token = new_refresh
                self._update_auth_headers()
                return
        # refresh 失败：若有邮箱密码则回退到重新登录，否则抛出
        if self.email and self.password:
            await self._login()
            return
        raise DifyApiError(
            resp.status_code,
            f"refresh_token invalid or expired: {resp.text[:200]}",
            resp.json() if resp.headers.get("content-type", "").startswith("application/json") else resp.text,
        )

    def _update_auth_headers(self) -> None:
        """token 刷新后，同步更新 Authorization / X-CSRF-Token / Cookie 头（双提交模式）。"""
        if self._access_token:
            self._headers["Authorization"] = f"Bearer {self._access_token}"
            # 更新 X-CSRF-Token 头（值必须与 csrf_token cookie 相同）
            if self.csrf_token:
                self._headers["X-CSRF-Token"] = self.csrf_token
            # 重建 Cookie：access_token + csrf_token + refresh_token
            cookie_parts = [f"access_token={self._access_token}"]
            if self.csrf_token:
                cookie_parts.append(f"csrf_token={self.csrf_token}")
            if self._refresh_token:
                cookie_parts.append(f"refresh_token={self._refresh_token}")
            self._headers["Cookie"] = "; ".join(cookie_parts)

    async def request(self, method: str, path: str, **kwargs: Any) -> Any:
        """底层请求方法，带超时与指数退避重试。

        - 2xx/3xx：返回解析后的 JSON（无内容时返回 None，非 JSON 返回文本）
        - 401：若有 refresh_token 或邮箱密码，自动 refresh/重新登录后重试一次
        - 4xx（非401）：立即抛出 DifyApiError（不重试）
        - 5xx 或 httpx 网络错误：指数退避重试，最多 MAX_RETRIES 次

        环境变量 DIFY_WORKSPACE_ID 非空时，自动注入 ?workspace_id= 给所有请求
        （多 workspace 环境下指定目标 workspace，不影响创建端点，它们以 token 为准）。
        """
        # 邮箱密码模式：确保已登录
        if self.email and self.password:
            await self._ensure_authenticated()

        url = f"{self._api_base}{path}"
        # 允许调用方覆盖默认 headers
        # ★ 修复：保存 caller_headers 到局部变量，401 refresh 后用同一份重建 headers，
        # 否则 kwargs.get("headers") 在第一次 pop 后永远拿空 dict，caller 自定义头丢失
        caller_headers = kwargs.pop("headers", None)
        headers = {**self._headers, **(caller_headers or {})}

        # ★ 新增：多 workspace 支持。环境变量非空时给所有请求追加 ?workspace_id=。
        # 创建端点忽略此参数（后端以 token 隐含 workspace 为准），list/get 端点用来过滤。
        wid = os.getenv("DIFY_WORKSPACE_ID", "").strip()
        if wid:
            params = kwargs.get("params") or {}
            if isinstance(params, dict) and "workspace_id" not in params:
                kwargs["params"] = {**params, "workspace_id": wid}

        attempt = 0
        retried_401 = False
        while True:
            attempt += 1
            try:
                async with httpx.AsyncClient(timeout=self.TIMEOUT) as client:
                    response = await client.request(
                        method, url, headers=headers, **kwargs
                    )
            except httpx.HTTPError as exc:
                # 网络层错误：重试
                if attempt <= self.MAX_RETRIES:
                    await asyncio.sleep(self.BACKOFF_BASE * (2 ** (attempt - 1)))
                    continue
                raise DifyApiError(
                    0,
                    f"network error after {self.MAX_RETRIES} retries: {exc}",
                    None,
                ) from exc

            # 401：若有 refresh_token 或邮箱密码，尝试刷新后重试一次
            # （Dify 1.14+ access_token 有 JWT 有效期，过期后用 refresh_token 续期）
            if response.status_code == 401 and not retried_401:
                can_refresh = bool(self._refresh_token or (self.email and self.password))
                if can_refresh:
                    retried_401 = True
                    try:
                        await self._refresh_access_token()
                        # ★ 修复：用 caller_headers 局部变量（已被 pop），不是 kwargs.get("headers")
                        headers = {**self._headers, **(caller_headers or {})}
                        attempt = 0  # 重置重试计数
                        continue
                    except DifyApiError:
                        pass  # 刷新失败，走正常错误处理

            if response.status_code < 400:
                # 成功
                if response.status_code == 204 or not response.content:
                    return None
                try:
                    return response.json()
                except ValueError:
                    return response.text

            # 解析 Dify 错误响应
            payload = self._safe_json(response)
            message = (
                payload.get("message")
                if isinstance(payload, dict)
                else response.reason_phrase
            ) or response.reason_phrase

            # 5xx 服务端错误：重试
            if 500 <= response.status_code < 600 and attempt <= self.MAX_RETRIES:
                await asyncio.sleep(self.BACKOFF_BASE * (2 ** (attempt - 1)))
                continue

            # 4xx 或重试耗尽：抛出业务异常
            raise DifyApiError(response.status_code, message, payload)

    @staticmethod
    def _safe_json(response: httpx.Response) -> Any:
        try:
            return response.json()
        except ValueError:
            return response.text

    async def get(self, path: str, params: dict | None = None) -> Any:
        return await self.request("GET", path, params=params)

    async def post(self, path: str, json: Any | None = None) -> Any:
        return await self.request("POST", path, json=json)

    async def patch(self, path: str, json: Any | None = None) -> Any:
        return await self.request("PATCH", path, json=json)

    async def delete(self, path: str) -> Any:
        return await self.request("DELETE", path)
