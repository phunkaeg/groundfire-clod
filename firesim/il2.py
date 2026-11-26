"""IL-2 framing and narrow ground-log ingestion; no connection at import time.

Wire reference: author's working client in IL-2 forum topic 61076.
Log grammar cross-checked against vaal-/il2_stats at recorded source commit.
The real installed game/server has not been used to accept this adapter.
"""
from __future__ import annotations

import hashlib
import math
import re
import socket
import struct


def pack_message(text):
    if any(ch in text for ch in ("\0", "\r", "\n")):
        raise ValueError("Invalid command delimiter")
    data = text.encode("ascii") + b"\0"
    if len(data) > 65535:
        raise ValueError("IL-2 RCon payload too long")
    return struct.pack("<H", len(data)) + data


def recv_exact(sock, n):
    pieces = bytearray()
    while len(pieces) < n:
        part = sock.recv(n - len(pieces))
        if not part:
            raise ConnectionError("Remote console closed a partial frame")
        pieces.extend(part)
    return bytes(pieces)


def receive_message(sock):
    size, = struct.unpack("<H", recv_exact(sock, 2))
    if size < 1:
        raise ValueError("Empty IL-2 frame")
    payload = recv_exact(sock, size)
    if not payload.endswith(b"\0") or b"\0" in payload[:-1]:
        raise ValueError("Malformed IL-2 C-string frame")
    return payload[:-1].decode("ascii")


class RconClient:
    def __init__(self, host, port, timeout=3):
        self.host, self.port, self.timeout = host, port, timeout
        self.sock = None

    def connect(self, username, password):
        if any(ch.isspace() for ch in username + password):
            raise ValueError("Whitespace credentials need protocol investigation; unsupported")
        self.close()
        self.sock = socket.create_connection((self.host, self.port), self.timeout)
        self.sock.settimeout(self.timeout)
        try:
            self._request(f"auth {username} {password}")
        except Exception:
            self.close()
            raise

    def _request(self, command):
        if self.sock is None:
            raise ConnectionError("Remote console is not connected")
        # No automatic retransmission: a damage command may be non-idempotent.
        try:
            self.sock.sendall(pack_message(command))
            response = receive_message(self.sock)
            status = re.search(r"\bSTATUS=(\d+)\b", response)
            if status is None or int(status[1]) != 1:
                raise RuntimeError("Remote console rejected a command: " + response)
            return response
        except Exception:
            self.close()
            raise

    def trigger(self, name):
        if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{0,100}", name):
            raise ValueError("Invalid Server Input Translator name")
        return self._request("serverinput " + name)

    def close(self):
        if self.sock is not None:
            self.sock.close()
            self.sock = None


class GroundLogIngestor:
    """Require an explicit target+ammo hit before damage can seed fire.

    No aircraft ignition, anonymous arbitrary damage ignition, inferred bomb
    ground impact, or default coordinate/clock conversion. Records retain ticks.
    Target mapping gives local simulator coordinates, independent of native axes.
    """
    def __init__(self, ground_targets, ammunition, correlation_ticks=100):
        self.targets = ground_targets
        self.ammunition = ammunition
        self.correlation_ticks = correlation_ticks
        self.hits = {}
        self.pending = {}
        self.last_tick = -1
        self.mission_epoch = 0
        self.seen = set()

    def feed(self, line, sim):
        match = re.match(r"^T:(\d+) AType:(\d+)\s?(.*)$", line.strip())
        if not match:
            return "ignored"
        tick, kind, rest = int(match[1]), int(match[2]), match[3]
        if kind == 0:
            self.hits.clear()
            self.pending.clear()
            self.mission_epoch += 1
            self.last_tick = tick
            return "mission-reset"
        if tick < self.last_tick:
            # Out-of-order records are supported, but mission changes require AType 0.
            pass
        self.last_tick = max(self.last_tick, tick)
        fields = dict(re.findall(r"(?:^|\s)([A-Z]+):([^\s]+)", rest))
        if kind not in (1, 2) or fields.get("TID") not in self.targets:
            return "ignored"
        key = (fields.get("AID"), fields["TID"])
        if kind == 1:
            ammo = fields.get("AMMO")
            if ammo not in self.ammunition:
                return "ignored-ammunition"
            self.hits[key] = (tick, ammo)
            pending = self.pending.pop(key, None)
            if pending and abs(tick - pending[0]) <= self.correlation_ticks:
                return self._apply(key, tick, ammo, pending[1], sim)
            return "hit-recorded"
        try:
            damage = float(fields.get("DMG", "nan"))
        except ValueError:
            return "ignored-damage"
        if not math.isfinite(damage) or damage <= 0:
            return "ignored-damage"
        digest = hashlib.sha256(line.strip().encode()).hexdigest()
        hit = self.hits.get(key)
        if hit and abs(tick - hit[0]) <= self.correlation_ticks:
            return self._apply(key, hit[0], hit[1], digest, sim)
        self.pending[key] = (tick, digest)
        return "damage-awaiting-hit"

    def _apply(self, key, hit_tick, ammo, digest, sim):
        # One pulse per correlated hit, not one pulse for every later damage record.
        event_id = f"il2:{self.mission_epoch}:{hit_tick}:{key[0]}:{key[1]}:{ammo}"
        if event_id in self.seen:
            return "duplicate"
        self.seen.add(event_id)
        target = self.targets[key[1]]
        policy = self.ammunition[ammo]
        sim.ignite(target["east"], target["north"], policy["radius_m"], policy["exposure_kj_m2"], event_id)
        return "ignition-proxy"
