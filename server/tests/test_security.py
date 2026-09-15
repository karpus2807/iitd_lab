from app.security import hash_password, hash_token, identity_fingerprint, token_matches, verify_password


def test_password_roundtrip():
    hashed = hash_password("s3cret!")
    assert hashed != "s3cret!"
    assert verify_password("s3cret!", hashed)
    assert not verify_password("wrong", hashed)


def test_token_hash_compare():
    raw = "registration-token-value"
    stored = hash_token(raw)
    assert token_matches(raw, stored)
    assert not token_matches("other", stored)


def test_identity_fingerprint_stable_and_ignores_unknown():
    a = identity_fingerprint(["HOST", "uuid-1", "Unknown", None, "  "])
    b = identity_fingerprint(["host", "uuid-1"])
    assert a == b
    assert a != identity_fingerprint(["host", "uuid-2"])
