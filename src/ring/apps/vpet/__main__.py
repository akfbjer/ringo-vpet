"""Manual VPet command and Ringo connection diagnostics."""
import argparse
import json

from .bridge import COMMANDS, ringo_messages, send_command


def main() -> int:
    parser = argparse.ArgumentParser(description="Ringo to Steam VPet bridge")
    sub = parser.add_subparsers(dest="mode", required=True)
    send = sub.add_parser("send", help="send one manual VPet command")
    send.add_argument("command", choices=sorted(COMMANDS))
    send.add_argument("--dx", type=float, default=0)
    send.add_argument("--dy", type=float, default=0)
    watch = sub.add_parser("ringo", help="show Ringo status and a few IMU frames")
    watch.add_argument("--ring", help="BLE address of one Ringo")
    watch.add_argument("--count", type=int, default=5)
    args = parser.parse_args()
    try:
        if args.mode == "send":
            response = send_command(args.command, dx=args.dx, dy=args.dy)
            print(json.dumps(response, ensure_ascii=False))
            return 0 if response.get("ok") is True else 1
        seen = 0
        for message in ringo_messages(ring_address=args.ring):
            print(json.dumps(message, ensure_ascii=False))
            if message.get("type") == "imu":
                seen += 1
                if seen >= args.count:
                    break
        return 0
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        parser.exit(1, f"error: {exc}\n")


if __name__ == "__main__":
    raise SystemExit(main())
