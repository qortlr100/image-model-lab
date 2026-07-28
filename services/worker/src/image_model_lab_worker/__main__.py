import argparse
import json
import sys
from collections.abc import Sequence
from threading import Event
from typing import cast

from image_model_lab_worker import __version__

SERVICE_NAME = "worker"


def health_payload() -> dict[str, str]:
    return {"service": SERVICE_NAME, "status": "ok", "version": __version__}


def version_payload() -> dict[str, str]:
    return {"service": SERVICE_NAME, "version": __version__}


def run_forever(stop_event: Event | None = None) -> None:
    event = stop_event or Event()
    print(json.dumps(health_payload(), sort_keys=True), flush=True)
    while not event.wait(timeout=30):
        pass


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Image Model Lab control-plane worker.")
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
