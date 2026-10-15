"""Ed25519 signatures in pure Python (RFC 8032), for licence files.

Standard library only, so the sidecar gets no new dependency. The app only
verifies, and verification uses the public key, which is not secret. Signing is
done by the vendor's licence tool, offline, with the private seed. At licence
size one check takes a few milliseconds.

Checked against the RFC 8032 test vectors in api/tests/test_ed25519.py.
"""

from __future__ import annotations

import hashlib

_P = 2**255 - 19
_L = 2**252 + 27742317777372353535851937790883648493  # order of the base point
_D = (-121665 * pow(121666, _P - 2, _P)) % _P
_I = pow(2, (_P - 1) // 4, _P)  # square root of -1

Point = tuple[int, int, int, int]  # extended twisted-Edwards coordinates X, Y, Z, T


def _recover_x(y: int, sign: int) -> int | None:
    xx = (y * y - 1) * pow(_D * y * y + 1, _P - 2, _P) % _P
    x = pow(xx, (_P + 3) // 8, _P)
    if (x * x - xx) % _P != 0:
        x = x * _I % _P
    if (x * x - xx) % _P != 0:
        return None
    if x == 0 and sign == 1:
        return None
    if x & 1 != sign:
        x = _P - x
    return x


_BASE_Y = 4 * pow(5, _P - 2, _P) % _P
_BASE_X = _recover_x(_BASE_Y, 0)
assert _BASE_X is not None
_BASE: Point = (_BASE_X, _BASE_Y, 1, _BASE_X * _BASE_Y % _P)
_NEUTRAL: Point = (0, 1, 1, 0)


def _add(p: Point, q: Point) -> Point:
    a = (p[1] - p[0]) * (q[1] - q[0]) % _P
    b = (p[1] + p[0]) * (q[1] + q[0]) % _P
    c = 2 * p[3] * q[3] * _D % _P
    d = 2 * p[2] * q[2] % _P
    e, f, g, h = b - a, d - c, d + c, b + a
    return (e * f % _P, g * h % _P, f * g % _P, e * h % _P)


def _mul(scalar: int, point: Point) -> Point:
    result = _NEUTRAL
    addend = point
    while scalar:
        if scalar & 1:
            result = _add(result, addend)
        addend = _add(addend, addend)
        scalar >>= 1
    return result


def _encode(point: Point) -> bytes:
    z_inv = pow(point[2], _P - 2, _P)
    x = point[0] * z_inv % _P
    y = point[1] * z_inv % _P
    return (y | ((x & 1) << 255)).to_bytes(32, "little")


def _decode(data: bytes) -> Point | None:
    if len(data) != 32:
        return None
    value = int.from_bytes(data, "little")
    sign = value >> 255
    y = value & ((1 << 255) - 1)
    if y >= _P:
        return None
    x = _recover_x(y, sign)
    if x is None:
        return None
    return (x, y, 1, x * y % _P)


def _expand(secret: bytes) -> tuple[int, bytes]:
    digest = hashlib.sha512(secret).digest()
    scalar = int.from_bytes(digest[:32], "little")
    scalar &= (1 << 254) - 8
    scalar |= 1 << 254
    return scalar, digest[32:]


def _hash_int(data: bytes) -> int:
    return int.from_bytes(hashlib.sha512(data).digest(), "little")


def public_key(secret: bytes) -> bytes:
    """The 32-byte public key of a 32-byte secret seed."""
    if len(secret) != 32:
        raise ValueError("the secret seed must be 32 bytes")
    scalar, _ = _expand(secret)
    return _encode(_mul(scalar, _BASE))


def sign(secret: bytes, message: bytes) -> bytes:
    """A 64-byte signature. Used by the vendor's licence tool, never by the app."""
    if len(secret) != 32:
        raise ValueError("the secret seed must be 32 bytes")
    scalar, prefix = _expand(secret)
    public = _encode(_mul(scalar, _BASE))
    r = _hash_int(prefix + message) % _L
    commitment = _encode(_mul(r, _BASE))
    k = _hash_int(commitment + public + message) % _L
    s = (r + k * scalar) % _L
    return commitment + s.to_bytes(32, "little")


def verify(public: bytes, message: bytes, signature: bytes) -> bool:
    """True when the signature is valid for the message under the public key."""
    if len(public) != 32 or len(signature) != 64:
        return False
    a_point = _decode(public)
    r_point = _decode(signature[:32])
    if a_point is None or r_point is None:
        return False
    s = int.from_bytes(signature[32:], "little")
    if s >= _L:
        return False
    k = _hash_int(signature[:32] + public + message) % _L
    return _encode(_mul(s, _BASE)) == _encode(_add(r_point, _mul(k, a_point)))
