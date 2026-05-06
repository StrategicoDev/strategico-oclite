from __future__ import annotations

import argparse

from .server import run_server
from .store import Store


def main() -> None:
    parser = argparse.ArgumentParser(prog="oclite")
    sub = parser.add_subparsers(dest="command")

    setup = sub.add_parser("setup")
    setup.add_argument("--main-workspace", help="Point the main agent at an existing OpenClaw workspace")

    run = sub.add_parser("run")
    run.add_argument("--host", default="127.0.0.1")
    run.add_argument("--port", type=int, default=8787)
    run.add_argument("--no-telegram", action="store_true")

    sub.add_parser("agents")

    sessions = sub.add_parser("sessions")
    sessions.add_argument("--prune-stale", action="store_true")

    args = parser.parse_args()
    store = Store()

    if args.command == "setup":
        store.setup(main_workspace=args.main_workspace)
        print(f"OCLite initialized at {store.home}")
        return
    if args.command == "run":
        run_server(args.host, args.port, poll_telegram=not args.no_telegram)
        return
    if args.command == "agents":
        for agent in store.list_agents():
            print(f"{agent.id}\t{agent.model}\t{agent.workspace}")
        return
    if args.command == "sessions":
        if args.prune_stale:
            print(f"Marked stale sessions: {store.prune_stale()}")
        for session in store.list_sessions():
            print(f"{session['id']}\t{session['status']}\t{session['lastActiveAt']}")
        return

    parser.print_help()
