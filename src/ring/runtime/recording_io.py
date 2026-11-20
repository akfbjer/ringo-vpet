"""HDF5 recording schema, streaming compatibility reader and JSONL export."""
import gzip
import json
from pathlib import Path
import numpy as np

FORMAT = 'ring-studio-imu'
VERSION = 1
CHUNK_SIZE = 1024
SAMPLE_DTYPE = np.dtype([
    ('device', '<u4'), ('sequence', '<u8'), ('flags', 'u1'),
    ('timestamp', '<f8'), ('host_timestamp', '<f8'), ('received', '<f8'),
    ('acc', '<f8', (3,)), ('gyr', '<f8', (3,)),
])


def read_recording(path, *, allow_incomplete=False):
    """Stream dictionaries from HDF5, gzip JSONL or legacy plain JSONL.

    HDF5 is read in bounded blocks; no whole-recording allocation. By default
    reject sessions whose writer did not finish. Completed files with reported
    gaps/overflow remain readable; inspect metadata for acquisition completeness.
    """
    path = Path(path)
    with path.open('rb') as probe:
        magic = probe.read(8)
    if magic == b'\x89HDF\r\n\x1a\n':
        import h5py
        with h5py.File(path, 'r') as file:
            if file.attrs.get('format') != FORMAT or file.attrs.get('version') != VERSION:
                raise ValueError('Unsupported HDF5 recording schema')
            if not allow_incomplete and not file.attrs.get('closed_cleanly', False):
                raise ValueError('Recording did not finish; explicitly allow incomplete recovery')
            samples = file['samples']
            if samples.dtype != SAMPLE_DTYPE:
                raise ValueError('Invalid sample dtype')
            count = int(file.attrs['committed_samples'])
            if count < 0 or count > len(samples):
                raise ValueError('Invalid committed sample count')
            devices = {int(key): (group.attrs['address'], group.attrs['name'])
                       for key, group in file['devices'].items()}
            for start in range(0, count, CHUNK_SIZE):
                for row in samples[start:min(start+CHUNK_SIZE, count)]:
                    address, name = devices[int(row['device'])]
                    flags = int(row['flags'])
                    yield dict(type='imu', address=address, name=name,
                        sequence=int(row['sequence']), timestamp=float(row['timestamp']),
                        host_timestamp=float(row['host_timestamp']), received=float(row['received']),
                        simulated=bool(flags & 1), discontinuity=bool(flags & 2),
                        acc=row['acc'].tolist(), gyr=row['gyr'].tolist())
    else:
        opener = gzip.open if magic[:2] == b'\x1f\x8b' else open
        with opener(path, 'rt', encoding='utf-8') as handle:
            for line in handle:
                if line.strip():
                    yield json.loads(line)


def export_jsonl(source, destination):
    """Exclusive output creation; remove an unsuccessful export, preserve source."""
    destination = Path(destination)
    handle = destination.open('x', encoding='utf-8')
    try:
        with handle:
            for sample in read_recording(source):
                handle.write(json.dumps(sample, ensure_ascii=False, separators=(',', ':'))+'\n')
    except BaseException:
        destination.unlink(missing_ok=True)
        raise


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description='Export a recording to JSONL without overwriting files')
    parser.add_argument('source', type=Path)
    parser.add_argument('destination', type=Path)
    args = parser.parse_args()
    export_jsonl(args.source, args.destination)
