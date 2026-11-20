"""Bounded 30 Hz preview. Raw samples stay in Python; QML never sees sample arrays."""
import numpy as np
from ring.core.plot_scale import axis_limit
from ring.core.plot_segments import plot_segments
from ring.core import ringo_plot
from PyQt6.QtCore import QTimer, QPointF, pyqtProperty, pyqtSignal
from PyQt6.QtGui import QColor, QPen, QPainter, QPolygonF
from PyQt6.QtQuick import QQuickPaintedItem


class Trace(QQuickPaintedItem):
    engine = None
    sdkStyleChanged = pyqtSignal()
    rangeChanged = pyqtSignal()
    channelChanged = pyqtSignal()
    yLimitChanged = pyqtSignal()
    autoRangeChanged = pyqtSignal()
    addressChanged = pyqtSignal()
    runningChanged = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._sdk_style = False
        self._range = (-12.0, 12.0)
        self._channel = 0
        self._y_limit = 20.0
        self._auto_range = True
        self._address = ""
        self._running = True
        self.samples = None
        self.last_key = None
        self.polygons = [QPolygonF() for _ in range(3)]
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.refresh)
        self.timer.start(33)
        self.setAntialiasing(True)

    @pyqtProperty(bool, notify=sdkStyleChanged)
    def sdkStyle(self):
        return self._sdk_style

    @sdkStyle.setter
    def sdkStyle(self, value):
        if value != self._sdk_style:
            self._sdk_style = value
            self.last_key = None
            self.sdkStyleChanged.emit()
            self.refresh()

    @pyqtProperty(float, notify=rangeChanged)
    def yMinimum(self):
        return self._range[0]

    @pyqtProperty(float, notify=rangeChanged)
    def yMaximum(self):
        return self._range[1]

    @pyqtProperty(int, notify=channelChanged)
    def channel(self):
        return self._channel

    @channel.setter
    def channel(self, value):
        self._channel = value
        self._set_limit(20.0 if value == 0 else 5.0)
        self.last_key = None
        self.channelChanged.emit()

    @pyqtProperty(str, notify=addressChanged)
    def address(self):
        return self._address

    @address.setter
    def address(self, value):
        if value != self._address:
            self._address = value
            self.samples = None
            self._set_limit(20.0 if self._channel == 0 else 5.0)
            self.last_key = None
            self.addressChanged.emit()
            self.update()

    @pyqtProperty(bool, notify=runningChanged)
    def running(self):
        return self._running

    @running.setter
    def running(self, value):
        if value != self._running:
            self._running = value
            self.runningChanged.emit()

    @pyqtProperty(bool, notify=autoRangeChanged)
    def autoRange(self):
        return self._auto_range

    @autoRange.setter
    def autoRange(self, value):
        if value != self._auto_range:
            self._auto_range = value
            self.last_key = None
            self.autoRangeChanged.emit()
            self.refresh()

    @pyqtProperty(float, notify=yLimitChanged)
    def yLimit(self):
        return self._y_limit

    def _set_limit(self, value):
        if self._y_limit != value:
            self._y_limit = value
            self.yLimitChanged.emit()

    def refresh(self):
        if self.isVisible() and self._running and self.engine:
            samples = self.engine.preview(self._address)
            key = (self._address, len(samples), samples[-1, 0]) if samples is not None and len(samples) else (self._address, 0)
            if key != self.last_key:
                self.last_key = key
                self.samples = samples
                minimum = 20.0 if self._channel == 0 else 5.0
                if self._sdk_style:
                    values = ringo_plot.preview(samples, self._channel)[1] if samples is not None else np.array([])
                    bounds = ringo_plot.limits(values if self._auto_range else np.array([]), self._channel)
                    if bounds != self._range:
                        self._range = bounds
                        self.rangeChanged.emit()
                elif self._auto_range and samples is not None and len(samples):
                    visible = samples[samples[:, 0] >= samples[-1, 0] - 6]
                    self._set_limit(axis_limit(visible[:, 1+self._channel:4+self._channel], 1.0 if self._channel == 0 else .1, self._y_limit))
                elif self._auto_range:
                    self._set_limit(minimum)
                self.update()

    def paint(self, painter):
        w, h = self.width(), self.height()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        painter.setPen(QPen(QColor("#e9edf2"), 1))
        for i in range(5):
            y = 12+(h-24)*i/4
            painter.drawLine(QPointF(0,y), QPointF(w,y))
        for i in range(1, 8):
            x = w*i/8
            painter.drawLine(QPointF(x,12), QPointF(x,h-12))
        data = self.samples
        if data is None or len(data) < 2:
            painter.setPen(QColor("#99a3b4"))
            painter.drawText(QPointF(max(12,w/2-60), h/2), "等待 IMU 数据")
            return
        if self._sdk_style:
            times, values, (start, end) = ringo_plot.preview(data, self._channel)
            xs = (times - start) / (end - start) * w
            low, high = self._range
            ys = 12 + (high - values) / (high - low) * (h - 24)
            colors = ringo_plot.COLORS[self._channel // 3]
            segments = [np.arange(len(times))]
        else:
            values = data[:, 1+self._channel:4+self._channel]
            colors = ("#7465df", "#27a99c", "#dd9560")
            xs = (data[:,0]-data[-1,0]+6)/6*w
            valid = xs >= 0
            xs, values = xs[valid], values[valid]
            segments = plot_segments(data[valid, 0], w)
            ys = h/2-values/self._y_limit*(h-24)/2
        painter.setClipRect(0, 12, int(w), max(0, int(h-24)))
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        for axis, color in enumerate(colors):
            painter.setPen(QPen(QColor(color), 1.6))
            points = self.polygons[axis]
            for indices in segments:
                count = len(indices)
                points.resize(count)
                # Fill contiguous Qt point storage without per-sample Python objects.
                storage = points.data()
                storage.setsize(count * 2 * 8)
                coordinates = np.frombuffer(storage, dtype=np.float64).reshape(count, 2)
                coordinates[:, 0] = xs[indices]
                coordinates[:, 1] = ys[indices, axis]
                if count == 1:
                    painter.drawPoint(points[0])
                else:
                    painter.drawPolyline(points)
