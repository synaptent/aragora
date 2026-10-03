"""Public, non-secret TEST material. Never use this deterministic key in production."""

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

TEST_KEY_SEED = bytes(range(32))


def odr_test_key() -> Ed25519PrivateKey:
    """Return the reproducible test/vector signing key."""
    return Ed25519PrivateKey.from_private_bytes(TEST_KEY_SEED)
