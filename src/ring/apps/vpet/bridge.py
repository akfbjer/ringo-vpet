"""Small, dependency-free clients for the two local JSON-lines services."""
from __future__ import annotations

import json
import math
import socket
from collections.abc import Iterator
from typing import Any

RINGO_ADDRESS = ("127.0.0.1", 17888)
VPET_ADDRESS = ("127.0.0.1", 17889)
COMMANDS = frozenset({
    "PING",
    "SUMMON", "FAREWELL", "STUDY", "MOVE_START", "MOVE_DELTA", "MOVE_END",
    "PLAY_DEAD", "PET", "FEED", "PANEL_TOGGLE", "PANEL_NEXT", "PANEL_PREV",
})


class VPetSession:
    """Keep a move sequence on one connection so disconnect releases the pet."""

    def __init__(self, address: tuple[str, int] = VPET_ADDRESS):
        self.address = address
        self.connection: socket.socket | None = None
        self.lines: Any = None

    def __enter__(self) -> "VPetSession":
        self.connection = socket.create_connection(self.address, timeout=3)
        self.connection.settimeout(5)
        self.lines = self.connection.makefile("r", encoding="utf-8")
        return self

    def __exit__(self, *_: object) -> None:
        if self.lines is not None:
            self.lines.close()
        if self.connection is not None:
            self.connection.close()

    def send(self, command: str, *, dx: float = 0, dy: float = 0) -> dict[str, Any]:
        command = command.upper()
        if command not in COMMANDS:
            raise ValueError(f"unsupported command: {command}")
        if command == "MOVE_DELTA" and (abs(dx) > 80 or abs(dy) > 80):
            raise ValueError("MOVE_DELTA is limited to 80 pixels per axis")
        if command == "MOVE_DELTA" and (not math.isfinite(dx) or not math.isfinite(dy)):
            raise ValueError("MOVE_DELTA coordinates must be finite")
        request: dict[str, Any] = {"version": 1, "command": command}
        if command == "MOVE_DELTA":
            request.update(dx=dx, dy=dy)
        assert self.connection is not None and self.lines is not None
        self.connection.sendall((json.dumps(request, separators=(",", ":")) + "\n").encode())
        raw = self.lines.readline(8193)
        if not raw or len(raw) > 8192:
            raise ConnectionError("VPet plugin did not return a valid response")
        response = json.loads(raw)
        if not isinstance(response, dict) or response.get("command") != command:
            raise ValueError("invalid VPet plugin response")
        return response


def send_command(command: str, *, dx: float = 0, dy: float = 0,
                 address: tuple[str, int] = VPET_ADDRESS) -> dict[str, Any]:
    with VPetSession(address) as session:
        return session.send(command, dx=dx, dy=dy)


def ringo_messages(*, address: tuple[str, int] = RINGO_ADDRESS,
                   ring_address: str | None = None) -> Iterator[dict[str, Any]]:
    """Yield Ringo status and IMU messages; a recognizer can consume this later."""
    with socket.create_connection(address, timeout=3) as connection:
        connection.sendall((json.dumps({"cmd": "subscribe", "rings": [ring_address]
                                        if ring_address else [], "streams": ["imu"]}) + "\n").encode())
        with connection.makefile("r", encoding="utf-8") as lines:
            for raw in lines:
                message = json.loads(raw)
                if isinstance(message, dict):
                    yield message
