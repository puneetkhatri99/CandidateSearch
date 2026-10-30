from app.features.auth.passwords import hash_password, needs_rehash, verify_password


async def test_hash_verifies_and_rejects_wrong_password() -> None:
    password_hash = await hash_password("correct-horse-battery")

    assert password_hash.startswith("$argon2id$")
    assert await verify_password(password_hash, "correct-horse-battery")
    assert not await verify_password(password_hash, "wrong-password")
    assert not needs_rehash(password_hash)


async def test_garbage_hash_never_verifies() -> None:
    assert not await verify_password("not-a-hash", "anything")
