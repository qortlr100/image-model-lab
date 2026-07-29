import argparse
import json
import signal
import sys
from collections.abc import Sequence
from threading import Event
from types import FrameType
from typing import cast

from image_model_lab_dgx_agent import __version__

SERVICE_NAME = "dgx-agent"


def health_payload() -> dict[str, str]:
    return {"service": SERVICE_NAME, "status": "ok", "version": __version__}


def version_payload() -> dict[str, str]:
    return {"service": SERVICE_NAME, "version": __version__}


def _wait_until_stopped(stop_event: Event) -> None:
    print(json.dumps(health_payload(), sort_keys=True), flush=True)
    while not stop_event.wait(timeout=30):
        pass


def run_forever(stop_event: Event | None = None) -> None:
    event = stop_event or Event()
    if stop_event is not None:
        _wait_until_stopped(event)
        return

    def request_stop(_signum: int, _frame: FrameType | None) -> None:
        event.set()

    signals = (signal.SIGINT, signal.SIGTERM)
    previous_handlers = tuple(signal.signal(signum, request_stop) for signum in signals)
    try:
        _wait_until_stopped(event)
    finally:
        for signum, previous_handler in zip(signals, previous_handlers, strict=True):
            signal.signal(signum, previous_handler)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Image Model Lab DGX execution agent.")
    parser.add_argument("command", choices=("health", "run", "version"))
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = sys.argv[1:] if argv is None else argv
    command = cast(str, _build_parser().parse_args(arguments).command)

    if command == "run":
        run_forever()
        return 0

    payload = health_payload() if command == "health" else version_payload()
    print(json.dumps(payload, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
