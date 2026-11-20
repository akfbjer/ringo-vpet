"""Bounded background PCM writer; close drains audio and finalizes the WAV header."""
import queue
import struct
import threading
import wave


class WavRecording:
    def __init__(self, path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self.samples = 0
        self.error = ''
        self.queue = queue.Queue(256)
        self.done = threading.Event()
        self.file = path.open('xb')
        try:
            self.wave = wave.open(self.file, 'wb')
            self.wave.setparams((1, 2, 16000, 0, 'NONE', 'not compressed'))
        except BaseException:
            self.file.close()
            raise
        self.thread = threading.Thread(target=self._run, name='ringo-wav')
        self.thread.start()

    def submit(self, samples):
        if self.done.is_set() or self.error:
            return
        try:
            self.queue.put_nowait(struct.pack('<' + 'h' * len(samples), *samples))
        except queue.Full:
            self.error = '录音写入队列已满，WAV 不完整'

    def _run(self):
        try:
            while not self.done.is_set() or not self.queue.empty():
                try:
                    pcm = self.queue.get(timeout=.05)
                except queue.Empty:
                    continue
                self.wave.writeframesraw(pcm)
                self.samples += len(pcm) // 2
        except Exception as exc:
            self.error = f'音频保存失败：{exc}'
        finally:
            try:
                self.wave.close()
            except Exception as exc:
                self.error = f'WAV 收尾失败：{exc}'
            finally:
                self.file.close()

    def close(self):
        self.done.set()
        self.thread.join()
