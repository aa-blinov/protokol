"""A WebSocket client with no dependencies, sized for CDP.

verify.sh runs system python3, which has no `websocket` module, and a check
that silently skips itself is worse than no check: it turns "verified" into
"nothing happened". CDP only needs a text-frame client that reads server frames
and writes masked client frames, so that is all this is.

Handshake per RFC 6455; frames follow §5.1. Continuation frames and payloads
above 64 KiB are the two things real servers do that this must get right, and
both are handled.
"""

from __future__ import annotations

import base64
import os
import socket
import struct


class WebSocketError(RuntimeError):
    pass


class CDP:
    def __init__(self, url: str, timeout: float = 60.0) -> None:
        # ws://host:port/path
        rest = url.split("://", 1)[1]
        hostport, _, path = rest.partition("/")
        host, _, port = hostport.partition(":")
        self.sock = socket.create_connection((host, int(port or 80)), timeout=timeout)
        self.sock.settimeout(timeout)
        self.buffer = b""
        key = base64.b64encode(os.urandom(16)).decode()

        request = (
            f"GET /{path} HTTP/1.1\r\n"
            f"Host: {hostport}\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {key}\r\n"
            "Sec-WebSocket-Version: 13\r\n\r\n"
        )
        self.sock.sendall(request.encode())

        while b"\r\n\r\n" not in self.buffer:
            chunk = self.sock.recv(4096)
            if not chunk:
                raise WebSocketError("сервер закрыл соединение на рукопожатии")
            self.buffer += chunk
        head, _, self.buffer = self.buffer.partition(b"\r\n\r\n")
        if b"101" not in head.split(b"\r\n")[0]:
            raise WebSocketError(f"рукопожатие отклонено: {head.split(chr(13).encode())[0][:80]!r}")

    def _recv(self, count: int) -> bytes:
        while len(self.buffer) < count:
            chunk = self.sock.recv(65536)
            if not chunk:
                raise WebSocketError("соединение закрыто")
            self.buffer += chunk
        data, self.buffer = self.buffer[:count], self.buffer[count:]
        return data

    def _frame(self) -> bytes:
        """One complete (possibly continued) message, reassembled."""
        first, second = self._recv(2)
        opcode = first & 0x0F
        length = second & 0x7F
        if length == 126:
            (length,) = struct.unpack(">H", self._recv(2))
        elif length == 127:
            (length,) = struct.unpack(">Q", self._recv(8))
        payload = self._recv(length) if length else b""

        if opcode == 0x8:  # close
            raise WebSocketError("сервер закрыл соединение")
        if opcode == 0x9:  # ping -> pong, same payload
            self._send_frame(0xA, payload)
            return self._frame()
        if opcode == 0xA:
            return self._frame()

        while opcode in (0x0, 0x1) and (second & 0x80):
            # Continuation: the FIN bit is on this frame's second byte.
            cont, second2 = self._recv(2)
            length2 = second2 & 0x7F
            if length2 == 126:
                (length2,) = struct.unpack(">H", self._recv(2))
            elif length2 == 127:
                (length2,) = struct.unpack(">Q", self._recv(8))
            payload += self._recv(length2) if length2 else b""
            if not (second2 & 0x80):
                break
        return payload.decode("utf-8", "replace")

    def _send_frame(self, opcode: int, payload: bytes) -> None:
        mask = os.urandom(4)
        masked = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
        length = len(payload)
        header = bytearray([0x80 | opcode])
        if length < 126:
            header.append(0x80 | length)
        elif length < (1 << 16):
            header.append(0x80 | 126)
            header += struct.pack(">H", length)
        else:
            header.append(0x80 | 127)
            header += struct.pack(">Q", length)
        self.sock.sendall(bytes(header) + mask + masked)

    def recv(self) -> str:
        return self._frame()

    def send(self, text: str) -> None:
        self._send_frame(0x1, text.encode())

    def close(self) -> None:
        try:
            self._send_frame(0x8, b"")
        except Exception:
            pass
        try:
            self.sock.close()
        except Exception:
            pass