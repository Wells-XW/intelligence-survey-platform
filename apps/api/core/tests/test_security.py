"""Unit tests for JWT and password utilities."""

import time

import pytest
from jose import JWTError

from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    hash_token,
    validate_password,
    verify_password,
)


class TestPasswordHashing:
    def test_hash_and_verify(self):
        pw = "SecurePass1"
        hashed = hash_password(pw)
        assert hashed != pw
        assert verify_password(pw, hashed)

    def test_verify_wrong_password(self):
        hashed = hash_password("Correct1")
        assert not verify_password("WrongPass1", hashed)

    def test_unique_salts(self):
        pw = "SamePassword1"
        h1 = hash_password(pw)
        h2 = hash_password(pw)
        assert h1 != h2  # different salts produce different hashes


class TestPasswordValidation:
    def test_valid_password(self):
        ok, err = validate_password("Abcdefg1")
        assert ok
        assert err is None

    def test_too_short(self):
        ok, err = validate_password("Ab1")
        assert not ok
        assert "8" in err

    def test_no_digit(self):
        ok, err = validate_password("Abcdefgh")
        assert not ok
        assert "数字" in err

    def test_no_letter(self):
        ok, err = validate_password("12345678")
        assert not ok
        assert "字母" in err


class TestJWT:
    USER_ID = "550e8400-e29b-41d4-a716-446655440000"

    def test_access_token_roundtrip(self):
        token = create_access_token(self.USER_ID)
        payload = decode_token(token)
        assert payload["sub"] == self.USER_ID
        assert payload["type"] == "access"

    def test_refresh_token_roundtrip(self):
        token = create_refresh_token(self.USER_ID)
        payload = decode_token(token)
        assert payload["sub"] == self.USER_ID
        assert payload["type"] == "refresh"
        assert "jti" in payload

    def test_access_token_rejected_for_refresh_type_check(self):
        """Tokens must carry the correct 'type' claim for their use case."""
        access = create_access_token(self.USER_ID)
        payload = decode_token(access)
        assert payload["type"] == "access"
        assert payload["type"] != "refresh"

    def test_tampered_token(self):
        token = create_access_token(self.USER_ID)
        tampered = token[:-5] + "aaaaa"
        with pytest.raises(JWTError):
            decode_token(tampered)

    def test_token_hash_deterministic(self):
        t = "some-token-string"
        assert hash_token(t) == hash_token(t)
        assert len(hash_token(t)) == 64  # SHA-256 hex digest

    def test_token_hash_unique(self):
        assert hash_token("token-a") != hash_token("token-b")
