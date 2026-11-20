"""Find continuity boundaries before decimation so gaps never get bridged."""
import numpy as np

GAP_SECONDS = .015


def plot_segments(timestamps, width):
    timestamps = np.asarray(timestamps)
    count = len(timestamps)
    if not count:
        return []
    delta = np.diff(timestamps)
    cuts = np.flatnonzero((delta <= 0) | (delta > GAP_SECONDS)) + 1
    boundaries = np.concatenate(([0], cuts, [count]))
    stride = max(1, int(np.ceil(count / max(1, int(width)))))
    segments = []
    for start, stop in zip(boundaries[:-1], boundaries[1:]):
        indices = np.arange(start, stop, stride)
        # Retain both endpoints, including a short fragment next to a gap.
        if indices[-1] != stop - 1:
            indices = np.append(indices, stop - 1)
        segments.append(indices)
    return segments
