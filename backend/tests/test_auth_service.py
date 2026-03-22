"""Tests for app.services.auth — password hashing & JWT token handling."""

from datetime import UTC, datetime, timedelta

from jose import jwt

from app.config import settings
from app.services.auth import (
    ALGORITHM,
    _prehash,
    create_access_token,
    decode_token,
    hash_password,
    verify_password,
)

# ---------------------------------------------------------------------------
# _prehash
# ---------------------------------------------------------------------------


class TestPrehash:
    def test_returns_bytes(self):
        result = _prehash("hello")
        assert isinstance(result, bytes)

    def test_deterministic(self):
        assert _prehash("password") == _prehash("password")

    def test_different_inputs_different_hashes(self):
        assert _prehash("a") != _prehash("b")

    def test_output_is_hex_encoded_sha256(self):
        result = _prehash("test")
        # SHA-256 hex digest is always 64 characters
        assert len(result) == 64


# ---------------------------------------------------------------------------
# hash_password / verify_password
# ---------------------------------------------------------------------------


class TestHashPassword:
    def test_returns_string(self):
        hashed = hash_password("mypassword")
        assert isinstance(hashed, str)

    def test_hash_differs_from_plain(self):
        assert hash_password("secret") != "secret"

    def test_different_calls_produce_different_hashes(self):
        """Each call uses a fresh salt."""
        h1 = hash_password("same")
        h2 = hash_password("same")
        assert h1 != h2


class TestVerifyPassword:
    def test_correct_password_returns_true(self):
        hashed = hash_password("correcthorse")
        assert verify_password("correcthorse", hashed) is True

    def test_wrong_password_returns_false(self):
        hashed = hash_password("correcthorse")
        assert verify_password("wronghorse", hashed) is False

    def test_empty_password(self):
        hashed = hash_password("")
        assert verify_password("", hashed) is True
        assert verify_password("notempty", hashed) is False

    def test_long_password_beyond_bcrypt_72_byte_limit(self):
        """Prehashing with SHA-256 means passwords >72 bytes still work."""
        long_pw = "a" * 200
        hashed = hash_password(long_pw)
        assert verify_password(long_pw, hashed) is True
        # Slightly different long password must fail
        assert verify_password("a" * 199 + "b", hashed) is False

    def test_unicode_password(self):
        pw = "\u00e9\u00e0\u00fc\u00f1\U0001f600"
        hashed = hash_password(pw)
        assert verify_password(pw, hashed) is True
        assert verify_password("ascii", hashed) is False


# ---------------------------------------------------------------------------
# create_access_token
# ---------------------------------------------------------------------------


class TestCreateAccessToken:
    def test_returns_string(self):
        token = create_access_token({"sub": "user1"})
        assert isinstance(token, str)

    def test_token_contains_subject(self):
        token = create_access_token({"sub": "user42"})
        payload = jwt.decode(token, settings.secret_key, algorithms=[ALGORITHM])
        assert payload["sub"] == "user42"

    def test_token_contains_expiry(self):
        before = datetime.now(UTC)
        token = create_access_token({"sub": "u"})
        after = datetime.now(UTC)

        payload = jwt.decode(token, settings.secret_key, algorithms=[ALGORITHM])
        exp = datetime.fromtimestamp(payload["exp"], tz=UTC)

        # JWT exp is truncated to integer seconds, so allow 1s tolerance
        expected_min = (
            before
            + timedelta(minutes=settings.access_token_expire_minutes)
            - timedelta(seconds=1)
        )
        expected_max = (
            after
            + timedelta(minutes=settings.access_token_expire_minutes)
            + timedelta(seconds=1)
        )
        assert expected_min <= exp <= expected_max

    def test_does_not_mutate_input(self):
        data = {"sub": "user1"}
        original = data.copy()
        create_access_token(data)
        assert data == original

    def test_extra_claims_preserved(self):
        token = create_access_token({"sub": "u", "role": "admin"})
        payload = jwt.decode(token, settings.secret_key, algorithms=[ALGORITHM])
        assert payload["role"] == "admin"


# ---------------------------------------------------------------------------
# decode_token
# ---------------------------------------------------------------------------


class TestDecodeToken:
    def test_valid_token(self):
        token = create_access_token({"sub": "user1"})
        payload = decode_token(token)
        assert payload is not None
        assert payload["sub"] == "user1"

    def test_expired_token_returns_none(self):
        expired_payload = {
            "sub": "user1",
            "exp": datetime.now(UTC) - timedelta(hours=1),
        }
        token = jwt.encode(expired_payload, settings.secret_key, algorithm=ALGORITHM)
        assert decode_token(token) is None

    def test_invalid_token_string_returns_none(self):
        assert decode_token("not.a.valid.token") is None

    def test_empty_string_returns_none(self):
        assert decode_token("") is None

    def test_wrong_secret_returns_none(self):
        token = jwt.encode(
            {"sub": "u", "exp": datetime.now(UTC) + timedelta(hours=1)},
            "wrong-secret",
            algorithm=ALGORITHM,
        )
        assert decode_token(token) is None

    def test_wrong_algorithm_returns_none(self):
        token = jwt.encode(
            {"sub": "u", "exp": datetime.now(UTC) + timedelta(hours=1)},
            settings.secret_key,
            algorithm="HS384",
        )
        assert decode_token(token) is None

    def test_tampered_token_returns_none(self):
        token = create_access_token({"sub": "user1"})
        # Replace signature with a completely different one
        parts = token.rsplit(".", 1)
        tampered_token = parts[0] + ".AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
        assert decode_token(tampered_token) is None
