import pytest
import uuid_utils.compat as uuid
from pydantic import SecretStr

from tramplin.core.config import Settings
from tramplin.core.errors import InvalidTokenError
from tramplin.core.security import AccessTokenCodec, generate_refresh_token, sha256_hex
from tramplin.core.time import utc_now


def test_access_token_roundtrip_returns_same_user(
    codec: AccessTokenCodec,
    settings: Settings,
) -> None:
    user_id = uuid.uuid7()

    token, expires_at = codec.encode(user_id)

    assert codec.decode(token) == user_id
    assert expires_at - utc_now() <= settings.access_token_ttl
    assert expires_at.tzinfo is not None


def test_access_token_decode_with_wrong_secret_raises_invalid_token(
    codec: AccessTokenCodec,
    settings: Settings,
) -> None:
    token, _ = codec.encode(uuid.uuid7())
    other_secret = SecretStr("another-secret-of-the-same-length")
    foreign = AccessTokenCodec(settings.model_copy(update={"jwt_secret": other_secret}))

    with pytest.raises(InvalidTokenError):
        foreign.decode(token)


def test_access_token_decode_of_garbage_raises_invalid_token(codec: AccessTokenCodec) -> None:
    with pytest.raises(InvalidTokenError):
        codec.decode("not-a-jwt")


def test_generate_refresh_token_returns_hash_matching_raw_value(settings: Settings) -> None:
    raw, token_hash = generate_refresh_token(settings.refresh_token_bytes)

    assert token_hash == sha256_hex(raw)
    assert raw not in token_hash
    assert len(token_hash) == 64
