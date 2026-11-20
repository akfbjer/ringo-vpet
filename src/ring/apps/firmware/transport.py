"""SMP adapter based on ring-python-sdk/ota; always uses an exact BLE address."""
import asyncio
from dataclasses import dataclass
import re
import time


@dataclass(frozen=True)
class Slot:
    slot: int
    version: str
    digest: bytes
    active: bool
    confirmed: bool
    pending: bool
    bootable: bool


def require_address(address):
    if not (re.fullmatch(r"(?:[0-9a-fA-F]{2}:){5}[0-9a-fA-F]{2}", address)
            or re.fullmatch(r"[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}", address)):
        raise ValueError("烧录目标必须是选定设备的完整蓝牙地址")


class SmpBackend:
    def __init__(self, address, timeout=12):
        require_address(address)
        from smpclient import SMPClient
        from smpclient.transport.ble import SMPBLETransport
        self.client = SMPClient(SMPBLETransport(), address, timeout)
        self.timeout = timeout

    async def connect(self):
        await self.client.connect(connect_timeout_s=self.timeout)

    async def disconnect(self):
        # Also clean up when connect failed after opening the BLE connection.
        try:
            await asyncio.wait_for(self.client.disconnect(), 5)
        except Exception:
            pass

    @staticmethod
    def _checked(response):
        from smpclient.generics import success
        if not success(response):
            raise RuntimeError(f"设备拒绝 OTA 请求：{response}")
        return response

    async def read_state(self):
        from smpclient.requests.image_management import ImageStatesRead
        result = self._checked(await self.client.request(ImageStatesRead()))
        return tuple(Slot(int(s.slot), s.version, bytes(s.hash or b""), bool(s.active),
                          bool(s.confirmed), bool(s.pending), bool(s.bootable)) for s in result.images)

    async def upload(self, data):
        async for offset in self.client.upload(data, slot=1):
            yield offset

    async def mark_test(self, digest):
        from smpclient.requests.image_management import ImageStatesWrite
        self._checked(await self.client.request(ImageStatesWrite(hash=digest, confirm=False)))

    async def reset(self):
        from smpclient.requests.os_management import ResetWrite
        self._checked(await self.client.request(ResetWrite()))


async def update(address, image, report, *, backend_factory=SmpBackend, verify_seconds=75):
    """Upload, test-swap, reboot, then require this image to be confirmed active."""
    require_address(address)
    from .images import version_tuple
    backend = backend_factory(address)
    try:
        report("connecting", "连接设备升级服务")
        await backend.connect()
        initial = await backend.read_state()
        if not any(s.active for s in initial):
            raise RuntimeError("设备没有报告当前运行固件")
        if any(s.pending for s in initial):
            raise RuntimeError("设备已有待切换固件，请先完成或恢复上一次升级")
        report("uploading", "正在上传固件", 0, len(image.data))
        async with asyncio.timeout(300):
            async for offset in backend.upload(image.data):
                report("uploading", "正在上传固件", offset, len(image.data))
        states = await backend.read_state()
        candidate = next((s for s in states if s.slot == 1 and s.digest == image.digest
                          and s.bootable and version_tuple(s.version) == image.version), None)
        if candidate is None:
            raise RuntimeError("上传后的固件槽位、版本或镜像摘要不匹配")
        report("marking", "标记固件试运行")
        await backend.mark_test(image.digest)
        report("rebooting", "设备正在重启")
        await backend.reset()
    finally:
        await backend.disconnect()
    report("verifying", "等待新固件启动并确认")
    deadline = time.monotonic() + verify_seconds
    last_error = "尚未重新发现设备"
    while time.monotonic() < deadline:
        verifier = backend_factory(address)
        try:
            async with asyncio.timeout(max(.01, min(20, deadline - time.monotonic()))):
                await verifier.connect()
                states = await verifier.read_state()
                active = next((s for s in states if s.active and s.confirmed and not s.pending
                               and s.digest == image.digest and version_tuple(s.version) == image.version), None)
                if active:
                    return active
                last_error = "新固件尚未成为已确认的运行镜像，设备可能已回滚"
        except Exception as exc:
            last_error = str(exc)
        finally:
            await verifier.disconnect()
        await asyncio.sleep(1)
    raise RuntimeError(f"固件验证超时：{last_error}")
