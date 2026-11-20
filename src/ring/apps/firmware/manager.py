"""Runtime-owned update session, firmware catalog and device exclusivity."""
import asyncio
from pathlib import Path

from .images import FIRMWARE_ROOT, FAMILIES, load_image, read_catalog


class FirmwareManager:
    def __init__(self, engine, root=FIRMWARE_ROOT, updater=None):
        self.engine = engine
        self.root = Path(root)
        self.updater = updater
        self.catalog = []
        self.task = None
        self.state = dict(busy=False, refreshing=False, cancellable=False, phase="idle", progress=0.,
                          sent=0, total=0, address="", deviceName="", version="", previousVersion="",
                          message="选择戒指与匹配的固件版本", error="", warning="")

    async def refresh(self):
        if self.state["busy"] or self.state["refreshing"]:
            return
        self.state.update(refreshing=True, error="")
        try:
            catalog = await asyncio.to_thread(read_catalog, self.root)
            self.catalog = [f for f in catalog if f.device in self.engine.product.drivers]
            self._summaries = [f.summary() for f in self.catalog]
        except Exception as exc:
            self.catalog = []
            self._summaries = []
            self.state["error"] = str(exc)
        finally:
            self.state["refreshing"] = False

    def snapshot(self):
        # File contents and stat calls stay outside the UI polling path.
        return dict(self.state, firmwares=list(getattr(self, "_summaries", [])))

    def _recording_active(self):
        e = self.engine
        if e.recording or e.record_busy or e.syncing:
            return True
        lab = e.ringo_lab
        return bool(lab and (lab.recording or lab.controls or any(
            d.get("imu_writer") or d.get("audio_writer") or d.get("imu_saving") or d.get("audio_saving")
            for d in lab.devices.values())))

    async def start(self, address, firmware_id):
        if self.state["busy"] or self.state["refreshing"]:
            raise RuntimeError("请等待当前固件操作完成")
        e = self.engine
        device = e.devices.get(address)
        ring = e.rings.get(address)
        firmware = next((f for f in self.catalog if f.id == firmware_id), None)
        if (not device or device.get("simulated") or not device.get("connected")
                or device.get("busy") or not ring or not ring.connected):
            raise RuntimeError("请先在设备页连接要烧录的真实戒指")
        if firmware is None or firmware.device != device["driver"]:
            raise RuntimeError("戒指类型与固件不匹配，禁止烧录")
        if self._recording_active():
            raise RuntimeError("请先结束录制、同步及设备控制操作")
        if e.gestures and e.gestures.devices.get(address, {}).get("busy"):
            raise RuntimeError("请等待手势控制完成")
        self.state.update(busy=True, cancellable=True, phase="preflight", progress=0., sent=0, total=0,
                          address=address, deviceName=device["name"], version=firmware.version,
                          previousVersion=device.get("firmwareVersion", ""), error="", warning="",
                          message="检查固件与戒指类型")
        e._state(address, busy=True)
        self.task = asyncio.create_task(self._run(address, ring, firmware))
        self.task.add_done_callback(self._finished)

    def _finished(self, task):
        if task.cancelled():
            self.state.update(busy=False, cancellable=False, phase="cancelled", message="已取消上传")
            self.engine._state(self.state["address"], busy=False)

    def report(self, phase, message, sent=0, total=0):
        self.state.update(phase=phase, message=message,
                          cancellable=phase in ("preflight", "connecting", "uploading"))
        if total:
            self.state.update(sent=sent, total=total, progress=min(1., max(0., sent / total)))

    async def _run(self, address, ring, firmware):
        e = self.engine
        detached = False
        try:
            image = await asyncio.to_thread(load_image, firmware)
            identity = await ring.read_firmware_identity()
            if identity["family"] != firmware.device:
                raise RuntimeError(f"设备 INFO 类型不是 {FAMILIES[firmware.device]}，禁止烧录")
            self.state["previousVersion"] = ".".join(map(str, identity["version"][:3]))
            # Resolve the transport dependency before disconnecting a working device.
            updater = self.updater
            if updater is None:
                from .transport import SmpBackend, require_address, update
                require_address(address)
                SmpBackend(address)
                updater = update
            for command in (b"\x26\x01", b"\x21\x01", b"\x24\x01", b"\x20\x01"):
                await ring.write(command)
            if e.gestures and address in e.gestures.devices:
                e.gestures.devices[address]["enabled"] = False
            ring.set_auto_reconnect(False)
            detached = True
            await asyncio.wait_for(ring.disconnect(), 15)
            e._state(address, connected=False, busy=True, state="固件升级中")
            await updater(address, image, self.report)
            # SMP confirmation is the success criterion. Restoring IMU is separate.
            self.report("restoring", "固件已验证，正在恢复设备连接")
            try:
                await asyncio.wait_for(ring.connect(), 20)
                identity = await ring.read_firmware_identity()
                if identity["family"] != firmware.device or identity["version"] != image.version:
                    raise RuntimeError("重连后的设备 INFO 与目标固件不一致")
            except Exception as exc:
                raise RuntimeError(f"升级镜像已确认，但设备重连验证失败：{exc}") from exc
            try:
                await ring.open_imu()
            except Exception as exc:
                self.state["warning"] = f"固件已更新；采集恢复失败，请重新连接：{exc}"
            e._ble_state(address)
            self.state.update(phase="complete", progress=1., message="固件烧录完成，设备版本已验证")
            e.log(f"{self.state['deviceName']} 固件已更新至 {firmware.version}")
        except asyncio.CancelledError:
            self.state.update(phase="cancelled", message="已取消上传，未请求切换固件")
        except Exception as exc:
            self.state.update(phase="error", error=str(exc), message="固件烧录未完成")
            e.log(f"固件烧录未完成：{exc}")
        finally:
            if detached and self.state["phase"] != "complete":
                try:
                    await asyncio.wait_for(ring.disconnect(), 8)
                except Exception:
                    pass
                e._state(address, connected=False, state="未连接")
            self.state.update(busy=False, cancellable=False)
            e._state(address, busy=False)

    def cancel(self):
        if self.state["busy"] and self.state["cancellable"] and self.task:
            self.state["cancellable"] = False
            self.task.cancel()

    async def close(self):
        self.cancel()
        if self.task:
            await asyncio.shield(asyncio.gather(self.task, return_exceptions=True))
