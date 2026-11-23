import json, time
import pytest
from app import security
from app.config import settings
from app.security import (hash_password, verify_password, create_access_token, decode_token,
                          check_secret_key, validate_password_strength, SecretKeyError, _b64)


def test_password_hash_roundtrip():
    stored = hash_password("A-strong-demo-password-123")
    assert stored != "A-strong-demo-password-123"
    assert verify_password("A-strong-demo-password-123", stored)
    assert not verify_password("wrong-password", stored)
    assert not verify_password("x", "garbage")


def test_token_roundtrip():
    payload = decode_token(create_access_token("test-admin", "admin", 3))
    assert payload["sub"] == "test-admin" and payload["role"] == "admin" and payload["ver"] == 3
    assert payload["iss"] == security.TOKEN_ISSUER and "jti" in payload


def test_tampered_and_malformed_tokens_rejected():
    t = create_access_token("u", "staff")
    h, p, s = t.split(".")
    forged = _b64(json.dumps({"sub": "u", "role": "admin", "iss": "exam-monitor", "exp": int(time.time()) + 999}).encode())
    assert decode_token(f"{h}.{forged}.{s}") is None
    assert decode_token("a.b") is None and decode_token("") is None and decode_token("a.b.c") is None


def test_alg_none_token_rejected():
    header = _b64(json.dumps({"alg": "none", "typ": "JWT"}).encode())
    payload = _b64(json.dumps({"sub": "u", "role": "admin", "iss": "exam-monitor", "exp": int(time.time()) + 999}).encode())
    assert decode_token(f"{header}.{payload}.") is None


def test_expired_token_rejected(monkeypatch):
    monkeypatch.setattr(settings, "access_token_minutes", -1)
    assert decode_token(create_access_token("u", "admin")) is None


@pytest.mark.parametrize("key", ["", "short", "REPLACE_WITH_A_LONG_RANDOM_SECRET_BEFORE_DEPLOYMENT",
                                 "development-only-change-this-secret", "a" * 40])
def test_weak_secret_keys_rejected(key):
    assert check_secret_key(key)


def test_strong_secret_accepted():
    assert check_secret_key("Zq8!vN3rT7yW1xKc5Lm0PdHs9GfB2eJu4aQo6RiV") == []


def test_signing_refuses_weak_key(monkeypatch):
    monkeypatch.setattr(settings, "secret_key", "weak")
    with pytest.raises(SecretKeyError):
        create_access_token("u", "admin")


@pytest.mark.parametrize("pw,ok", [("Sturdy-Pass-2026-xyz", True), ("short1", False), ("onlyletterslongenough", False),
                                   ("123456789012345", False), ("ChangeMe123!", False), ("aaaaaaaaaaaa1", False)])
def test_password_policy(pw, ok):
    assert (validate_password_strength(pw) == []) is ok


def test_password_must_not_contain_username():
    assert validate_password_strength("my-admin1-password-77", "admin1")


def test_low_pbkdf2_rounds_refused_outside_test_env(monkeypatch):
    monkeypatch.setattr(settings, "environment", "production")
    with pytest.raises(RuntimeError):
        hash_password("Sturdy-Pass-2026-xyz")
