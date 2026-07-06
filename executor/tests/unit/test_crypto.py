"""crypto 单元测试 — 对齐 web/backend/src/infra/crypto.ts（单一 Bearer token）。"""

from __future__ import annotations

import base64
import hashlib

import pytest
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from eval_executor.auth.crypto import (
    decrypt_token,
    derive_aes_key,
    hash_token,
    parse_bearer_token,
)


@pytest.fixture
def encryption_key() -> str:
    return "test-encryption-key"


@pytest.fixture
def token_ciphertext(encryption_key: str) -> str:
    """用 Python 加密一个 token，模拟 web 端生成的 tokenEncrypted。"""
    plain = "eval-deadbeefcafebabe0102030405060708090a0b0c0d0e0f"
    key = derive_aes_key(encryption_key)
    iv = b"\x00" * 12  # 测试用固定 IV；生产必须随机
    aesgcm = AESGCM(key)
    ct_with_tag = aesgcm.encrypt(iv, plain.encode("utf-8"), None)
    ct = ct_with_tag[:-16]
    tag = ct_with_tag[-16:]
    return f"v1:{base64.b64encode(iv).decode()}:{base64.b64encode(ct).decode()}:{base64.b64encode(tag).decode()}"


def test_derive_aes_key(encryption_key: str) -> None:
    key = derive_aes_key(encryption_key)
    assert len(key) == 32
    assert key == hashlib.sha256(encryption_key.encode("utf-8")).digest()


def test_decrypt_token(token_ciphertext: str, encryption_key: str) -> None:
    plain = decrypt_token(token_ciphertext, encryption_key)
    assert plain.startswith("eval-")


def test_decrypt_token_invalid_version() -> None:
    with pytest.raises(ValueError, match="invalid token ciphertext"):
        decrypt_token("v2:abc:def:ghi", "key")


def test_hash_token() -> None:
    assert hash_token("eval-abc") == hashlib.sha256(b"eval-abc").hexdigest()


def test_parse_bearer_token_valid() -> None:
    assert parse_bearer_token("Bearer eval-deadbeef") == "eval-deadbeef"


def test_parse_bearer_token_case_insensitive_scheme() -> None:
    assert parse_bearer_token("bearer eval-x") == "eval-x"


def test_parse_bearer_token_invalid() -> None:
    assert parse_bearer_token("Eval pk-eval-abc:deadbeef") is None  # 旧 HMAC 格式不再支持
    assert parse_bearer_token(None) is None
    assert parse_bearer_token("") is None
