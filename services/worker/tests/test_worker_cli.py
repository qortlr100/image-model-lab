import json
import signal
from threading import Event

import pytest
from image_model_lab_worker.__main__ import health_payload, main, run_forever


def test_health_command(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["health"]) == 0

    captured = capsys.readouterr()
    assert json.loads(captured.out) == health_payload()


def test_version_command(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["version"]) == 0

    captured = capsys.readouterr()
    assert json.loads(captured.out) == {
        "service": "worker",
        "version": "0.1.0",
    }


def test_run_can_stop_without_polling_work() -> None:
    stop_event = Event()
    stop_event.set()

    run_forever(stop_event)


def test_run_stops_after_shutdown_signal(monkeypatch: pytest.MonkeyPatch) -> None:
    registered_signals: list[int] = []

    def fake_signal(signum: int, handler: object) -> object:
        if callable(handler):
            registered_signals.append(signum)
            if len(registered_signals) == 2:
                handler(signum, None)
        return signal.SIG_DFL

    monkeypatch.setattr(signal, "signal", fake_signal)
    run_forever()

    assert registered_signals == [signal.SIGINT, signal.SIGTERM]
