"""Bounded background lossless JSONL recording of all RX/TX and derived samples."""
import json
import queue
import threading


class Recording:
    def __init__(self, path, devices):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path, self.count, self.error = path, 0, ''
        self.queue = queue.Queue(8192)
        self.done = threading.Event()
        self.file = path.open('x', encoding='utf-8')
        self.file.write(json.dumps(dict(type='session', version=1, devices=devices,
            audio='ADPCM/Opus blocks; decoded PCM s16 mono 16000Hz', imu='m/s², rad/s; chip axes',
            clock='received_ns=host monotonic; unix_ns=host UTC; uptime_ms=device'))+'\n')
        self.thread = threading.Thread(target=self._run, name='ringo-recorder')
        self.thread.start()

    def submit(self, event):
        if self.error or self.done.is_set():
            return
        try:
            self.queue.put_nowait(event)
        except queue.Full:
            self.error = '录制队列已满，文件不完整'

    def _run(self):
        try:
            while not self.done.is_set() or not self.queue.empty():
                try:
                    event = self.queue.get(timeout=.1)
                except queue.Empty:
                    self.file.flush()
                    continue
                self.file.write(json.dumps(event, ensure_ascii=False, separators=(',', ':'))+'\n')
                self.count += 1
            self.file.write(json.dumps(dict(type='end', records=self.count,
                complete=not bool(self.error), error=self.error))+'\n')
        except Exception as exc:
            self.error = f'录制失败：{exc}'
        finally:
            self.file.close()

    def close(self):
        self.done.set()
        self.thread.join()
