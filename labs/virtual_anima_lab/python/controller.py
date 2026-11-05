#!/usr/bin/env python3
"""P5-A standalone test controller for the ANIMA actor in a running Godot Lab."""

import argparse
import time

try:
    from .lab_client import LabClient, LabRejected
except ImportError:
    from lab_client import LabClient, LabRejected


def _pos(data):
    cell = data.get("position", data.get("self", {}))
    return f"({cell.get('x', '?')}, {cell.get('y', '?')})"


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=46019)
    parser.add_argument("--auto", action="store_true",
                        help="walk a small repeatable loop while Human moves separately")
    parser.add_argument("--steps", type=int, default=24)
    parser.add_argument("--interval", type=float, default=0.65)
    args = parser.parse_args(argv)
    if args.steps < 1 or args.interval < 0.05:
        parser.error("steps must be >=1 and interval >=0.05")
    with LabClient(args.port, role="agent", timeout=5) as client:
        ping = client.call("ping")["data"]
        print(f"Virtual Lab: {ping['world_version']} / seed {ping['seed']}")
        print("Python controls ANIMA only. Human uses Godot WASD/arrows.")
        if args.auto:
            pattern = ("E", "N", "S", "W")
            for index in range(args.steps):
                direction = pattern[index % len(pattern)]
                try:
                    response = client.call("move", direction=direction)["data"]
                    print(
                        f"{index + 1:02} {direction}: "
                        f"{_pos(response)} — {response['reason']}",
                        flush=True,
                    )
                except LabRejected as error:
                    print(f"{index + 1:02}: command rejected: {error.error}")
                time.sleep(args.interval)
        else:
            print("ANIMA> w/a/s/d = move, o = observe, q = quit")
            while True:
                entry = input("ANIMA> ").strip().lower()
                if entry in ("q", "quit", "exit"):
                    return 0
                if entry in ("w", "a", "s", "d"):
                    direction = {"w": "N", "a": "W", "s": "S", "d": "E"}[entry]
                    try:
                        result = client.call("move", direction=direction)["data"]
                        print(f"{_pos(result)}  {result['reason']}")
                    except LabRejected as error:
                        print(f"Rejected: {error.error}")
                elif entry == "o":
                    observation = client.call("observe")["data"]
                    print(
                        f"self={_pos(observation)} | "
                        f"visible={observation['visible']}"
                    )
                else:
                    print("Use w/a/s/d, o or q")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
