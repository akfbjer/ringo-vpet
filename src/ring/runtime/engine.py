"""Single-owner asyncio runtime. No Qt imports or GUI-thread work."""
import asyncio
from collections import deque
from datetime import datetime
import math
from pathlib import Path
import threading
import time

from ring.core.buffer import SampleBuffer
from ring.core.plot_segments import GAP_SECONDS
from ring.product import load_product
from ring.drivers import create_driver
from ring.runtime.calibration import calibrate
from ring.adapters.stream_hub import ImuStreamHub


class Engine:
    def __init__(self, data_dir: Path, port=17888, product=None):
        self.product = product or load_product()
        self.firmware = None
        if "firmware" in self.product.apps:
            from ring.apps.firmware.manager import FirmwareManager
            self.firmware = FirmwareManager(self)
        self.ringo_lab = None
        if "ringo_lab" in self.product.apps:
            from ring.apps.ringo_lab import RingoLab
            self.ringo_lab = RingoLab(data_dir)
        self.density = None
        if "density" in self.product.apps:
            from ring.apps.density.manager import DensityManager
            self.density = DensityManager(wakeup=self._density_done)
        self.discovered = {}
        self.handwriting = None
        if "handwriting" in self.product.apps:
            from ring.apps.handwriting.manager import HandwritingManager
            self.handwriting = HandwritingManager()
        self.click = None
        if "click" in self.product.apps:
            from ring.apps.click.manager import ClickManager
            self.click = ClickManager()
        self.gestures = None
        if "gestures" in self.product.apps:
            from ring.apps.gestures import Gestures
            self.gestures = Gestures()
        self.data_dir, self.port = data_dir, port
        self.loop = asyncio.new_event_loop()
        self.thread = threading.Thread(target=self._run, name="ring-runtime")
        self.ready = threading.Event()
        self.lock = threading.Lock()
        self.devices, self.rings, self.buffers = {}, {}, {}
        self.rates, self.sequence = {}, {}
        self.connection_generations = {}
        self.status = "运行时启动中"
        self.scanning = self.demo = self.recording = False
        self.server_ready = False
        self.recorder = None
        self.demo_task = None
        self.tasks = set()
        self.events = deque(maxlen=80)
        self.hub = ImuStreamHub(port=port)
        self.closing = False
        self.record_busy = False
        self.syncing = False
        self.sync_progress = 0.0
        self.last_timestamps = {}
        self.preview_clocks = {}
        self.gaps = 0
        self.thread.start()
        self.ready.wait(3)

    def _run(self):
        asyncio.set_event_loop(self.loop)
        self.ready.set()
        self.loop.create_task(self._start())
        self.loop.run_forever()
        self.loop.close()

    async def _start(self):
        try:
            await self.hub.start()
            self.server_ready = True
            self.log("工作台已就绪")
        except OSError as exc:
            self.log(f"数据服务启动失败（端口 {self.port}）：{exc}")

    def log(self, message):
        with self.lock:
            self.status = message
            self.events.appendleft({"time": datetime.now().strftime("%H:%M:%S"), "text": message})

    def command(self, name, *args):
        if self.closing:
            return
        async def execute():
            task = asyncio.current_task()
            self.tasks.add(task)
            try:
                await getattr(self, "_" + name)(*args)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self.log(f"操作失败：{exc}")
            finally:
                self.tasks.discard(task)
        asyncio.run_coroutine_threadsafe(execute(), self.loop)

    def _device(self, address, name, simulated=False, driver="bcl"):
        address, name = str(address), str(name)
        with self.lock:
            if address not in self.devices:
                self.devices[address] = dict(address=address, name=name, connected=False,
                    busy=False, battery=-1, simulated=simulated, driver=driver, state="未连接", fps=0.0,
                    imuMode="six_axis", firmwareVersion="")
                self.buffers[address] = SampleBuffer()
                self.rates[address] = deque(maxlen=1000)
                self.sequence[address] = 0
                self.connection_generations[address] = 0
        self.hub.upsert_ring(address, name, self.devices[address]["connected"])

    def _state(self, address, **changes):
        if self.ringo_lab and self.devices[address]['driver'] == 'ringo' and 'connected' in changes:
            self.ringo_lab.connection(address, changes['connected'])
        if self.density and changes.get("connected") is False:
            self.density.disconnect(address)
        if self.handwriting and changes.get("connected") is False:
            self.handwriting.disconnect(address)
        if self.click and changes.get("connected") is False:
            self.click.disconnect(address)
        with self.lock:
            if "connected" in changes and changes["connected"] != self.devices[address]["connected"]:
                if self.gestures:
                    self.gestures.reset_connection(address)
                self.connection_generations[address] += 1
                self.buffers[address].clear()
                self.rates[address].clear()
                self.last_timestamps.pop(address, None)
                self.preview_clocks.pop(address, None)
            self.devices[address].update(changes)
            d = self.devices[address].copy()
        self.hub.upsert_ring(address, d["name"], d["connected"])

    async def _scan(self):
        self._require_no_firmware_update()
        if self.scanning:
            return
        from bleak import BleakScanner
        self.scanning = True
        self.log("正在扫描附近的戒指…")
        try:
            found = await BleakScanner.discover(timeout=4, return_adv=True)
            count = 0
            for d, advertisement in found.values():
                kind = self.product.match(d, advertisement)
                if kind:
                    self.discovered[str(d.address)] = d
                    self._device(d.address, d.name or advertisement.local_name or kind, driver=kind)
                    count += 1
            self.log(f"扫描完成，发现 {count} 枚戒指")
        finally:
            self.scanning = False

    async def _connect(self, address):
        if self.syncing:
            raise RuntimeError("请等待同步完成")
        if address not in self.devices or self.devices[address]["busy"]:
            return
        if self.devices[address]["simulated"]:
            return
        ring = self.rings.get(address)
        disconnecting = ring and (ring.connected or ring.is_reconnecting)
        if not disconnecting and self.product.max_devices is not None:
            occupied = sum(1 for other, device in self.devices.items() if other != address and
                           (device['connected'] or device['busy'] or
                            (self.rings.get(other) and self.rings[other].is_reconnecting)))
            if occupied >= self.product.max_devices:
                raise RuntimeError('此版本最多连接一枚 Ringo，请先断开当前设备' if self.product.max_devices == 1
                                   else f'此版本最多连接 {self.product.max_devices} 枚设备')
        self._state(address, busy=True, state="连接中")
        try:
            if address not in self.rings:
                kind = self.devices[address]["driver"]
                if kind not in self.product.drivers:
                    raise RuntimeError("此版本未包含该设备驱动")
                self.rings[address] = create_driver(kind, self.discovered[address],
                    self.devices[address]["name"],
                    sample=lambda timestamp, values: self.ingest(address, timestamp, values),
                    state=lambda: self._ble_state(address), reconnected=self._reconnected)
            ring = self.rings[address]
            if self.ringo_lab and self.devices[address]['driver'] == 'ringo':
                ring.packet_callback = lambda data: self.ringo_lab.receive(address, data)
                ring.command_callback = lambda data: self.ringo_lab.record(address, dict(type='tx', hex=data.hex()))
            if self.gestures and hasattr(ring, "set_gestures"):
                self.gestures.attach(address, ring)
            if ring.connected or ring.is_reconnecting:
                await ring.disconnect()
                self._state(address, connected=False, state="未连接")
            else:
                await asyncio.wait_for(ring.connect(), 20)
                if not ring.connected:
                    raise RuntimeError("连接未成功，请检查蓝牙权限和设备状态")
                if self.devices[address]["driver"] == "r1":
                    ring.imu_mode = self.devices[address]["imuMode"]
                await ring.open_imu()
                if self.gestures and self.devices[address]["imuMode"] != "ulp100":
                    await self.gestures.resume(address, ring)
                self._ble_state(address)
            self.log(f'{self.devices[address]["name"]} · {self.devices[address]["state"]}')
        except BaseException:
            ring = self.rings.get(address)
            if ring:
                await ring.disconnect()
            self._state(address, connected=False, state="连接失败")
            raise
        finally:
            self._state(address, busy=False)

    def _ble_state(self, address):
        ring = self.rings.get(address)
        if ring:
            self._state(address, connected=ring.connected, battery=ring.battery_level,
                firmwareVersion=getattr(ring, "firmware_version_text", "") if ring.connected else "",
                state="重连中" if ring.is_reconnecting else "已连接" if ring.connected else "未连接")

    async def _reconnected(self, address):
        await self.rings[address].open_imu()
        if self.gestures and self.devices[address]["imuMode"] != "ulp100":
            await self.gestures.resume(address, self.rings[address])
        self._ble_state(address)
        self.log("设备已自动重连")

    async def _r1_mode(self, address, mode):
        device = self.devices.get(address, {})
        ring = self.rings.get(address)
        if device.get("driver") != "r1" or mode not in ("six_axis", "ulp100"):
            raise ValueError("无效的 R1 采集模式")
        if (device.get("connected") or device.get("busy") or self.syncing
                or (ring and ring.is_reconnecting)):
            raise RuntimeError("请先断开设备再切换采集模式")
        self._state(address, imuMode=mode)

    def _require_six_axis(self, address):
        if self.devices.get(address, {}).get("imuMode") == "ulp100":
            raise RuntimeError("此功能需要 200 Hz 六轴数据，请断开后切换采集模式")

    async def _ringo_control(self, address, action):
        self._require_app('ringo_lab')
        self._require_no_firmware_update()
        if action == 'record':
            await self.ringo_lab.toggle_record(self.devices)
            return
        device = self.devices.get(address, {})
        ring = self.rings.get(address)
        if device.get('driver') != 'ringo' or not ring or not ring.connected or device.get('busy'):
            raise RuntimeError('请先连接 Ringo 并等待连接完成')
        await self.ringo_lab.control(address, ring, action)

    async def _gesture(self, address):
        self._require_app("gestures")
        ring = self.rings.get(address)
        if self.devices.get(address, {}).get("busy"):
            raise RuntimeError("请等待设备连接完成")
        if not ring or not ring.connected or not hasattr(ring, "set_gestures"):
            raise RuntimeError("请连接支持手势的 R1 或 Ringo")
        self._require_six_axis(address)
        await self.gestures.toggle(address, ring)

    async def _density(self, action, address=""):
        self._require_app("density")
        if action == "load":
            self.density.load()
        elif action == "stop":
            self.density.stop()
        elif action == "start":
            device = self.devices.get(address, {})
            ring = self.rings.get(address)
            if (device.get("driver") != "r1" or device.get("imuMode") != "ulp100"
                    or not device.get("connected") or device.get("busy") or device.get("simulated")
                    or not ring or not ring.connected or not ring._stream_ready
                    or ring._active_mode != "ulp100"):
                raise RuntimeError("请先以 ULP 100 Hz 加速度模式连接 R1 并等待数据流就绪")
            self.density.start(address)
        else:
            raise ValueError("未知 density 操作")

    def _density_done(self):
        # Future callbacks run on the worker. Continue pending patches on the
        # runtime loop immediately, including the tail of a BLE notification.
        self.loop.call_soon_threadsafe(self.density.poll)

    async def _density_snapshot(self):
        return self.density.snapshot() if self.density else {}

    def density_snapshot_future(self):
        return asyncio.run_coroutine_threadsafe(self._density_snapshot(), self.loop)

    async def _click_start(self, address, cursor, dispatch, mapping):
        self._require_app("click")
        device = self.devices.get(address, {})
        if not device.get("connected") or device.get("simulated") or device.get("busy"):
            raise RuntimeError("请先连接真实戒指")
        self._require_six_axis(address)
        self.click.start(address, cursor=cursor, dispatch=dispatch, mapping=mapping)

    async def _click_stop(self):
        self._require_app("click")
        self.click.stop()

    async def _handwriting(self, action, address="", mode="digits"):
        self._require_app("handwriting")
        if action == "load":
            self.handwriting.load()
        elif action == "start":
            device = self.devices.get(address, {})
            if not device.get("connected") or device.get("simulated") or device.get("busy"):
                self.handwriting.error = "请先连接真实戒指"
                return
            self._require_six_axis(address)
            self.handwriting.start(address, mode)
        elif action == "finish":
            self.handwriting.finish()
        elif action == "cancel":
            self.handwriting.cancel()
        elif action == "mode":
            self.handwriting.set_mode(mode)
        elif action == "clear":
            self.handwriting.history.clear()

    def ingest(self, address, timestamp, values):
        if not self.devices[address]["connected"]:
            return
        if not math.isfinite(timestamp) or not all(math.isfinite(x) for x in values):
            self.log("收到无效 IMU 数值，已拒绝该帧")
            return
        if self.density:
            self.density.feed(address, timestamp, values)
        if self.handwriting:
            self.handwriting.feed(address, timestamp, values)
        if self.click:
            self.click.feed(address, timestamp, values)
        previous = self.last_timestamps.get(address)
        gap = previous is not None and timestamp > 0 and previous > 0 and (timestamp <= previous or timestamp-previous > GAP_SECONDS)
        self.last_timestamps[address] = timestamp
        self.gaps += int(gap)
        reset = previous is not None and timestamp > 0 and previous > 0 and timestamp < previous
        clock = "device" if timestamp > 0 or self.devices[address]["simulated"] else "host"
        changed_clock = address in self.preview_clocks and self.preview_clocks[address] != clock
        self.preview_clocks[address] = clock
        if reset or changed_clock:
            self.buffers[address].clear()
        now = time.perf_counter()
        self.buffers[address].append(timestamp if timestamp > 0 or self.devices[address]["simulated"] else now, values)
        self.rates[address].append(now)
        self.sequence[address] += 1
        d = self.devices[address]
        ring = self.rings.get(address)
        host_timestamp = ring.to_host_timestamp(timestamp) if ring else 0.0
        self.hub.publish_imu(address=address, name=d["name"], local_timestamp=timestamp,
            host_timestamp=host_timestamp, acc_x=values[0], acc_y=values[1], acc_z=values[2],
            gyr_x=values[3], gyr_y=values[4], gyr_z=values[5], sequence=self.sequence[address])
        lab_recording = self.ringo_lab and self.ringo_lab.is_imu_recording(address)
        if self.recorder or lab_recording:
            sample = dict(type="imu", address=address, name=d["name"],
                timestamp=timestamp, host_timestamp=host_timestamp, received=now, sequence=self.sequence[address],
                simulated=d["simulated"], discontinuity=gap, acc=list(values[:3]), gyr=list(values[3:]))
            if self.recorder:
                self.recorder.submit(sample)
            if lab_recording:
                self.ringo_lab.feed_imu(sample)

    async def _demo(self):
        if self.recording or self.syncing:
            raise RuntimeError("请先停止录制或等待同步完成")
        if self.demo:
            self.demo = False
            self.demo_task.cancel()
            await asyncio.gather(self.demo_task, return_exceptions=True)
            self.demo_task = None
            with self.lock:
                addresses = [a for a, d in self.devices.items() if d["simulated"]]
                for address in addresses:
                    for mapping in (self.devices, self.buffers, self.rates, self.sequence,
                                    self.connection_generations, self.last_timestamps, self.preview_clocks):
                        mapping.pop(address, None)
            self.hub.remove_rings(addresses)
            self.log("演示数据已停止")
        else:
            self.demo = True
            for i, side in enumerate(("left", "right")):
                address = "demo-" + side
                self._device(address, "Ring " + side.title(), True)
                self._state(address, connected=True, state="模拟数据", battery=86-i*14)
            self.demo_task = asyncio.create_task(self._generate())
            self.log("演示模式 · 双设备 200 Hz 模拟数据")

    async def _generate(self):
        origin, index = time.perf_counter(), 0
        while True:
            due = int((time.perf_counter()-origin)*200)
            # Cap catch-up: a stalled source exposes a time gap rather than blocking forever.
            index = max(index, due-40)
            while index < due:
                t = index / 200
                for i, side in enumerate(("left", "right")):
                    p = t*2.4+i
                    self.ingest("demo-"+side, t, (math.sin(p)*2.2,
                        math.sin(p*1.7)*1.3, 9.8+math.cos(p)*0.6,
                        math.cos(p*0.8)*0.6, math.sin(p)*0.4, math.cos(p*1.4)*0.3))
                index += 1
            await asyncio.sleep(0.01)

    async def _sync(self):
        self._require_app("recording")
        self._require_no_firmware_update()
        if self.syncing or self.recording or self.record_busy:
            raise RuntimeError("请等待同步完成或先停止录制")
        targets = [self.rings[a] for a, d in self.devices.items()
                   if d["connected"] and not d["simulated"] and a in self.rings]
        if not targets:
            raise RuntimeError("请连接真实戒指后生成同步文件")
        generations = {ring.address: self.connection_generations[ring.address] for ring in targets}
        def valid():
            return all(ring.connected and self.devices[ring.address]["connected"]
                       and self.connection_generations[ring.address] == generations[ring.address]
                       for ring in targets)
        self.syncing, self.sync_progress = True, 0.0
        try:
            files = []
            # Sequential exchanges preserve the old per-device sampling workload.
            for i, ring in enumerate(targets):
                self.log(f"正在同步 {self.devices[ring.address]['name']}（{i+1}/{len(targets)}）")
                def progress(current, total, offset=i):
                    self.sync_progress = (offset + current / total) / len(targets)
                # Separate device folders retain the exact legacy filename without collisions.
                import re
                folder = re.sub(r"[^a-zA-Z0-9_-]", "_", str(ring.address))
                path = await calibrate(ring, self.data_dir / "sync" / folder, progress, valid=valid)
                files.append(str(path))
                self.log(f"同步文件已保存：{path.relative_to(self.data_dir)}")
            self.sync_progress = 1.0
            return files
        finally:
            self.syncing = False

    def _require_app(self, name):
        if name not in self.product.apps:
            raise RuntimeError("此版本未包含该应用")

    def _require_no_firmware_update(self):
        if self.firmware and self.firmware.state["busy"]:
            raise RuntimeError("请等待固件烧录完成")

    async def _firmware_refresh(self):
        self._require_app("firmware")
        await self.firmware.refresh()

    async def _firmware_start(self, address, firmware_id):
        self._require_app("firmware")
        try:
            await self.firmware.start(address, firmware_id)
        except Exception as exc:
            if not self.firmware.state["busy"]:
                self.firmware.state["error"] = str(exc)
            raise

    async def _firmware_cancel(self):
        self._require_app("firmware")
        self.firmware.cancel()

    async def _record(self):
        self._require_app("recording")
        self._require_no_firmware_update()
        if self.record_busy or self.syncing:
            return
        self.record_busy = True
        try:
            await self._toggle_record()
        finally:
            self.record_busy = False

    async def _toggle_record(self):
        if self.recorder:
            recorder, self.recorder = self.recorder, None
            self.recording = False
            await asyncio.shield(asyncio.to_thread(recorder.close))
            self.log(recorder.error or f"已保存 {recorder.count:,} 帧 · {recorder.path.name}")
        else:
            if not any(d["connected"] for d in self.devices.values()):
                raise RuntimeError("请先连接设备")
            path = self.data_dir / (datetime.now().strftime("session-%Y%m%d-%H%M%S-%f") + ".h5")
            from ring.runtime.recorder import Recorder
            self.recorder = Recorder(path)
            self.recording = True
            self.log("开始录制 · " + path.name)

    async def _snapshot(self):
        now = time.perf_counter()
        with self.lock:
            devices = [d.copy() for d in self.devices.values()]
            events, status = list(self.events), self.status
        devices.sort(key=lambda d: (d["name"].casefold(), d["address"]))
        for d in devices:
            stamps = self.rates[d["address"]]
            d["fps"] = float(sum(t > now-1 for t in stamps)) if d["connected"] else 0.0
        return dict(devices=devices, events=events, status=status, scanning=self.scanning,
            demo=self.demo, recording=self.recording, serverReady=self.server_ready,
            frames=sum(self.sequence.values()), recorded=self.recorder.count if self.recorder else 0,
            error=self.recorder.error if self.recorder else "", port=self.port,
            slowClients=self.hub.slow_disconnects, gaps=self.gaps,
            syncing=self.syncing, syncProgress=self.sync_progress,
            recordBusy=self.record_busy,
            firmware=self.firmware.snapshot() if self.firmware else {},
            ringoLab=self.ringo_lab.snapshot(self.devices) if self.ringo_lab else {},
            handwriting=self.handwriting.snapshot() if self.handwriting else {},
            click=self.click.snapshot() if self.click else {},
            gestures=self.gestures.snapshot(self.devices) if self.gestures else dict(devices=[], history=[]))

    def snapshot_future(self):
        return asyncio.run_coroutine_threadsafe(self._snapshot(), self.loop)

    def preview(self, address):
        with self.lock:
            buffer = self.buffers.get(address)
        return buffer.snapshot() if buffer else None

    async def _shutdown(self):
        if self.firmware:
            await self.firmware.close()
        for task in list(self.tasks):
            task.cancel()
        await asyncio.gather(*list(self.tasks), return_exceptions=True)
        if self.demo_task:
            self.demo_task.cancel()
            await asyncio.gather(self.demo_task, return_exceptions=True)
        if self.density:
            await asyncio.to_thread(self.density.close)
        if self.handwriting:
            await asyncio.to_thread(self.handwriting.close)
        if self.click:
            await asyncio.to_thread(self.click.close)
        for ring in self.rings.values():
            ring.set_auto_reconnect(False)
        await asyncio.gather(*(r.disconnect() for r in self.rings.values()), return_exceptions=True)
        if self.recorder:
            await self._record()
        if self.ringo_lab:
            await self.ringo_lab.close()
        await self.hub.stop()
        pending = [task for task in asyncio.all_tasks() if task is not asyncio.current_task()]
        for task in pending:
            task.cancel()
        await asyncio.gather(*pending, return_exceptions=True)
        await self.loop.shutdown_default_executor()

    def close(self):
        self.closing = True
        future = asyncio.run_coroutine_threadsafe(self._shutdown(), self.loop)
        future.result(timeout=120 if self.firmware and self.firmware.state["busy"] else 30)
        self.loop.call_soon_threadsafe(self.loop.stop)
        self.thread.join(timeout=3)
