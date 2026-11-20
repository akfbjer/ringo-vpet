"""Plot recorded Ringo IMU data from a lab JSONL or an IMU HDF5 file."""

import argparse
import json
from pathlib import Path
import sys

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import font_manager


def configure_chinese_font():
    available = {font.name for font in font_manager.fontManager.ttflist}
    for name in ("Microsoft YaHei", "SimHei", "PingFang SC", "Noto Sans CJK SC", "WenQuanYi Micro Hei"):
        if name in available:
            plt.rcParams["font.sans-serif"] = [name]
            plt.rcParams["axes.unicode_minus"] = False
            return


def imu_frames(path):
    if path.suffix.lower() == ".h5":
        sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))
        from ring.runtime.recording_io import read_recording

        for record in read_recording(path):
            if record.get("type") == "imu":
                yield record["address"], record["timestamp"], record["acc"] + record[
                    "gyr"
                ]
    else:
        with path.open(encoding="utf-8") as source:
            for line in source:
                record = json.loads(line)
                if record.get("type") == "decoded" and record.get("kind") == "imu":
                    for frame in record["frames"]:
                        yield record["address"], frame["timestamp"], frame["values"]


def main():
    configure_chinese_font()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("recording", type=Path)
    parser.add_argument("--address", help="Plot only this ring's BLE address")
    parser.add_argument("--output", type=Path, help="PNG output path")
    args = parser.parse_args()

    samples = [
        (address, timestamp, values)
        for address, timestamp, values in imu_frames(args.recording)
        if not args.address or address.lower() == args.address.lower()
    ]
    if not samples:
        parser.error("No IMU frames found in this recording")
    addresses = sorted({address for address, _, _ in samples})
    if len(addresses) > 1:
        parser.error(
            "Multiple rings found; select one with --address: " + ", ".join(addresses)
        )

    start = samples[0][1]
    times = [(timestamp - start) for _, timestamp, _ in samples]
    values = [sample for _, _, sample in samples]
    fig, axes = plt.subplots(2, 1, figsize=(14, 7), sharex=True, layout="constrained")
    for ax, offset, title, unit in (
        (axes[0], 0, "加速度", "m/s²"),
        (axes[1], 3, "角速度", "rad/s"),
    ):
        for index, name in enumerate("XYZ"):
            ax.plot(
                times,
                [row[offset + index] for row in values],
                linewidth=0.8,
                label=name,
            )
        ax.set_ylabel(f"{title} ({unit})")
        ax.grid(alpha=0.25)
        ax.legend(loc="upper right", ncol=3)
    axes[1].set_xlabel("时间 (s)")
    output = args.output or args.recording.with_name(args.recording.stem + "-imu.png")
    fig.savefig(output, dpi=150)
    print(output.resolve())


if __name__ == "__main__":
    main()
