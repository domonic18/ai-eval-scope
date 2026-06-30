"""crypto 单元测试 — 对齐 web/backend/src/infra/crypto.ts。"""

from __future__ import annotations

import base64
import hashlib
import hmac

import pytest
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from eval_gateway.auth.crypto import (
    canonical_string,
    decrypt_secret,
    derive_aes_key,
    hmac_verify,
    parse_auth_header,
    sign_hmac,
)


@pytest.fixture
def encryption_key() -> str:
    return "test-encryption-key"


@pytest.fixture
def secret(encryption_key: str) -> str:
    """用 Python 加密一个 secret，模拟 web 端生成的 secretEncrypted。"""
    plain = "sk-eval-deadbeefcafebabe0102030405060708090a0b0c0d0e0f"
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


def test_decrypt_secret(secret: str, encryption_key: str) -> None:
    plain = decrypt_secret(secret, encryption_key)
    assert plain.startswith("sk-eval-")


def test_decrypt_secret_invalid_version() -> None:
    with pytest.raises(ValueError, match="invalid secret ciphertext"):
        decrypt_secret("v2:abc:def:ghi", "key")


def test_canonical_string_empty_body() -> None:
    canonical = canonical_string("POST", "/v1/jobs")
    empty_hash = hashlib.sha256(b"").hexdigest()
    assert canonical == f"POST\n/v1/jobs\n{empty_hash}"


def test_canonical_string_with_body() -> None:
    body = b'{"hello":"world"}'
    canonical = canonical_string("POST", "/v1/jobs", body)
    expected_hash = hashlib.sha256(body).hexdigest()
    assert canonical == f"POST\n/v1/jobs\n{expected_hash}"


def test_sign_hmac() -> None:
    sig = sign_hmac("secret", "POST", "/v1/jobs", b"body")
    canonical = "POST\n/v1/jobs\n" + hashlib.sha256(b"body").hexdigest()
    expected = hmac.new(b"secret", canonical.encode(), hashlib.sha256).hexdigest()
    assert sig == expected


def test_hmac_verify_success() -> None:
    sig = sign_hmac("secret", "GET", "/v1/jobs/123")
    assert hmac_verify("secret", "GET", "/v1/jobs/123", None, sig)


def test_hmac_verify_wrong_secret() -> None:
    sig = sign_hmac("secret", "GET", "/v1/jobs/123")
    assert not hmac_verify("wrong", "GET", "/v1/jobs/123", None, sig)


def test_parse_auth_header_valid() -> None:
    parsed = parse_auth_header("Eval pk-eval-abc:deadbeef")
    assert parsed is not None
    assert parsed.public_key == "pk-eval-abc"
    assert parsed.signature == "deadbeef"


def test_parse_auth_header_uppercase_signature_normalized() -> None:
    parsed = parse_auth_header("Eval pk-eval-abc:DEADBEEF")
    assert parsed is not None
    assert parsed.signature == "deadbeef"


def test_parse_auth_header_invalid() -> None:
    assert parse_auth_header("Bearer token") is None
    assert parse_auth_header(None) is None
    assert parse_auth_header("") is None
