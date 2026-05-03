from __future__ import annotations

import argparse
import json
import os
import sys

from supervisor_lease import acquire_supervisor_lease, heartbeat_supervisor_lease, release_supervisor_lease


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Acquire, refresh, or release the dashboard supervisor lease.")
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("acquire", "heartbeat", "release"):
        item = sub.add_parser(name)
        item.add_argument("--instance-id", required=True)
        item.add_argument("--lease-name", default="dashboard_stack")
        item.add_argument("--ttl-seconds", type=int, default=120)
        item.add_argument("--dsn", default=None)
    sub.choices["acquire"].add_argument("--process-id", type=int, default=os.getpid())
    sub.choices["acquire"].add_argument("--command-line", default=" ".join(sys.argv))
    sub.choices["acquire"].add_argument("--allow-duplicate", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.command == "acquire":
        result = acquire_supervisor_lease(
            supervisor_instance_id=args.instance_id,
            lease_name=args.lease_name,
            process_id=args.process_id,
            command_line=args.command_line,
            ttl_seconds=args.ttl_seconds,
            allow_duplicate=args.allow_duplicate,
            dsn=args.dsn,
        )
        print(json.dumps(result, default=str))
        raise SystemExit(0 if result.get("acquired") else 2)
    if args.command == "heartbeat":
        ok = heartbeat_supervisor_lease(
            supervisor_instance_id=args.instance_id,
            lease_name=args.lease_name,
            ttl_seconds=args.ttl_seconds,
            dsn=args.dsn,
        )
        print(json.dumps({"ok": ok}))
        raise SystemExit(0 if ok else 2)
    ok = release_supervisor_lease(
        supervisor_instance_id=args.instance_id,
        lease_name=args.lease_name,
        dsn=args.dsn,
    )
    print(json.dumps({"ok": ok}))


if __name__ == "__main__":
    main()
