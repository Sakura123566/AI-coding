"""注册登录与鉴权：零新依赖实现。

- 密码：`hashlib.pbkdf2_hmac`（SHA256，12 万轮，每用户随机盐），不存明文；
- 令牌：手写 HS256 JWT（base64url + HMAC-SHA256），不装 PyJWT / python-jose；
- 校验签名用 `hmac.compare_digest`，避免计时侧信道。

为什么不用第三方库：主项目的铁律是"依赖只有 fastapi + uvicorn"，
认证这几十行代码自己写反而更可控，也不会给队员3 的部署增加装包失败的风险。
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time
from typing import Any

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from .config import settings
from .db import now_iso, query_one
from .errors import ApiError

PBKDF2_ROUNDS = 120_000
SALT_BYTES = 16

security = HTTPBearer(auto_error=False, description="Bearer <token>")


# ----------------------------- 密码 -----------------------------
def hash_password(password: str, salt_hex: str | None = None) -> tuple[str, str]:
    salt = bytes.fromhex(salt_hex) if salt_hex else secrets.token_bytes(SALT_BYTES)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, PBKDF2_ROUNDS)
    return digest.hex(), salt.hex()


def verify_password(password: str, digest_hex: str, salt_hex: str) -> bool:
    try:
        expect = bytes.fromhex(digest_hex)
        salt = bytes.fromhex(salt_hex)
    except ValueError:
        return False
    actual = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, PBKDF2_ROUNDS)
    return hmac.compare_digest(actual, expect)


def check_password_strength(password: str) -> None:
    if len(password or "") < settings.min_password_len:
        raise ApiError("WEAK_PASSWORD")


# ----------------------------- JWT（HS256，手写） -----------------------------
def _b64url_encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _b64url_decode(text: str) -> bytes:
    padding = "=" * (-len(text) % 4)
    return base64.urlsafe_b64decode(text + padding)


def create_token(user_id: int, ttl_seconds: int | None = None) -> tuple[str, int]:
    """返回 (token, expires_in 秒)。"""
    ttl = int(ttl_seconds if ttl_seconds is not None else settings.auth_token_ttl)
    issued = int(time.time())
    header = {"alg": "HS256", "typ": "JWT"}
    payload: dict[str, Any] = {
        "uid": int(user_id),
        "iat": issued,
        "exp": issued + ttl,
        "jti": secrets.token_hex(8),
    }
    signing_input = f"{_b64url_encode(json.dumps(header, separators=(',', ':')).encode())}." \
                    f"{_b64url_encode(json.dumps(payload, separators=(',', ':')).encode())}"
    signature = hmac.new(
        settings.auth_secret.encode("utf-8"), signing_input.encode("ascii"), hashlib.sha256
    ).digest()
    return f"{signing_input}.{_b64url_encode(signature)}", ttl


def decode_token(token: str) -> dict[str, Any]:
    """校验签名与过期时间；任何不合法都抛 ApiError（401）。"""
    parts = (token or "").split(".")
    if len(parts) != 3:
        raise ApiError("UNAUTHORIZED", http_status=401)
    signing_input = f"{parts[0]}.{parts[1]}"
    try:
        expected = hmac.new(
            settings.auth_secret.encode("utf-8"), signing_input.encode("ascii"), hashlib.sha256
        ).digest()
    except Exception:  # noqa: BLE001 - 签名过程异常一律当作无效 token
        raise ApiError("UNAUTHORIZED", http_status=401)

    if not hmac.compare_digest(_b64url_encode(expected), parts[2]):
        raise ApiError("UNAUTHORIZED", http_status=401)

    try:
        payload = json.loads(_b64url_decode(parts[1]).decode("utf-8"))
    except Exception:  # noqa: BLE001
        raise ApiError("UNAUTHORIZED", http_status=401)

    if int(payload.get("exp", 0)) < int(time.time()):
        raise ApiError("TOKEN_EXPIRED", http_status=401)
    if not payload.get("uid"):
        raise ApiError("UNAUTHORIZED", http_status=401)
    return payload


# ----------------------------- FastAPI 依赖 -----------------------------
def optional_user_id(
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
) -> int | None:
    """没有带 token 就返回 None：老接口（/api/research/run）既能匿名用，也能带上身份落库。"""
    if credentials is None or not credentials.credentials:
        return None
    payload = decode_token(credentials.credentials)
    uid = int(payload["uid"])
    row = query_one("SELECT id FROM users WHERE id = ?", (uid,))
    if row is None:  # 用户被删了，token 立刻失效
        raise ApiError("UNAUTHORIZED", http_status=401)
    return uid


def current_user_id(uid: int | None = Depends(optional_user_id)) -> int:
    if uid is None:
        raise ApiError("UNAUTHORIZED", http_status=401)
    return uid


def touch_login(user_id: int) -> None:
    from .db import execute  # 局部导入：避免模块初始化顺序问题

    execute("UPDATE users SET last_login_at = ? WHERE id = ?", (now_iso(), user_id))
