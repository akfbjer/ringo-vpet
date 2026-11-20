"""Legacy clock calibration: 300 exchanges, 16 ms filter, linear clock fit.

The sampling, ordering and JSON fields follow desktop/device_runtime.py in the
original project. Validation happens before fitting/saving, so failed attempts
cannot produce a misleading calibration file.
"""
import asyncio
import json
from pathlib import Path
import time
import numpy as np

PACKET_COUNT = 300
PACKET_INTERVAL = .1
SETTLE_SECONDS = 1.0
MAX_DELTA = .016
MIN_SAMPLES = 20


def fit_clock(start, end, device, indices):
    start = np.sort(np.asarray(start, dtype=float))
    end = np.sort(np.asarray(end, dtype=float))
    device = np.sort(np.asarray(device, dtype=float))
    indices = np.sort(np.asarray(indices, dtype=int))
    if not len(indices) or np.any(indices < 0) or np.any(indices >= len(start)):
        raise ValueError("同步应答序号无效")
    start = start[indices]
    if not (len(start) == len(end) == len(device)):
        raise ValueError("同步应答数量不一致")
    if not all(np.all(np.isfinite(x)) for x in (start, end, device)):
        raise ValueError("同步时间戳无效")
    midpoint = (start + end) / 2
    delta = end - start
    order = np.argsort(delta, kind="stable")
    keep = order[(delta[order] >= 0) & (delta[order] < MAX_DELTA)]
    if len(keep) < MIN_SAMPLES:
        raise ValueError("校准数据不足，请重新同步")
    pc, ring, latency = midpoint[keep], device[keep], delta[keep]
    x = np.c_[np.ones(len(ring)), ring]
    try:
        intercept, slope = np.linalg.inv(x.T.dot(x)).dot(x.T).dot(pc)
    except np.linalg.LinAlgError as exc:
        raise ValueError("同步时间戳无法拟合") from exc
    if not np.isfinite(intercept) or not np.isfinite(slope) or slope <= 0:
        raise ValueError("同步拟合无效")
    return dict(intercept=float(intercept), slope=float(slope),
                pc_timestamps=pc.tolist(), ring_timestamps=ring.tolist(),
                pc_delta_time=latency.tolist())


def save_clock(payload, directory: Path):
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f'calib_time_{int(payload["saved_epoch"])}.json'
    # Each real attempt takes >30 seconds; exclusive creation protects old data.
    with path.open("x", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False)
    return path


async def calibrate(ring, directory: Path, progress=lambda *_: None, *, valid=lambda: True):
    if not ring.connected or not valid():
        raise RuntimeError("设备未连接")
    ring.reset_time_calib_data()
    ring.clear_time_calibration()
    try:
        for index in range(PACKET_COUNT):
            if not ring.connected or not valid():
                raise RuntimeError("同步期间设备断开")
            await asyncio.wait_for(ring.calib_time(index=index), timeout=5)
            progress(index+1, PACKET_COUNT)
            await asyncio.sleep(PACKET_INTERVAL)
        await asyncio.sleep(SETTLE_SECONDS)
        if not ring.connected or not valid():
            raise RuntimeError("同步期间设备断开")
        payload = fit_clock(ring.start_calib_timestamps, ring.end_calib_timestamps,
                            ring.ring_timestamps, ring.end_indices)
        payload.update(ring_mac=str(ring.address), saved_perf_counter=time.perf_counter(),
                       saved_epoch=time.time())
        path = await asyncio.to_thread(save_clock, payload, directory)
        if not ring.connected or not valid():
            raise RuntimeError("同步完成时设备已断开，请重新同步")
        ring.set_time_calibration(payload["intercept"], payload["slope"])
        return path
    finally:
        ring.reset_time_calib_data()
