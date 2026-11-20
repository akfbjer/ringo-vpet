"""Bounded, thread-safe preview storage. Acquisition never waits for rendering."""
import threading
import numpy as np


class SampleBuffer:
    def __init__(self, capacity=1200):
        self.data = np.empty((capacity, 7), dtype=np.float64)
        self.capacity, self.count, self.cursor = capacity, 0, 0
        self.lock = threading.Lock()

    def append(self, timestamp, values):
        with self.lock:
            self.data[self.cursor, 0] = timestamp
            self.data[self.cursor, 1:] = values
            self.cursor = (self.cursor + 1) % self.capacity
            self.count = min(self.count + 1, self.capacity)

    def clear(self):
        with self.lock:
            self.count = self.cursor = 0

    def snapshot(self):
        with self.lock:
            if self.count < self.capacity:
                return self.data[:self.count].copy()
            return np.concatenate((self.data[self.cursor:], self.data[:self.cursor]))
