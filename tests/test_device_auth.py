from eventpulse.device_auth import generate_device_token, hash_device_token, verify_device_token


def test_hash_and_verify_roundtrip():
    token = generate_device_token()
    th = hash_device_token(token)

    assert th.salt_b64
    assert th.hash_b64

    assert verify_device_token(
        token,
        salt_b64=th.salt_b64,
        hash_b64=th.hash_b64,
        iterations=th.iterations,
    )


def test_verify_fails_for_wrong_token():
    token = generate_device_token()
    th = hash_device_token(token)

    assert not verify_device_token(
        token + "x",
        salt_b64=th.salt_b64,
        hash_b64=th.hash_b64,
        iterations=th.iterations,
    )


def test_verify_fails_for_bad_base64():
    assert not verify_device_token(
        "abc",
        salt_b64="not-base64",
        hash_b64="also-not",
        iterations=200_000,
    )
