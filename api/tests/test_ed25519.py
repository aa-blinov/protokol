"""Ed25519 against the RFC 8032 test vectors, plus the properties the licence check relies on."""

import os

import pytest

from ed25519 import public_key, sign, verify

# RFC 8032, section 7.1: TEST 1 (empty message) and TEST 2 (one byte).
VECTORS = [
    (
        "9d61b19deffd5a60ba844af492ec2cc44449c5697b326919703bac031cae7f60",
        "d75a980182b10ab7d54bfed3c964073a0ee172f3daa62325af021a68f707511a",
        b"",
        "e5564300c360ac729086e2cc806e828a84877f1eb8e5d974d873e065224901555fb8821590a33bacc61e39701cf9b46bd25bf5f0595bbe24655141438e7a100b",
    ),
    (
        "4ccd089b28ff96da9db6c346ec114e0f5b8a319f35aba624da8cf6ed4fb8a6fb",
        "3d4017c3e843895a92b70aa74d1b7ebc9c982ccf2ec4968cc0cd55f12af4660c",
        bytes.fromhex("72"),
        "92a009a9f0d4cab8720e820b5f642540a2b27b5416503f8fb3762223ebdb69da085ac1e43e15996e458f3613d0f11d8c387b2eaeb4302aeeb00d291612bb0c00",
    ),
]


@pytest.mark.parametrize("secret_hex, public_hex, message, signature_hex", VECTORS)
def test_rfc8032_vectors(secret_hex, public_hex, message, signature_hex):
    secret = bytes.fromhex(secret_hex)
    assert public_key(secret).hex() == public_hex
    assert sign(secret, message).hex() == signature_hex
    assert verify(bytes.fromhex(public_hex), message, bytes.fromhex(signature_hex))


def test_round_trip_with_a_fresh_key():
    secret = os.urandom(32)
    public = public_key(secret)
    message = "payload with кириллица".encode("utf-8")
    signature = sign(secret, message)
    assert verify(public, message, signature)


def test_changed_message_is_rejected():
    secret = bytes(range(32))
    public = public_key(secret)
    signature = sign(secret, b"edition=team")
    assert not verify(public, b"edition=enterprise", signature)


def test_changed_signature_is_rejected():
    secret = bytes(range(32))
    public = public_key(secret)
    signature = bytearray(sign(secret, b"seats=10"))
    signature[5] ^= 0x01
    assert not verify(public, b"seats=10", bytes(signature))


def test_another_key_is_rejected():
    signature = sign(bytes(range(32)), b"seats=10")
    assert not verify(public_key(bytes(range(1, 33))), b"seats=10", signature)


def test_malformed_input_is_rejected_without_raising():
    public = public_key(bytes(range(32)))
    assert not verify(public, b"x", b"short")
    assert not verify(b"short", b"x", bytes(64))
    assert not verify(public, b"x", bytes(64))
