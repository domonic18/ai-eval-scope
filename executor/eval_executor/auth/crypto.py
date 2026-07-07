"""加密原语 — Python 复刻 web/backend/src/infra/crypto.ts（单一 Bearer token）。

- token 加密态：AES-256-GCM，序列化 v1:<iv_b64>:<ct_b64>:<tag_b64>（executor 回传时解密）。
- token 哈希态：sha256(token)（鉴权查找）。
- Bearer 头解析：Authorization: Bearer <token>。
"""

from __future__ import annotations

import base64
import hashlib
import re

from cryptography.hazmat.primitives.ciphers.aead import AESGCM


def derive_aes_key(encryption_key_str: str) -> bytes:
    """AES key = SHA256(PLATFORM_KEY_ENCRYPTION_KEY)，32 字节。"""
    return hashlib.sha256(encryption_key_str.encode("utf-8")).digest()


def decrypt_token(serialized: str, encryption_key_str: str) -> str:
    """解密 api_keys.token_encrypted → token 明文（executor 回传 web 时用）。

    对齐 web crypto.ts::decryptToken：
      iv 12 字节；tag 16 字节；ct 与 tag 独立 base64 编码，解密时 tag 追加在 ct 后。
    """
    parts = str(serialized).split(":")
    if len(parts) != 4 or parts[0] != "v1":
        raise ValueError("invalid token ciphertext")
    _, iv_b64, ct_b64, tag_b64 = parts

    key = derive_aes_key(encryption_key_str)
    iv = base64.b64decode(iv_b64)
    ciphertext = base64.b64decode(ct_b64)
    tag = base64.b64decode(tag_b64)

    aesgcm = AESGCM(key)
    plaintext = aesgcm.decrypt(iv, ciphertext + tag, None)
    return plaintext.decode("utf-8")


def hash_token(plain: str) -> str:
    """token 的 sha256 哈希（hex）——鉴权查找用。"""
    return hashlib.sha256(plain.encode("utf-8")).hexdigest()


_BEARER_RE = re.compile(r"^Bearer\s+(.+)$", re.IGNORECASE)


def parse_bearer_token(header: str | None) -> str | None:
    """解析 Authorization: Bearer <token> → token | None。"""
    if not header:
        return None
    match = _BEARER_RE.match(header)
    if not match:
        return None
    return match.group(1).strip()
