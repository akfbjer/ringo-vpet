"""Low-rate state bridge. No per-sample Qt signals or synchronous runtime calls."""
from PyQt6.QtCore import QObject, QTimer, pyqtProperty, pyqtSignal, pyqtSlot
from ring.ui.device_model import DeviceModel
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtCore import QUrl
import threading


class Bridge(QObject):
    changed = pyqtSignal()
    selectedChanged = pyqtSignal()
    autoRangeChanged = pyqtSignal()
    shutdownFinished = pyqtSignal()
    shutdownFailed = pyqtSignal(str)
    densityChanged = pyqtSignal()
    densityHistoryChanged = pyqtSignal()
    densityRingsChanged = pyqtSignal()
    firmwareCatalogChanged = pyqtSignal()
    _densityArrived = pyqtSignal(object)

    def __init__(self, engine):
        super().__init__()
        self.engine = engine
        self._devices = DeviceModel(self)
        self._connected_devices = DeviceModel(self)
        self._gesture_devices = DeviceModel(self)
        self._firmware_devices = DeviceModel(self)
        self._firmware_catalog = []
        self._state = dict(devices=[], events=[], status="启动中", scanning=False, demo=False,
            recording=False, serverReady=False, frames=0, recorded=0, error="", port=engine.port, syncing=False, syncProgress=0, recordBusy=False, click={}, gestures=dict(devices=[], history=[]))
        self._selected = ""
        self._auto_range = True
        self.pending = None
        self.closing = False
        self._density_state = {}
        self._density_history = []
        self._density_rings = []
        self._density_pending = None
        self._density_visible = False
        self._densityArrived.connect(self._apply_density)
        self.density_timer = QTimer(self)
        self.density_timer.setInterval(50)  # Model outputs at 20 Hz; raw Trace is 30 Hz.
        self.density_timer.timeout.connect(self._request_density)
        self.shutdownFailed.connect(self._shutdown_failed)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.poll)
        self.timer.start(200)

    @pyqtProperty(QObject, constant=True)
    def gestureDevices(self):
        return self._gesture_devices

    @pyqtProperty(QObject, constant=True)
    def firmwareDevices(self):
        return self._firmware_devices

    @pyqtProperty("QVariantList", notify=firmwareCatalogChanged)
    def firmwareCatalog(self):
        return self._firmware_catalog

    @pyqtProperty(bool, constant=True)
    def hasRecording(self):
        return "recording" in self.engine.product.apps

    @pyqtProperty("QVariantList", constant=True)
    def pages(self):
        return self.engine.product.pages

    @pyqtProperty(bool, notify=autoRangeChanged)
    def autoRange(self):
        return self._auto_range

    @pyqtSlot(bool)
    def setAutoRange(self, enabled):
        if self._auto_range != enabled:
            self._auto_range = enabled
            self.autoRangeChanged.emit()

    @pyqtProperty(QObject, constant=True)
    def connectedDevices(self):
        return self._connected_devices

    @pyqtProperty(QObject, constant=True)
    def devices(self):
        return self._devices

    @pyqtProperty('QVariantMap', notify=changed)
    def state(self):
        return self._state

    @pyqtProperty('QVariantMap', notify=densityChanged)
    def densityState(self):
        return self._density_state

    @pyqtProperty('QVariantList', notify=densityHistoryChanged)
    def densityHistory(self):
        return self._density_history

    @pyqtProperty('QVariantList', notify=densityRingsChanged)
    def densityRings(self):
        return self._density_rings

    @pyqtSlot(bool)
    def setDensityVisible(self, visible):
        self._density_visible = visible and not self.closing
        if self._density_visible:
            self.density_timer.start()
            self._request_density()
        else:
            self.density_timer.stop()

    def _request_density(self):
        if not self._density_visible or self.closing or self._density_pending is not None:
            return
        future = self.engine.density_snapshot_future()
        self._density_pending = future
        # Apply when ready, instead of waiting another 50/200 ms timer tick.
        future.add_done_callback(self._densityArrived.emit)

    @pyqtSlot(object)
    def _apply_density(self, future):
        if future is not self._density_pending:
            return
        self._density_pending = None
        if not self._density_visible or self.closing:
            return
        try:
            state = dict(future.result())
        except Exception as exc:
            self.engine.log(str(exc))
            return
        history = state.pop("history", [])
        # Preserve the ListView model between actual events. Telemetry must not
        # destroy and recreate every history row on each animation update.
        if history != self._density_history:
            self._density_history = history
            self.densityHistoryChanged.emit()
        if state != self._density_state:
            self._density_state = state
            self.densityChanged.emit()

    @pyqtProperty(str, notify=selectedChanged)
    def selected(self):
        return self._selected

    @pyqtSlot(str)
    def select(self, address):
        if self._selected != address:
            self._selected = address
            self.selectedChanged.emit()

    @pyqtSlot(str)
    def action(self, name):
        if name in ("scan", "demo", "record", "sync"):
            self.engine.command(name)

    @pyqtSlot(str, str)
    def ringoControl(self, address, action):
        self.engine.command("ringo_control", address, action)

    @pyqtSlot(str)
    def toggleGestures(self, address):
        self.engine.command("gesture", address)

    @pyqtSlot(str, str)
    def density(self, action, address):
        self.engine.command("density", action, address)

    @pyqtSlot(str, bool, bool, bool)
    def startClick(self, address, cursor, dispatch, mapping):
        self.engine.command("click_start", address, cursor, dispatch, mapping)

    @pyqtSlot()
    def stopClick(self):
        self.engine.command("click_stop")

    @pyqtSlot(str, str, str)
    def handwriting(self, action, address, mode):
        self.engine.command("handwriting", action, address, mode)

    @pyqtSlot()
    def refreshFirmware(self):
        self.engine.command("firmware_refresh")

    @pyqtSlot(str, str)
    def startFirmware(self, address, firmware_id):
        self.engine.command("firmware_start", address, firmware_id)

    @pyqtSlot()
    def cancelFirmware(self):
        self.engine.command("firmware_cancel")

    @pyqtSlot()
    def openFirmwareFolder(self):
        if self.engine.firmware:
            path = self.engine.firmware.root
            path.mkdir(parents=True, exist_ok=True)
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))

    @pyqtSlot(str, str)
    def setR1Mode(self, address, mode):
        self.engine.command("r1_mode", address, mode)

    @pyqtSlot(str)
    def connectDevice(self, address):
        self.engine.command("connect", address)

    @pyqtSlot()
    def openRecordings(self):
        self.engine.data_dir.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.engine.data_dir)))

    def poll(self):
        if self.pending and self.pending.done():
            try:
                self._state = self.pending.result()
                self._devices.update(self._state["devices"])
                self._gesture_devices.update(self._state["gestures"]["devices"])
                self._connected_devices.update([d for d in self._state["devices"] if d["connected"]])
                self._firmware_devices.update([d for d in self._state["devices"] if not d["simulated"]])
                catalog = self._state.get("firmware", {}).get("firmwares", [])
                if catalog != self._firmware_catalog:
                    self._firmware_catalog = catalog
                    self.firmwareCatalogChanged.emit()
                devices = self._state["devices"]
                density_rings = [dict(address=d["address"], name=d["name"]) for d in devices
                                 if d.get("driver") == "r1" and d.get("imuMode") == "ulp100"
                                 and d["connected"] and not d.get("busy") and not d.get("simulated")]
                if density_rings != self._density_rings:
                    self._density_rings = density_rings
                    self.densityRingsChanged.emit()
                if self._selected not in {d["address"] for d in devices}:
                    self.select(devices[0]["address"] if devices else "")
                self.changed.emit()
            except Exception as exc:
                self.engine.log(str(exc))
            self.pending = None
        if self.pending is None:
            self.pending = self.engine.snapshot_future()

    @pyqtSlot()
    def shutdown(self):
        if self.closing:
            return
        self.closing = True
        self.timer.stop()
        self.density_timer.stop()
        def finish():
            try:
                self.engine.close()
            except Exception as exc:
                self.shutdownFailed.emit(str(exc))
                return
            self.shutdownFinished.emit()
        threading.Thread(target=finish, name="ring-shutdown").start()

    @pyqtSlot(str)
    def _shutdown_failed(self, message):
        self._state["status"] = f"退出失败：{message}"
        self.changed.emit()
