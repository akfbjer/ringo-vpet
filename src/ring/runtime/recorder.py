"""Bounded asynchronous HDF5 writer: binary samples, deduplicated device metadata."""
import json
import time
import queue
import threading
from pathlib import Path
import h5py
import numpy as np
from ring.runtime.recording_io import FORMAT, VERSION, CHUNK_SIZE, SAMPLE_DTYPE


class Recorder:
    def __init__(self, path: Path, capacity=8192):
        self.path = path
        self.queue = queue.Queue(maxsize=capacity)
        self.error = ""
        self.count = self.gaps = 0
        self.accepting = True
        self.closed = threading.Event()
        self._devices = {}
        path.parent.mkdir(parents=True, exist_ok=True)
        self.meta_path = path.with_suffix('.meta.json')
        self.file = h5py.File(path, 'x')
        try:
            self._manifest(False, '录制尚未正常结束')
            self.file.attrs.update(format=FORMAT, version=VERSION, closed_cleanly=False,
                complete=False, committed_samples=0, acc_unit='m/s^2', gyr_unit='rad/s',
                timestamp_unit='seconds', flags='bit0=simulated, bit1=discontinuity')
            self.file.create_group('devices')
            self.samples = self.file.create_dataset('samples', shape=(0,), maxshape=(None,),
                dtype=SAMPLE_DTYPE, chunks=(CHUNK_SIZE,), compression='gzip', compression_opts=1,
                shuffle=True, fletcher32=True)
            self.file.flush()
        except BaseException:
            self.file.close()
            raise
        self.thread = threading.Thread(target=self._write, name='ring-writer')
        self.thread.start()

    def submit(self, payload):
        if not self.accepting or self.error:
            return
        try:
            self.queue.put_nowait(payload)
        except queue.Full:
            self.error = '录制队列已满：文件不完整，请停止录制并检查磁盘'
            self.accepting = False

    def _flush_batch(self, batch):
        rows = np.empty(len(batch), dtype=SAMPLE_DTYPE)
        gaps = 0
        fields = {'type', 'address', 'name', 'sequence', 'timestamp', 'host_timestamp',
                  'received', 'simulated', 'discontinuity', 'acc', 'gyr'}
        for i, item in enumerate(batch):
            if set(item) != fields or item['type'] != 'imu':
                raise ValueError('Unsupported recording sample schema')
            if len(item['acc']) != 3 or len(item['gyr']) != 3:
                raise ValueError('IMU sample must have six axes')
            key = (item['address'], item['name'])
            if key not in self._devices:
                device_id = len(self._devices)
                self._devices[key] = device_id
                self.file['devices'].create_group(str(device_id)).attrs.update(address=key[0], name=key[1])
            flags = int(bool(item['simulated'])) | (int(bool(item['discontinuity'])) << 1)
            rows[i] = (self._devices[key], item['sequence'], flags, item['timestamp'],
                item['host_timestamp'], item['received'], item['acc'], item['gyr'])
            gaps += int(bool(item['discontinuity']))
        end = self.count + len(rows)
        self.samples.resize((end,))
        self.samples[self.count:end] = rows
        self.file.attrs.modify('committed_samples', end)
        self.file.flush()
        self.count = end
        self.gaps += gaps
        batch.clear()

    def _write(self):
        batch = []
        try:
            last_flush = time.monotonic()
            while not self.closed.is_set() or not self.queue.empty():
                try:
                    batch.append(self.queue.get(timeout=.1))
                except queue.Empty:
                    pass
                if batch and (len(batch) >= CHUNK_SIZE or time.monotonic()-last_flush >= 1):
                    self._flush_batch(batch)
                    last_flush = time.monotonic()
            if batch:
                self._flush_batch(batch)
            self.file.attrs.update(closed_cleanly=True, complete=not bool(self.error) and self.gaps == 0,
                                   discontinuities=self.gaps, error=self.error)
        except Exception as exc:
            self.error = f'录制失败：{exc}'
            self.accepting = False
        finally:
            try:
                self.file.close()
            except Exception as exc:
                self.error = f'录制收尾失败：{exc}'
                self.accepting = False

    def close(self):
        self.accepting = False
        self.closed.set()
        self.thread.join()
        self._manifest(not bool(self.error) and self.gaps == 0, self.error)

    def _manifest(self, complete, error):
        payload = dict(version=3, format='hdf5', schema_version=VERSION, compression='gzip+shuffle',
            compression_level=1, sample_bytes=SAMPLE_DTYPE.itemsize, samples=self.count,
            complete=complete, discontinuities=self.gaps, error=error,
            timestamp='device seconds; received = host monotonic seconds')
        temporary = self.meta_path.with_suffix('.tmp')
        temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
        temporary.replace(self.meta_path)
