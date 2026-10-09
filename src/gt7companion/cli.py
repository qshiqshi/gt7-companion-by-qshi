"""Start the program:  python -m gt7companion [--demo | --live] [--lan] [--port 8707]"""
from __future__ import annotations

import argparse
import logging
import socket
import sys

from . import APP_NAME, __version__

DEFAULT_PORT = 8707


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="gt7companion",
        description=f"{APP_NAME} – unofficial dashboard and stream overlay for Gran Turismo 7 telemetry.")
    source = parser.add_mutually_exclusive_group()
    source.add_argument("--demo", action="store_const", const="demo", dest="source",
                        help="play the recorded demo drive in a loop (no console needed)")
    source.add_argument("--live", action="store_const", const="live", dest="source",
                        help="listen to the PlayStation in the home network")
    parser.add_argument("--lan", action=argparse.BooleanOptionalAction, default=None,
                        help="let other devices in the home network open the dashboard "
                             "(default: as chosen in the settings)")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT,
                        help=f"port of the web pages (default {DEFAULT_PORT})")
    parser.add_argument("--ps5", metavar="IP", help="address of the console; without it the console is searched")
    parser.add_argument("-v", "--verbose", action="store_true", help="more detailed log output")
    parser.add_argument("--version", action="version", version=f"{APP_NAME} {__version__}")
    return parser


def port_is_free(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        if sys.platform != "win32":
            # Without this a port in TIME_WAIT (just closed) counts as taken on Unix.
            probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            probe.bind((host, port))
        except OSError:
            return False
    return True


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s", datefmt="%H:%M:%S")

    from .settings import Settings

    settings = Settings()
    if args.ps5 is not None:
        try:
            settings.update({"ps5_ip": args.ps5})
        except ValueError:
            print(f"Not a valid address: {args.ps5}", file=sys.stderr)
            return 2
    source = args.source or settings["source"]
    lan = settings["lan"] if args.lan is None else args.lan

    host = "0.0.0.0" if lan else "127.0.0.1"
    if not port_is_free(host, args.port):
        print(f"Port {args.port} is already in use – is the program running already? "
              f"Choose another one with --port.", file=sys.stderr)
        return 1

    import uvicorn

    from .app import create_app
    from .netinfo import local_addresses

    print(f"{APP_NAME} {__version__}")
    print(f"  On this computer:      http://127.0.0.1:{args.port}/")
    if lan:
        for address in local_addresses():
            print(f"  In your home network:  http://{address}:{args.port}/")
    print(f"  Connect other devices: http://127.0.0.1:{args.port}/connect")
    print("  Source:                " + ("demo drive (no console needed)" if source == "demo"
                                         else "PlayStation in the home network"))
    print("  Stop with Ctrl+C.", flush=True)

    from .engineer import helper

    app = create_app(settings, source=source, lan=lan, port=args.port, helper=helper.find())
    uvicorn.run(app, host=host, port=args.port, log_level="debug" if args.verbose else "warning",
                ws_max_size=256 * 1024, access_log=False)
    return 0
