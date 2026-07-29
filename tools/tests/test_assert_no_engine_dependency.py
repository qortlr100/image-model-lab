from __future__ import annotations

import assert_no_engine_dependency as guard
import pytest


def test_torch_is_blocked() -> None:
    assert "torch" in guard.BLOCKED_MODULES


def test_an_installed_module_fails_the_assertion(capsys: pytest.CaptureFixture[str]) -> None:
    assert guard.main(("json",)) == 1
    assert "json" in capsys.readouterr().err


def test_absent_modules_pass_the_assertion(capsys: pytest.CaptureFixture[str]) -> None:
    assert guard.main(("image_model_lab_absent_engine",)) == 0
    assert "no engine dependency found" in capsys.readouterr().out
