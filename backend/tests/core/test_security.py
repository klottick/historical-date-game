import pytest

from app.core.security import get_password_hash, verify_password


@pytest.mark.parametrize("password", ["a" * 127 + "1", "é" * 63 + "1"])
def test_password_hash_preserves_characters_beyond_bcrypt_limit(password: str) -> None:
    hashed_password = get_password_hash(password)

    assert verify_password(password, hashed_password)
    assert not verify_password(password[:-1] + "2", hashed_password)


def test_password_hashes_are_salted() -> None:
    password = "correct-horse-battery-staple"

    first_hash = get_password_hash(password)
    second_hash = get_password_hash(password)

    assert first_hash != second_hash
    assert verify_password(password, first_hash)
    assert verify_password(password, second_hash)
    assert not verify_password("incorrect-password", first_hash)
