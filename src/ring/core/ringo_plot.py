"""Display adapter matching receiver/src/imu/live_plot.py and SDK plot_values.

Input stays in Studio SI units and wire axes; only the display uses degrees/s.
"""
import numpy as np

WINDOW_SECONDS = 3.0
SAMPLE_HZ = 200
COLORS = (("#e74c3c", "#f1c40f", "#2ecc71"),
          ("#e74c3c", "#2ecc71", "#3498db"))


def preview(samples, channel):
    values = samples[:, 1 + channel:4 + channel].copy()
    if channel == 3:
        values = np.rad2deg(values)
    # SDK plots sample ODR, not batched BLE arrival/device packet timestamps.
    times = np.arange(len(samples), dtype=float) / SAMPLE_HZ
    end = times[-1] if len(times) else 0.0
    start = max(0.0, end - WINDOW_SECONDS)
    visible = times >= start
    return times[visible], values[visible], (start, max(start + 1.0, end))


def limits(values, channel):
    finite = values[np.isfinite(values)]
    if not finite.size:
        return (-12.0, 12.0) if channel == 0 else (-50.0, 50.0)
    low, high = float(finite.min()), float(finite.max())
    span = max(high - low, 8.0 if channel == 0 else 40.0)
    middle = (low + high) / 2
    return middle - span * .62, middle + span * .62
