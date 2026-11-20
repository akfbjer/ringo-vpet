"""Version-1 JSONL compatibility adapter, bounded per-client backlog.

A slow consumer is disconnected rather than silently losing control or samples.
The recorder is deliberately not a TCP consumer.
"""
import asyncio
import contextlib
from dataclasses import dataclass, field
import json


@dataclass(eq=False)
class ClientSession:
    writer: asyncio.StreamWriter
    subscriptions: set[str] | None = None
    streams: set[str] = field(default_factory=lambda: {"imu"})
    queue: asyncio.Queue = field(default_factory=lambda: asyncio.Queue(maxsize=256))
    writer_task: asyncio.Task | None = None


class ImuStreamHub:
    def __init__(self, host="127.0.0.1", port=17888):
        self.host, self.port = host, port
        self._server = None
        self._clients = set()
        self._tasks = set()
        self._rings = {}
        self.slow_disconnects = 0

    async def start(self):
        self._server = await asyncio.start_server(self._on_client, self.host, self.port, limit=16384)

    async def stop(self):
        if self._server:
            self._server.close()
            await self._server.wait_closed()
            self._server = None
        for client in tuple(self._clients):
            client.writer.close()
        tasks = tuple(self._tasks)
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

    def upsert_ring(self, address, name, connected):
        value = dict(address=address, name=name, connected=connected)
        if self._rings.get(address) == value:
            return
        self._rings[address] = value
        for client in tuple(self._clients):
            self._enqueue(client, self._status())

    def remove_rings(self, addresses):
        changed = False
        for address in addresses:
            changed |= self._rings.pop(address, None) is not None
        if changed:
            status = self._status()
            for client in tuple(self._clients):
                self._enqueue(client, status)

    def _status(self):
        return self._encode(dict(type="status", rings=list(self._rings.values())))

    @staticmethod
    def _encode(payload):
        return (json.dumps(payload, ensure_ascii=False, separators=(",", ":"))+"\n").encode()

    def publish_imu(self, *, address, name, local_timestamp, host_timestamp,
                    acc_x, acc_y, acc_z, gyr_x, gyr_y, gyr_z, sequence=0):
        clients = [c for c in self._clients if "imu" in c.streams and
            (c.subscriptions is None or address in c.subscriptions)]
        if not clients:
            return
        message = self._encode(dict(type="imu", address=address, name=name,
            timestamp=local_timestamp, local_timestamp=local_timestamp,
            host_timestamp=host_timestamp, sequence=sequence,
            acc=[acc_x, acc_y, acc_z], gyr=[gyr_x, gyr_y, gyr_z]))
        for client in clients:
            self._enqueue(client, message)

    def _enqueue(self, client, message):
        if client.writer.is_closing():
            return
        try:
            client.queue.put_nowait(message)
        except asyncio.QueueFull:
            self.slow_disconnects += 1
            client.writer.close()

    async def _write(self, client):
        try:
            while True:
                first = await client.queue.get()
                batch = [first]
                for _ in range(min(client.queue.qsize(), 63)):
                    batch.append(client.queue.get_nowait())
                client.writer.writelines(batch)
                await asyncio.wait_for(client.writer.drain(), timeout=2)
        except (ConnectionError, OSError, TimeoutError):
            client.writer.close()

    async def _on_client(self, reader, writer):
        task = asyncio.current_task()
        self._tasks.add(task)
        client = ClientSession(writer)
        self._clients.add(client)
        client.writer_task = asyncio.create_task(self._write(client))
        self._enqueue(client, self._encode(dict(type="hello", version=1)))
        self._enqueue(client, self._status())
        try:
            while raw := await reader.readline():
                try:
                    command = json.loads(raw)
                    if not isinstance(command, dict):
                        raise ValueError("command must be an object")
                    self._command(client, command)
                except (ValueError, TypeError, UnicodeError):
                    self._enqueue(client, self._encode(dict(type="error", message="invalid_command")))
        except (ConnectionError, OSError, ValueError):
            pass
        finally:
            client.writer_task.cancel()
            await asyncio.gather(client.writer_task, return_exceptions=True)
            self._clients.discard(client)
            writer.close()
            with contextlib.suppress(ConnectionError, OSError):
                await writer.wait_closed()
            self._tasks.discard(task)

    def _command(self, client, command):
        if command.get("cmd") == "status":
            self._enqueue(client, self._status())
        elif command.get("cmd") == "subscribe":
            rings, streams = command.get("rings", []), command.get("streams", ["imu"])
            if not isinstance(rings, list) or not all(isinstance(x, str) for x in rings):
                raise ValueError("invalid rings")
            if not isinstance(streams, list) or not all(isinstance(x, str) for x in streams):
                raise ValueError("invalid streams")
            if set(streams)-{"imu"}:
                self._enqueue(client, self._encode(dict(type="error", message="unsupported_stream")))
                return
            # Legacy [] means all; explicit all=false means no rings.
            client.subscriptions = set(rings) if rings or command.get("all") is False else None
            client.streams = set(streams)
            self._enqueue(client, self._encode(dict(type="subscribed", rings=rings, streams=streams)))
        else:
            self._enqueue(client, self._encode(dict(type="error", message="unsupported_command")))
