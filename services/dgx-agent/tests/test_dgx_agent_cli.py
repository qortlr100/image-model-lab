import json
from threading import Event

import pytest
from image_model_lab_dgx_agent.__main__ import health_payload, main, run_forever


def test_health_command(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["health"]) == 0

    captured = capsys.readouterr()
    assert json.loads(captured.out) == health_payload()


def test_version_command(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["version"]) == 0

    captured = capsys.readouterr()
    assert json.loads(captured.out) == {
        "service": "dgx-agent",
        "version": "0.1.0",
    }


def test_run_can_stop_without_polling_work() -> None:
    stop_event = Event()
    stop_event.set()

    run_forever(stop_event)
