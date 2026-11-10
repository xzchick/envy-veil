"""Command-line entry point. The Veil window is the default.

Every write goes to a brand-new file; Veil never overwrites a carrier or payload.
"""

from __future__ import annotations

import argparse
import getpass
import json
import os
import sys

from . import __version__
from .core import VeilError, capacity, check_passphrase, hide, hide_many, inspect, reveal


def build_parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(
        prog="envy-veil",
        description="Hide an AES-256-GCM encrypted file inside a lossless image (PNG/BMP) or audio "
                    "(WAV) carrier, and recover it. Run with no arguments to open the window. Local "
                    "only: no network, no accounts.")
    root.add_argument("--version", action="version", version=f"envy-veil {__version__}")
    commands = root.add_subparsers(dest="command")
    commands.add_parser("gui", help="open the Veil window (default)")

    h = commands.add_parser("hide", help="encrypt a file and hide it in a carrier")
    h.add_argument("carrier", help="a lossless PNG, BMP or WAV carrier")
    h.add_argument("payload", help="the file to hide")
    h.add_argument("destination", help="a new carrier file to write; never overwritten")

    hm = commands.add_parser("hide-many", help="encrypt several files as one bundle and hide them")
    hm.add_argument("carrier", help="a lossless PNG, BMP or WAV carrier")
    hm.add_argument("destination", help="a new carrier file to write; never overwritten")
    hm.add_argument("--file", action="append", required=True, dest="files", metavar="PATH",
                    help="a file to include in the bundle (repeatable)")

    r = commands.add_parser("reveal", help="extract and decrypt a hidden payload")
    r.add_argument("carrier", help="a carrier that holds a Veil payload")
    r.add_argument("destination",
                   help="a new file for a single payload, or a new directory for a multi-file bundle")

    cap = commands.add_parser("capacity", help="show how many bytes a carrier can hide (read-only)")
    cap.add_argument("carrier")
    cap.add_argument("--payload", default=None, metavar="FILE",
                     help="also check whether this payload fits and how full it would leave the carrier")

    insp = commands.add_parser("inspect", help="report whether a carrier holds a payload (read-only)")
    insp.add_argument("carrier")
    return root


def _passphrase(confirm: bool = False) -> bytes:
    if not sys.stdin.isatty():
        raise VeilError("Open this action in a terminal so the passphrase is not echoed")
    value = getpass.getpass("Veil passphrase: ").encode()
    if confirm and value != getpass.getpass("Repeat passphrase: ").encode():
        raise VeilError("Passphrases do not match")
    return check_passphrase(value)


def _run(args) -> int:
    if args.command == "hide":
        result = hide(args.carrier, args.payload, args.destination, _passphrase(confirm=True))
        print(f"hid {result['payload_bytes']} bytes → {result['output']} ({result['kind']})")
        print(result["note"])
        return 0
    if args.command == "hide-many":
        result = hide_many(args.carrier, args.files, args.destination, _passphrase(confirm=True))
        print(f"hid {result['files']} file(s), {result['payload_bytes']} bytes → "
              f"{result['output']} ({result['kind']})")
        print(result["note"])
        return 0
    if args.command == "reveal":
        result = reveal(args.carrier, args.destination, _passphrase())
        if result["bundle"]:
            print(f"revealed {len(result['files'])} file(s) → {result['output']}/")
            for name in result["files"]:
                print(f"  {name}")
        else:
            print(f"revealed {result['payload_bytes']} bytes → {result['output']}")
        return 0
    if args.command == "capacity":
        payload_bytes = os.path.getsize(args.payload) if args.payload else None
        report = capacity(args.carrier, payload_bytes=payload_bytes)
        print(json.dumps(report, indent=2))
        if report["warning"]:
            print(report["warning"], file=sys.stderr)
        return 1 if (report.get("fits") is False or report["low_capacity"]) else 0
    if args.command == "inspect":
        print(json.dumps(inspect(args.carrier), indent=2))
        return 0
    return 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command in (None, "gui"):
        from .gui import run_app
        return run_app()
    try:
        return _run(args)
    except VeilError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("\nCancelled.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
