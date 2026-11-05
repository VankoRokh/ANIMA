#!/usr/bin/env python3
"""P5 Lab test controller. --typed selects the v0.2 contract; no ANIMA Core."""

import argparse
import time
import uuid

try:
    from .contracts import validate_observation, validate_receipt
    from .lab_client import LabClient, LabRejected, PROTOCOL, PROTOCOL_V2
except ImportError:
    from contracts import validate_observation, validate_receipt
    from lab_client import LabClient, LabRejected, PROTOCOL, PROTOCOL_V2


def _pos(data):
    cell = data.get(
        "position", data.get("self", data.get("self_position", {}))
    )
    return f"({cell.get('x', '?')}, {cell.get('y', '?')})"


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=46019)
    parser.add_argument("--auto", action="store_true",
                        help="repeat a small route while Human moves independently")
    parser.add_argument("--typed", action="store_true",
                        help="P5-B versioned observation/conditional-action contract")
    parser.add_argument("--steps", type=int, default=24)
    parser.add_argument("--interval", type=float, default=0.65)
    args = parser.parse_args(argv)
    if args.steps < 1 or args.interval < 0.05:
        parser.error("steps must be >=1 and interval >=0.05")

    version = PROTOCOL_V2 if args.typed else PROTOCOL
    session_id = uuid.uuid4().hex[:12]
    counter = 0
    with LabClient(
        args.port, role="agent", protocol=version, timeout=5,
    ) as client:
        if args.typed:
            hello = client.call("hello")
            print(f"Virtual Lab: {hello['data']['world_version']} / {version}")
        else:
            ping = client.call("ping")["data"]
            print(f"Virtual Lab: {ping['world_version']} / seed {ping['seed']}")
        print("Python controls ANIMA only; Human controls the Godot GUI.")

        def observe():
            response = client.call("observe")
            if args.typed:
                validate_observation(response["data"], response)
            return response["data"]

        def move(direction):
            nonlocal counter
            if not args.typed:
                return client.call("move", direction=direction)["data"]
            sample = observe()
            counter += 1
            operation = f"ctrl:{session_id}:{counter:04d}"
            response = client.call(
                "act",
                operation_id=operation,
                action={"schema": "val.action/0.1", "direction": direction},
                expected_epoch=sample["observed_at"]["epoch"],
                expected_revision=sample["world_revision"],
            )
            return validate_receipt(response["data"], action_id=operation)

        if args.auto:
            pattern = ("E", "N", "S", "W")
            for index in range(args.steps):
                direction = pattern[index % len(pattern)]
                try:
                    response = move(direction)
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
                        result = move(direction)
                        print(f"{_pos(result)}  {result['reason']}")
                    except LabRejected as error:
                        print(f"Rejected: {error.error}")
                elif entry == "o":
                    observation = observe()
                    details = (
                        observation["readings"] if args.typed
                        else observation["visible"]
                    )
                    print(
                        f"self={_pos(observation)} | "
                        f"visible={details}"
                    )
                else:
                    print("Use w/a/s/d, o or q")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
