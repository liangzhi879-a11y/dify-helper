"""身份识别层（Dify Helper Bridge v0.3.0 多用户隔离）。

设计目标：内部团队使用，不需要密码，但要稳定识别"谁是谁"。

策略：
- 指纹源 = IP + UA + Accept-Language（HTTP 头，服务端取，油猴无需主动算）
- 算法 = HMAC-SHA256(secret_salt, ip|ua|lang) → hex → uuid5(NAMESPACE_DNS, hex)
- 二次细分 = display_name（油猴 UI 提供，"alice"/"bob-laptop"），维护 display_name_map
- 老油猴（无 X-Bridge-* header）→ 全部归 LEGACY_GLOBAL_USER_ID

安全性：
- HMAC 防外部猜测（看不到 salt 无法爆破）
- 服务端权威：不信任 client 传来的 fingerprint
- internal-team 假设：不做 HTTPS / JWT；防呆不防恶意
"""

from __future__ import annotations

import hashlib
import hmac
import os
import uuid
from dataclasses import dataclass

from fastapi import Depends, Header, HTTPException, Request

from .sqlite_store import SqliteStore, get_store


# ==================== 配置加载 ====================

def _get_salt() -> str:
    """从环境变量加载 fingerprint salt。

    首次部署时生成：
        python -c "import secrets; print(secrets.token_hex(32))" >> bridge/.env
    """
    salt = os.environ.get("BRIDGE_FINGERPRINT_SALT", "")
    if not salt:
        # 警告但不崩（启动后所有用户都是 LEGACY，但 whoami 会报错）
        print(
            "[auth] WARNING: BRIDGE_FINGERPRINT_SALT 未设置。"
            "运行 `python -c \"import secrets; print(secrets.token_hex(32))\"` "
            "生成 64 字符 hex 串写入 .env。"
        )
        return ""
    return salt


def _get_legacy_user_id() -> uuid.UUID:
    """老油猴（无 X-Bridge-* header）的兜底 user_id。"""
    legacy = os.environ.get("BRIDGE_LEGACY_USER_ID", "")
    if not legacy:
        # 默认 fallback UUID（稳定，团队一致即可）
        return uuid.UUID("00000000-0000-0000-0000-000000000000")
    try:
        return uuid.UUID(legacy)
    except ValueError:
        print(f"[auth] WARNING: BRIDGE_LEGACY_USER_ID 非法 UUID: {legacy!r}")
        return uuid.UUID("00000000-0000-0000-0000-000000000000")


def _is_legacy_disabled() -> bool:
    """Phase 4 开关：全员升级油猴 v0.3.0 后设为 true，无 X-Bridge-* header 返 401。

    默认 false（保留 LEGACY 兜底，让老油猴 / 内部调试用 curl 仍能工作）。
    全员升级完成后 flip 为 true 即可。
    """
    return os.environ.get("BRIDGE_LEGACY_DISABLED", "").lower() in ("1", "true", "yes")


# ==================== Fingerprint 算法 ====================


def compute_user_id(ip: str, ua: str, lang: str) -> uuid.UUID:
    """计算 (ip, ua, lang) 对应的稳定 user_id。

    Algorithm:
        digest = HMAC-SHA256(salt, ip|ua|lang)
        return uuid5(NAMESPACE_DNS, digest_hex)

    Why uuid5: 确定性输入 → 确定性输出；同一 (ip, ua, lang) 永远拿到同一 UUID。
    Why HMAC: 外部看到 UUID 也无法反推 ip/ua（不知道 salt）。
    """
    salt = _get_salt()
    if not salt:
        # 无 salt 时退化：所有用户合并到一个固定 UUID
        # 这样不会让 whoami 崩，但所有新用户都看不到区分
        return uuid.UUID("ffffffff-ffff-ffff-ffff-ffffffffffff")
    raw = f"{ip}|{ua[:256]}|{(lang or '')[:32]}"
    digest = hmac.new(salt.encode("utf-8"), raw.encode("utf-8"), hashlib.sha256).hexdigest()
    return uuid.uuid5(uuid.NAMESPACE_DNS, digest)


def compute_fingerprint_hash(ip: str, ua: str, lang: str) -> str:
    """返回 fingerprint 的短哈希（用于 client 缓存校验，不暴露 salt）。"""
    user_id = compute_user_id(ip, ua, lang)
    return user_id.hex[:16]  # 16 字符足够区分


# ==================== Request Context ====================


@dataclass
class UserContext:
    """当前请求的用户身份。注入到所有 endpoint 作为参数。"""

    user_id: uuid.UUID
    fingerprint: str              # short hex（16 chars），用于 client 缓存
    ip: str
    user_agent: str
    accept_language: str
    display_name: str | None
    is_legacy: bool               # True = 老油猴无 fingerprint


def extract_client_info(request: Request) -> tuple[str, str, str]:
    """从 request 提取 (ip, ua, lang)。"""
    # IP：优先 X-Forwarded-For（NAT/代理后），回落到 client.host
    xff = request.headers.get("x-forwarded-for", "")
    ip = xff.split(",")[0].strip() if xff else (request.client.host if request.client else "")
    ua = request.headers.get("user-agent", "")[:256]
    # Accept-Language 首段
    accept_lang = request.headers.get("accept-language", "")
    lang = accept_lang.split(",")[0].strip()[:32] if accept_lang else ""
    return ip, ua, lang


# ==================== FastAPI Dependency ====================


async def get_current_user(
    request: Request,
    x_bridge_fingerprint: str | None = Header(None, alias="X-Bridge-Fingerprint"),
    x_bridge_display_name: str | None = Header(None, alias="X-Bridge-Display-Name"),
    store: SqliteStore = Depends(get_store),
) -> UserContext:
    """从 HTTP 头解析当前 user 的 UserContext。

    处理顺序：
    1. 服务端权威计算 user_id = compute_user_id(ip, ua, lang)
    2. 若有 display_name header → resolve_display_name 二次细分
    3. 若完全无 fingerprint 和 display_name → 兜底 LEGACY_GLOBAL_USER_ID
    4. upsert 到 users 表（记录 first_seen / last_seen）
    5. 返回 UserContext
    """
    ip, ua, lang = extract_client_info(request)
    raw_user_id = compute_user_id(ip, ua, lang)
    fingerprint = compute_fingerprint_hash(ip, ua, lang)

    is_legacy = not x_bridge_fingerprint and not x_bridge_display_name
    display_name = x_bridge_display_name or None

    # Phase 4: 全员升级后禁用 LEGACY 路径
    if is_legacy and _is_legacy_disabled():
        raise HTTPException(
            status_code=401,
            detail=(
                "LEGACY path disabled: 必须带 X-Bridge-Fingerprint 或 "
                "X-Bridge-Display-Name header（升级到油猴 v0.3.0+）"
            ),
        )

    # legacy 兜底
    if is_legacy:
        canonical_id = _get_legacy_user_id()
    elif display_name:
        canonical_id = uuid.UUID(
            await store.resolve_display_name(str(raw_user_id), display_name)
        )
    else:
        canonical_id = raw_user_id

    # upsert（记录 first_seen / last_seen + 触发 stats 计数）
    await store.upsert_user(
        user_id=str(canonical_id),
        ip=ip,
        user_agent=ua,
        display_name=display_name,
        is_legacy=is_legacy,
    )

    return UserContext(
        user_id=canonical_id,
        fingerprint=fingerprint,
        ip=ip,
        user_agent=ua,
        accept_language=lang,
        display_name=display_name,
        is_legacy=is_legacy,
    )