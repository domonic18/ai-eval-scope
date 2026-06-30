"""加密原语 — Python 复刻 web/backend/src/infra/crypto.ts。

- secret 加密态：AES-256-GCM，序列化格式 v1:<iv_b64>:<ct_b64>:<tag_b64>。
- secret 哈希态：sha256(secret)。
- HMAC：canonical = METHOD\nPATH\nsha256(body)，signature = hex(HMAC-SHA256(secret, canonical))。
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import re
from dataclasses import dataclass

from cryptography.hazmat.primitives.ciphers.aead import AESGCM


@dataclass
class ParsedAuthHeader:
    """解析后的 Authorization 头。"""

    scheme: str
    public_key: str
    signature: str


def derive_aes_key(encryption_key_str: str) -> bytes:
    """AES key = SHA256(PLATFORM_KEY_ENCRYPTION_KEY)，32 字节。"""
    return hashlib.sha256(encryption_key_str.encode("utf-8")).digest()


def decrypt_secret(serialized: str, encryption_key_str: str) -> str:
    """解密 api_keys.secret_encrypted → secret 明文。

    对齐 web crypto.ts::decryptSecret：
      iv 12 字节；tag 16 字节；ct 与 tag 独立 base64 编码，解密时 tag 追加在 ct 后。
    """
    parts = str(serialized).split(":")
    if len(parts) != 4 or parts[0] != "v1":
        raise ValueError("invalid secret ciphertext")
    _, iv_b64, ct_b64, tag_b64 = parts

    key = derive_aes_key(encryption_key_str)
    iv = base64.b64decode(iv_b64)
    ciphertext = base64.b64decode(ct_b64)
    tag = base64.b64decode(tag_b64)

    aesgcm = AESGCM(key)
    plaintext = aesgcm.decrypt(iv, ciphertext + tag, None)
    return plaintext.decode("utf-8")


def hash_secret(plain: str) -> str:
    """secret 的 sha256 哈希（hex）。"""
    return hashlib.sha256(plain.encode("utf-8")).hexdigest()


def canonical_string(method: str, path: str, body: bytes | None = None) -> str:
    """canonical = METHOD\nPATH\nsha256(body)。body 为空时 sha256(b"")。"""
    body_hash = hashlib.sha256(body if body is not None else b"").hexdigest()
    return f"{method.upper()}\n{path}\n{body_hash}"


def sign_hmac(secret: str, method: str, path: str, body: bytes | None = None) -> str:
    """hex(HMAC-SHA256(secret, canonical))。"""
    canonical = canonical_string(method, path, body).encode("utf-8")
    return hmac.new(secret.encode("utf-8"), canonical, hashlib.sha256).hexdigest()


def hmac_verify(secret: str, method: str, path: str, body: bytes | None, signature: str) -> bool:
    """常量时间比较签名。"""
    expected = sign_hmac(secret, method, path, body)
    if len(expected) != len(signature) or len(expected) == 0:
        return False
    return hmac.compare_digest(expected, signature)


_AUTH_RE = re.compile(r"^Eval\s+([^:\s]+):([0-9a-f]+)$", re.IGNORECASE)


def parse_auth_header(header: str | None) -> ParsedAuthHeader | None:
    """解析 Authorization: Eval <publicKey>:<signature>，signature 统一转小写。"""
    if not header:
        return None
    match = _AUTH_RE.match(header)
    if not match:
        return None
    return ParsedAuthHeader(
        scheme="Eval",
        public_key=match.group(1),
        signature=match.group(2).lower(),
    )
